# Kế hoạch giảm phụ thuộc vào vnstock

> Cập nhật: 2026-03-21
> Trạng thái: Đang thiết kế — chưa implement

---

## 1. Bức tranh hiện tại

### Mức độ phụ thuộc theo nguồn dữ liệu

| Dữ liệu | Module | Phụ thuộc vnstock | Có fallback? |
|---|---|---|---|
| Danh mục mã (Listing) | `vnstock_data.Listing` | 100% | ❌ |
| BCTC (Finance) | `vnstock_data.Finance` | 100% | ❌ |
| Doanh nghiệp (Company) | `vnstock_data.Company` | 100% | ❌ |
| Ratio summary (Trading) | `vnstock_data.Company` | 100% | ❌ |
| Giá lịch sử (Price) | `vnstock.Quote(source='kbs')` | Primary | ✅ VNDirect REST |
| Cross-validation | `vnstock.Finance(source='kbs')` | 100% | ❌ |

### Rủi ro cụ thể

**TCBS là bài học lớn nhất:** Tháng 3/2026, vnstock v3.5.0 xóa hoàn toàn TCBS — toàn bộ code liên quan đến TCBS trong pipeline phải viết lại khẩn cấp. Tương tự có thể xảy ra với VCI hoặc KBS bất cứ lúc nào.

**Rủi ro xếp loại theo mức độ:**

| Rủi ro | Tác động | Xác suất (ước tính) |
|---|---|---|
| vnstock thay đổi API nội bộ của VCI | Listing + Finance + Company + Trading dừng | Trung bình |
| VCI siết quyền truy cập (yêu cầu auth) | Tương tự | Thấp–Trung bình |
| vnstock_data ngừng maintain | Toàn bộ pipeline dừng | Thấp (dài hạn) |
| KBS đổi endpoint | Price history dừng | Thấp |

### Những gì kiến trúc hiện tại đã làm đúng

```
Hiện tại:
  Jobs → Extractors (vnstock) → Transformers → Loaders → DB
              ↑
         Điểm duy nhất
         phụ thuộc vnstock
         (tốt — có thể thay thế mà không đụng vào tầng khác)
```

`BaseExtractor` là seam đúng chỗ. Khi thêm direct HTTP extractor, chỉ cần implement `extract()` — Jobs, Transformers, Loaders không cần đổi.

---

## 2. Nguyên tắc thiết kế

### 2.1 Validation-first — không thay thế mù

Mỗi nguồn trực tiếp mới **bắt buộc phải** chạy song song với vnstock và so sánh output trước khi được dùng làm primary.

```
Giai đoạn Shadow:     vnstock (primary) + NewSource (shadow, chỉ log diff)
Giai đoạn Parallel:   vnstock + NewSource (cả hai ghi DB, so sánh flags)
Giai đoạn Promotion:  NewSource (primary) + vnstock (fallback)
Giai đoạn Retirement: NewSource (primary) + vnstock (xóa hoàn toàn)
```

Dùng lại cơ sở hạ tầng `data_quality_flags` đã có (Phase 7B) để track sai lệch trong giai đoạn Parallel.

### 2.2 Thứ tự ưu tiên replace

```
Ưu tiên cao:  Dữ liệu thay đổi thường xuyên, rủi ro mất cao
Ưu tiên thấp: Dữ liệu tĩnh, chạy ít, tác động nhỏ nếu dừng
```

| Thứ tự | Dữ liệu | Lý do |
|---|---|---|
| **1** | Giá lịch sử (đã có) | Chạy hàng ngày — rủi ro cao nhất khi gián đoạn |
| **2** | BCTC (Finance) | Dữ liệu lớn nhất, khó backfill nếu mất nguồn |
| **3** | Danh mục mã (Listing) | Nền tảng của toàn pipeline |
| **4** | Ratio summary (Trading) | Có thể tính từ BCTC đã lưu |
| **5** | Thông tin doanh nghiệp (Company) | Thay đổi chậm, ít ưu tiên nhất |

### 2.3 Nguồn thay thế được đánh giá

Thực tế kiểm tra từ môi trường hiện tại (2026-03-21):

| Nguồn | Endpoint | Trạng thái | Ghi chú |
|---|---|---|---|
| **KBS direct REST** | API nội bộ KBS (chưa reverse-engineer) | Chưa kiểm tra | vnstock đang wrap KBS |
| **VNDirect finfo-api** | `finfo-api.vndirect.com.vn/v4/` | ⚠️ Timeout từ local | Ổn định trên VPS |
| **SSI iBoard** | `iboard.ssi.com.vn/dchart/api/` | ⚠️ Một số endpoint 200, một số 404 | Cần khảo sát thêm |
| **CAFEF** | `cafef.vn` APIs | ❌ Blocked/404 | Không ổn định |
| **HOSE/HNX direct** | Không có public API | ❌ | Không khả dụng |
| **SSI FastConnect** | `fc-data.ssi.com.vn` | ❌ 404 từ local | Có thể cần API key |
| **Tính toán từ DB** | Nội bộ từ dữ liệu đã lưu | ✅ | Cho derived metrics |

> **Lưu ý về VNDirect:** Timeout khi test từ máy local (có thể do firewall/ISP) — endpoint này đã hoạt động tốt trước đây và thường ổn định trên VPS. Cần kiểm tra lại trên môi trường deploy thực tế trước khi loại bỏ.

---

## 3. Lộ trình các Phase

### Phase 8A — Tăng cường Price History *(ưu tiên cao)*

**Mục tiêu:** Thêm SSI làm nguồn giá lịch sử thứ 3, xác nhận VNDirect hoạt động trên VPS.

**Vấn đề hiện tại:**
- Primary (KBS via vnstock): ✅ hoạt động
- Fallback (VNDirect REST): ❌ timeout từ local → cần kiểm tra trên VPS

**Hành động:**
1. Deploy và kiểm tra VNDirect fallback trên VPS
2. Nghiên cứu SSI iBoard price history endpoint (reverse-engineer từ browser DevTools)
3. Nếu SSI khả dụng: thêm `etl/extractors/ssi_price.py` làm fallback thứ 2

**Fallback chain sau Phase 8A:**
```
KBS (vnstock) → VNDirect (direct REST) → SSI (direct REST)
```

**Tiêu chí hoàn thành:** Ít nhất 2 nguồn giá hoạt động độc lập nhau.

---

### Phase 8B — Finance trực tiếp: VNDirect finfo-api *(ưu tiên cao)*

**Mục tiêu:** Có nguồn BCTC không qua vnstock — bảo vệ dữ liệu tài chính.

**Nguồn nhắm đến:** VNDirect finfo-api
```
GET https://finfo-api.vndirect.com.vn/v4/financialstatements/
    ?q=code:HPG~reportType:BS~reportTermType:A
    &sort=reportDate&size=10
```

**Hành động:**
1. Xác nhận endpoint hoạt động trên VPS
2. Reverse-engineer schema response → map sang DB columns hiện tại
3. Tạo `etl/extractors/vndirect_finance.py` (direct REST, không vnstock)
4. **Shadow run:** Chạy song song với vnstock VCI, log diff vào `data_quality_flags`
5. Sau 4 tuần shadow không có diff lớn → promote làm fallback

**Ưu điểm:** Dữ liệu VNDirect BCTC thường có `reportDate` chuẩn và đầy đủ hơn.

**Files cần tạo:**
- `etl/extractors/vndirect_finance.py`
- `etl/transformers/vndirect_finance.py`

**Sửa:**
- `jobs/sync_financials.py` — thêm fallback về `vndirect_finance` nếu vnstock lỗi

---

### Phase 8C — Listing trực tiếp: Đa nguồn *(ưu tiên trung bình)*

**Mục tiêu:** Danh mục mã từ ít nhất 2 nguồn độc lập.

**Nguồn nhắm đến:**
- **VNDirect** `finfo-api.vndirect.com.vn/v4/stocks/` — danh sách mã
- **SSI iBoard** — danh sách mã (nếu endpoint ổn định)

**Hành động:**
1. Tạo `etl/extractors/vndirect_listing.py` (direct REST)
2. So sánh với `vnstock_data.Listing` — nếu khớp >99% → promote làm fallback

**Lưu ý:** ICB industry classification có thể khác nhau giữa các nguồn — cần mapping thủ công.

---

### Phase 8D — Tự tính Ratio Summary *(ưu tiên trung bình)*

**Mục tiêu:** `ratio_summary` không còn phụ thuộc vnstock — tính từ dữ liệu BCTC đã có trong DB.

**Phân tích:** Nhiều chỉ số trong `ratio_summary` có thể tính từ `balance_sheets` + `income_statements` + `price_history`:

| Chỉ số | Công thức |
|---|---|
| `pe` | `close_price / eps_basic` |
| `pb` | `close_price / book_value_per_share` |
| `roe` | `net_profit / avg(total_equity)` |
| `roa` | `net_profit / avg(total_assets)` |
| `debt_to_equity` | `total_liabilities / total_equity` |
| `current_ratio` | `total_current_assets / total_current_liabilities` |

**Hành động:**
1. Phân tích toàn bộ columns trong `ratio_summary` — phân loại: tính được vs cần source ngoài
2. Tạo `etl/calculators/ratio_calculator.py` — tính các chỉ số từ dữ liệu DB
3. Chạy song song: tính từ DB vs fetch từ vnstock, so sánh
4. Promote khi sai lệch < 1% (rounding error chấp nhận được)

**Lợi ích bổ sung:** Có thể tính ratio với frequency tùy ý (không phụ thuộc vnstock cập nhật lúc nào).

---

### Phase 8E — Company Info: Nguồn bổ sung *(ưu tiên thấp)*

**Mục tiêu:** Shareholders, officers, events từ nguồn thứ 2.

**Đặc điểm:** Dữ liệu thay đổi chậm, ít quan trọng cho real-time use cases.

**Nguồn tiềm năng:**
- Dữ liệu công bố thông tin từ HOSE/HNX website (crawl HTML — kém ổn định)
- SSI iBoard company profile
- VNDirect company API (nếu có)

**Hành động:** Khảo sát và đánh giá sau khi Phase 8B, 8C hoàn thành.

---

## 4. Thứ tự implement

```
Hiện tại:
  [DONE] Phase 7A — KBS price (vnstock) + VNDirect fallback
  [DONE] Phase 7B — Cross-validation BCTC

Kế tiếp:
  Phase 8A — Xác nhận VNDirect price hoạt động trên VPS + khảo sát SSI
     ↓
  Phase 8B — VNDirect Finance direct REST (shadow 4 tuần → fallback)
     ↓
  Phase 8C — VNDirect Listing direct REST
     ↓
  Phase 8D — Self-calculate Ratio Summary từ DB
     ↓
  Phase 8E — Company Info bổ sung (tùy chọn)
```

---

## 5. Kiến trúc mục tiêu (sau Phase 8D)

```
Listing:          VNDirect REST (primary) → vnstock VCI (fallback)
Finance:          VNDirect REST (primary) → vnstock VCI (fallback)
Company:          vnstock VCI (primary)   → [TBD] (fallback)
Ratio Summary:    Tính từ DB (primary)    → vnstock VCI (fallback)
Price History:    KBS/vnstock (primary)   → VNDirect REST → SSI REST
Cross-Validation: Dùng dữ liệu đã có trong DB (không cần fetch thêm)
```

Sau Phase 8D, ngay cả khi vnstock ngừng hoàn toàn trong 1 tuần:
- **Listing**: Tự chạy từ VNDirect
- **Finance**: Tự chạy từ VNDirect
- **Price**: Tự chạy từ VNDirect
- **Ratio**: Tự tính từ DB

---

## 6. Nguyên tắc validation khi thêm nguồn mới

### Threshold chấp nhận được

| Loại dữ liệu | Threshold |
|---|---|
| Giá (price_history) | diff < 0.01% (rounding) |
| BCTC tổng hợp (total_assets, net_revenue...) | diff < 0.1% |
| BCTC chi tiết (từng dòng mục) | diff < 2% |
| Ratio tính toán | diff < 1% |
| Danh mục mã | match 100% (mã có trong cả hai) |

### Quy trình shadow run

```python
# Trong job, khi có nguồn mới chạy song song:
df_primary  = vnstock_extractor.extract(symbol)      # Nguồn cũ
df_new      = new_extractor.extract(symbol)           # Nguồn mới (shadow)

# Chỉ log diff, không ghi vào DB từ nguồn mới
diff_flags = compare(df_primary, df_new, threshold=0.02)
if diff_flags:
    save_to_data_quality_flags(diff_flags, resolved=False, notes="shadow_run")
```

Sau khi shadow run đủ 4 tuần và `data_quality_flags` không có flag bất thường → promote.

---

## 7. Rủi ro và giảm thiểu

| Rủi ro | Giảm thiểu |
|---|---|
| Nguồn mới trả về đơn vị khác (nghìn VND vs tỷ VND) | Shadow run + kiểm tra thủ công trước promote |
| Nguồn mới không có đủ lịch sử | Giữ vnstock làm fallback cho backfill |
| API nguồn mới đổi schema | Unit test snapshot + alert khi transform lỗi |
| VNDirect/SSI siết API | Đa dạng nguồn, không phụ thuộc 1 nguồn duy nhất |

---

## 8. Trạng thái tracking

| Phase | Trạng thái | Bắt đầu | Hoàn thành |
|---|---|---|---|
| 7A — Price KBS + VNDirect | ✅ Done | 2026-03-21 | 2026-03-21 |
| 7B — BCTC Cross-validation | ✅ Done | 2026-03-21 | 2026-03-21 |
| 8A — Price: xác nhận VPS + SSI | 🔲 Chưa bắt đầu | — | — |
| 8B — Finance: VNDirect direct | 🔲 Chưa bắt đầu | — | — |
| 8C — Listing: VNDirect direct | 🔲 Chưa bắt đầu | — | — |
| 8D — Ratio: tự tính từ DB | 🔲 Chưa bắt đầu | — | — |
| 8E — Company: nguồn bổ sung | 🔲 Chưa bắt đầu | — | — |
