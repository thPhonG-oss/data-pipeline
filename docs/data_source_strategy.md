# Chiến lược mở rộng nguồn dữ liệu — Data Pipeline

> **Trạng thái:** Đề xuất chiến lược — chưa implement
> **Mục tiêu:** Tăng độ chính xác, độ sạch, và tính độc lập của dữ liệu thu thập

---

## Mục lục

1. [Phân tích hiện trạng](#1-phân-tích-hiện-trạng)
2. [Kiến trúc vnstock — Có thể mở rộng không?](#2-kiến-trúc-vnstock--có-thể-mở-rộng-không)
3. [Ba hướng tiếp cận](#3-ba-hướng-tiếp-cận)
4. [Nguồn dữ liệu độc lập khả dụng](#4-nguồn-dữ-liệu-độc-lập-khả-dụng)
5. [Kỹ thuật nâng cao chất lượng dữ liệu](#5-kỹ-thuật-nâng-cao-chất-lượng-dữ-liệu)
6. [Khuyến nghị & Lộ trình](#6-khuyến-nghị--lộ-trình)
7. [Rủi ro & Hạn chế cần lưu ý](#7-rủi-ro--hạn-chế-cần-lưu-ý)

---

## 1. Phân tích hiện trạng

### 1.1 Pipeline hiện tại phụ thuộc vào gì?

Toàn bộ dữ liệu đang đến từ **một nguồn duy nhất**: `vnstock_data` (sponsor package của vnstock), thông qua 3 class chính:

| Class (vnstock_data) | Dùng trong | Nguồn API thực tế |
|---|---|---|
| `Finance(source="vci")` | `FinanceExtractor` | VCI (VietCap) — GraphQL/REST |
| `Company(source="vci")` | `CompanyExtractor`, `TradingExtractor` | VCI (VietCap) |
| `Listing(source="vnd")` | `ListingExtractor` | VND (VNDirect) |

### 1.2 Vấn đề dữ liệu đã phát hiện

Trong quá trình phát triển Phase 1–6, đã gặp các vấn đề chất lượng dữ liệu sau:

| Vấn đề | Biểu hiện | Cách xử lý hiện tại |
|---|---|---|
| **Dữ liệu thiếu** | ~22 mã không có `ratio_summary` (skipped) | Bỏ qua (skip) |
| **Overflow số** | P/E âm vô cực, EPS ≈ 0 → NUMERIC overflow | `_to_float_bounded()` → None |
| **Cột trùng lặp** | Công ty bảo hiểm có duplicate columns | `drop_duplicates()` |
| **Sentinel ngày** | `1753-01-01` (SQL Server artifact) | Map → None |
| **Dữ liệu rỗng** | API trả về DataFrame rỗng hoặc None | Skip + log |
| **Tên cột thay đổi** | API đổi tên cột theo version | Map thủ công |
| **Không có giá giá cổ phiếu** | Pipeline chưa thu thập OHLCV | Chưa xử lý |
| **Không cross-validate** | Dữ liệu từ 1 nguồn, không kiểm chứng | Chưa xử lý |

### 1.3 Điểm yếu cốt lõi: Single Source of Truth

```
vnstock_data (VCI)
        │
        ▼
   [Pipeline]  ←── Không có gì để so sánh nếu VCI sai
        │
        ▼
   PostgreSQL
        │
        ▼
   Web App (phân tích cơ bản)
```

Nếu VCI báo cáo sai một chỉ số (đã xảy ra trong thực tế với một số BCTC), pipeline lưu dữ liệu sai mà không biết.

---

## 2. Kiến trúc vnstock — Có thể mở rộng không?

### 2.1 Kiến trúc thực tế của vnstock

Sau khi phân tích source code trong venv, vnstock dùng **Provider Registry Pattern**:

```
BaseAdapter (vnstock/base.py)
        │
        ├── ProviderRegistry.get("quote", "vci")   → VCIQuote
        ├── ProviderRegistry.get("finance", "kbs") → KBSFinance
        └── ProviderRegistry.get("quote", "fmp")   → FMPQuote
```

Các nguồn hiện có trong vnstock:

| Nguồn | Loại | Dữ liệu |
|---|---|---|
| `vci` | Web scraping (GraphQL) | Quote, Finance, Company, Listing, Trading |
| `kbs` | Web scraping (REST) | Quote, Finance, Company, Listing, Trading |
| `msn` | Web scraping | Quote, Listing |
| `fmp` | API (cần key) | Quote, Finance |
| `fmarket` | API | Fund data |
| `binance` | API | Crypto |
| `dnse` | API | Vietnamese market |

### 2.2 Khả năng mở rộng: CÓ, nhưng có giới hạn

**Về mặt kỹ thuật:** vnstock cho phép đăng ký provider mới:

```python
from vnstock.core.registry import ProviderRegistry

@ProviderRegistry.register("finance", "mysource")
class MySourceFinance:
    def balance_sheet(self, symbol, ...):
        # logic tự viết
        return pd.DataFrame(...)

# Sau đó dùng như bình thường:
from vnstock import Finance
Finance(source="mysource", symbol="HPG").balance_sheet()
```

**Hạn chế thực tế:**

| Hạn chế | Chi tiết |
|---|---|
| **Phụ thuộc version** | Nếu vnstock update cấu trúc `ProviderRegistry`, code bị vỡ |
| **Tight coupling** | Provider phải conform interface của vnstock — không linh hoạt |
| **Không kiểm soát được** | Khi vnstock thay đổi `BaseAdapter`, tất cả provider tự viết bị ảnh hưởng |
| **Khó test** | Provider phải test trong context của vnstock |
| **Documentation ít** | API nội bộ của vnstock không có docs chính thức |

**Kết luận:** Mở rộng vào vnstock là **có thể về mặt kỹ thuật** nhưng **không khuyến nghị cho production** vì rủi ro fragility cao.

---

## 3. Ba hướng tiếp cận

### Hướng A — Mở rộng trực tiếp vào vnstock (Plugin Provider)

```
vnstock ProviderRegistry
    ├── "vci"     → VCIFinance  (vnstock built-in)
    ├── "kbs"     → KBSFinance  (vnstock built-in)
    └── "tcbs"    → TCBSFinance ← (TỰ VIẾT — đăng ký vào registry)
```

**Phù hợp khi:** Muốn dùng ngay `Finance(source="tcbs", symbol="HPG")` mà không cần sửa pipeline.

**Không phù hợp vì:** Phụ thuộc vnstock internals — dễ vỡ, khó maintain.

---

### Hướng B — Extractor độc lập (Independent Collector) ✓ Khuyến nghị

```
etl/extractors/
    ├── listing.py     ← vnstock_data.Listing  (giữ nguyên)
    ├── finance.py     ← vnstock_data.Finance  (giữ nguyên)
    ├── company.py     ← vnstock_data.Company  (giữ nguyên)
    ├── trading.py     ← vnstock_data.Company  (giữ nguyên)
    │
    ├── tcbs.py        ← TỰ VIẾT — HTTP trực tiếp đến TCBS API
    ├── ssi.py         ← TỰ VIẾT — HTTP trực tiếp đến SSI iBoard
    └── cafef.py       ← TỰ VIẾT — Web scraping CafeF
```

Mỗi extractor mới kế thừa `BaseExtractor` của pipeline — cùng interface, không đụng vnstock.

**Ưu điểm:**
- Hoàn toàn kiểm soát được logic
- Không phụ thuộc vào vnstock internals
- Dễ test, dễ maintain
- Có thể evolve độc lập

---

### Hướng C — Hybrid + Cross-Validation Layer ✓ Khuyến nghị dài hạn

```
                ┌─── VCI (qua vnstock) ───────────┐
                │                                  │
Symbol ─────────┼─── TCBS (extractor độc lập) ────┼──► CrossValidator ──► PostgreSQL
                │                                  │        │
                └─── SSI  (extractor độc lập) ─────┘        │
                                                       (So sánh, flag
                                                        dị thường, chọn
                                                        giá trị tin cậy)
```

Fetching từ nhiều nguồn → so sánh → giữ giá trị đồng thuận hoặc flag để review.

---

## 4. Nguồn dữ liệu độc lập khả dụng

### 4.1 Các nguồn chính cho thị trường Việt Nam

| Nguồn | Loại | Dữ liệu | Khả năng truy cập | Ưu tiên |
|---|---|---|---|---|
| **TCBS** (Techcom Securities) | Public REST API | OHLCV, BCTC, Company, Events | Không cần key, stable | ⭐⭐⭐⭐⭐ |
| **SSI iBoard** | Public REST API | OHLCV, Orderbook, Market data | Không cần key | ⭐⭐⭐⭐ |
| **HOSE/HNX/UPCOM** | Official website | Công bố thông tin, báo cáo PDF | Scraping | ⭐⭐⭐ |
| **CafeF** | Web scraping | BCTC, tin tức, phân tích | Scraping | ⭐⭐⭐ |
| **VietStock** | Web scraping | BCTC, thông tin doanh nghiệp | Scraping (có CAPTCHA) | ⭐⭐ |
| **FiinGroup** | Premium API | BCTC chuẩn IFRS, lịch sử dài | Cần subscription | ⭐⭐ |
| **VCI (trực tiếp)** | REST/GraphQL | Giống vnstock/vci nhưng trực tiếp | Reverse engineer | ⭐⭐⭐ |

### 4.2 TCBS — Nguồn ưu tiên cao nhất

TCBS có public API không cần authentication, trả về dữ liệu JSON sạch:

```
# Ví dụ endpoints TCBS (không cần auth)
GET https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/financialratio
    ?ticker=HPG&yearly=1&page=0&size=5

GET https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/balancesheet
    ?ticker=HPG&yearly=1&page=0&size=5

GET https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/incomestatement
    ?ticker=HPG&yearly=1&page=0&size=5

GET https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/cashflow
    ?ticker=HPG&yearly=1&page=0&size=5

GET https://apipubaws.tcbs.com.vn/tcanalysis/v1/company/businessInfo
    ?ticker=HPG
```

**Tại sao TCBS quan trọng:**
- Dữ liệu BCTC từ TCBS thường **khớp với công bố chính thức của HoSE/HNX** hơn VCI
- Trả về số tuyệt đối (đơn vị: triệu đồng) — ít lỗi overflow hơn
- Ổn định, không cần API key
- Đã được cộng đồng vnstock sử dụng rộng rãi (vnstock cũ dùng TCBS)

### 4.3 SSI iBoard

```
# Ví dụ endpoints SSI
GET https://iboard-query.ssi.com.vn/v2/stock/company-trade/HPG
GET https://iboard-query.ssi.com.vn/v2/stock/price-board
```

SSI mạnh về **dữ liệu giá realtime và orderbook** — lấp đầy khoảng trống pipeline hiện tại (chưa có OHLCV).

---

## 5. Kỹ thuật nâng cao chất lượng dữ liệu

### 5.1 Cross-Source Validation (So sánh chéo)

Ý tưởng: Lấy cùng dữ liệu từ 2 nguồn, so sánh, flag dị thường.

```python
# Ví dụ trong CrossValidator
class FinanceCrossValidator:
    def validate(self, symbol: str) -> ValidationResult:
        df_vci  = FinanceExtractor(source="vci").extract(symbol, "balance_sheet")
        df_tcbs = TCBSFinanceExtractor().extract(symbol, "balance_sheet")

        # So sánh cột key
        discrepancies = []
        for col in ["total_assets", "equity", "revenue"]:
            if not self._within_tolerance(df_vci[col], df_tcbs[col], pct=0.02):
                discrepancies.append({
                    "column": col,
                    "vci": df_vci[col].iloc[0],
                    "tcbs": df_tcbs[col].iloc[0],
                    "diff_pct": ...
                })

        return ValidationResult(symbol, discrepancies)
```

**Kết quả:** Ghi vào bảng `data_quality_flags` trong DB → web app hiển thị cảnh báo khi dữ liệu không nhất quán.

### 5.2 Source Priority (Ưu tiên nguồn đáng tin)

Thay vì chọn 1 nguồn cứng, dùng chain of trust:

```python
# Thứ tự ưu tiên cho BCTC
FINANCE_SOURCE_PRIORITY = ["tcbs", "vci", "kbs"]

def extract_with_fallback(symbol, report_type):
    for source in FINANCE_SOURCE_PRIORITY:
        try:
            df = extractor(source).extract(symbol, report_type)
            if df is not None and not df.empty:
                df["_source"] = source   # track nguồn
                return df
        except Exception:
            continue
    return None
```

### 5.3 Bổ sung dữ liệu giá (OHLCV)

Pipeline hiện tại **hoàn toàn thiếu dữ liệu giá**. Đây là khoảng trống lớn nhất:

```
Bảng mới cần thêm: price_history
┌────────────────────────────────────────────────────────┐
│ symbol | date | open | high | low | close | volume    │
│ HPG    | 2024-03-20 | 27.5 | 28.1 | 27.2 | 27.8 | ... │
└────────────────────────────────────────────────────────┘
```

Nguồn: TCBS API hoặc SSI — cả hai đều có endpoint lịch sử giá không cần auth.

### 5.4 Data Lineage (Truy vết nguồn gốc)

Thêm cột `_source` và `_fetched_at` vào các bảng chính:

```sql
-- Thêm vào balance_sheets, income_statements, v.v.
ALTER TABLE balance_sheets ADD COLUMN data_source VARCHAR(20) DEFAULT 'vci';
```

Giúp audit khi phát hiện dữ liệu sai — biết ngay dữ liệu đến từ đâu và khi nào.

### 5.5 Anomaly Detection đơn giản

Phát hiện dữ liệu bất thường trước khi upsert:

```python
def detect_anomalies(df_new, df_existing, symbol, table):
    """Flag nếu giá trị thay đổi > 50% so với kỳ trước — có thể là lỗi API."""
    for col in CRITICAL_COLS[table]:
        pct_change = abs(df_new[col] - df_existing[col]) / abs(df_existing[col])
        if pct_change > 0.5:
            logger.warning(f"[anomaly] {symbol}.{col}: thay đổi {pct_change:.0%} — kiểm tra lại")
```

---

## 6. Khuyến nghị & Lộ trình

### Tóm tắt khuyến nghị

| Hướng | Quyết định | Lý do |
|---|---|---|
| Mở rộng vào vnstock internals | ❌ Không | Fragile, phụ thuộc version |
| Build extractor độc lập | ✅ Có | Kiểm soát hoàn toàn, dễ maintain |
| Cross-source validation | ✅ Có (ưu tiên cao) | Đây là vấn đề thực tế nhất |
| Thu thập dữ liệu giá (OHLCV) | ✅ Có | Khoảng trống lớn nhất của pipeline |
| Source priority / fallback | ✅ Có | Tăng resilience khi 1 nguồn lỗi |

---

### Lộ trình đề xuất (3 giai đoạn)

#### Giai đoạn 7A — TCBS Extractor + Giá lịch sử (~1–2 tuần)

Ưu tiên cao nhất vì lấp đầy khoảng trống lớn nhất:

```
Việc cần làm:
1. Viết etl/extractors/tcbs.py
   ├── TCBSFinanceExtractor     → balance_sheet, income_statement, cash_flow
   └── TCBSPriceExtractor       → lịch sử giá OHLCV (daily)

2. Viết etl/transformers/tcbs.py
   ├── TCBSFinanceTransformer
   └── TCBSPriceTransformer

3. Thêm migration db/migrations/005_price_history.sql
   CREATE TABLE price_history (symbol, date, open, high, low, close, volume, ...)

4. Viết jobs/sync_prices.py
   → Chạy hàng ngày sau 18:30 (cùng lúc sync_ratios)

5. Thêm CRON_SYNC_PRICES vào settings + scheduler
```

**Kết quả:** Pipeline có dữ liệu giá để tính P/E, P/B real-time, vẽ chart.

---

#### Giai đoạn 7B — Cross-Validation Layer (~1 tuần)

```
Việc cần làm:
1. Viết etl/validators/cross_source.py
   ├── FinanceCrossValidator    → so sánh VCI vs TCBS
   └── ValidationResult         → dataclass kết quả

2. Thêm migration 006_data_quality.sql
   CREATE TABLE data_quality_flags (
       symbol, table_name, column_name,
       source_a, value_a, source_b, value_b,
       diff_pct, flagged_at
   )

3. Tích hợp vào sync_financials — sau mỗi lần sync, chạy validator
4. Thêm alert khi có flag mới
```

**Kết quả:** Biết ngay khi VCI và TCBS báo cáo khác nhau > 2% → có thể điều tra.

---

#### Giai đoạn 7C — Fallback & Resilience (~3–5 ngày)

```
Việc cần làm:
1. Refactor FinanceExtractor dùng source priority chain
   FINANCE_SOURCE_PRIORITY = ["vci", "tcbs", "kbs"]
   → Nếu vci fail 3 lần → tự động thử tcbs

2. Thêm cột data_source vào balance_sheets, income_statements, v.v.
3. Log nguồn nào được dùng vào pipeline_logs
```

**Kết quả:** Pipeline không bị dừng hoàn toàn khi VCI downtime.

---

### Thứ tự ưu tiên rõ ràng

```
[Ưu tiên 1] Giai đoạn 7A — TCBS + Price History
    Lý do: Dữ liệu giá là thiếu sót lớn nhất, TCBS dễ tích hợp

[Ưu tiên 2] Giai đoạn 7B — Cross-Validation
    Lý do: Tăng tin cậy dữ liệu BCTC — trực tiếp ảnh hưởng chất lượng web app

[Ưu tiên 3] Giai đoạn 7C — Fallback
    Lý do: Tăng resilience — pipeline không downtime khi VCI lỗi
```

---

## 7. Rủi ro & Hạn chế cần lưu ý

| Rủi ro | Mức độ | Biện pháp |
|---|---|---|
| **TCBS thay đổi API** (không có SLA) | Cao | Viết test kiểm tra response format mỗi tuần |
| **Xung đột dữ liệu** giữa VCI và TCBS | Trung bình | Dùng cross-validator flag thay vì tự động ghi đè |
| **Rate limiting** khi gọi 2 nguồn/mã | Trung bình | Tăng `REQUEST_DELAY`, stagger requests |
| **Schema khác nhau** giữa nguồn | Cao | Transformer riêng cho từng nguồn (không share) |
| **Legal/ToS** của SSI, CafeF | Thấp–Trung bình | Chỉ dùng cho học thuật, không scale commercial |
| **Tăng thời gian sync** (2 nguồn thay vì 1) | Trung bình | Chạy song song, không tuần tự |

---

*Tài liệu này là kế hoạch chiến lược — không thay đổi code nào. Xác nhận hướng đi trước khi bắt đầu implement Giai đoạn 7.*
