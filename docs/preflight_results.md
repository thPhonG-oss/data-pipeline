# Pre-flight Results — VCI API Column Inventory

> **Ngày chạy:** 2026-03-28
> **Script:** `scripts/preflight_api_check.py`
> **Output raw:** `docs/preflight_api_output.json`
> **Mục đích:** Xác nhận tên cột thực tế trả về từ VCI trước khi implement Approach C.

---

## 1. API Shape Summary

| Template | Statement | Cols | Rows (sample) |
|---|---|---|---|
| non_financial (HPG) | balance_sheet | 134 | 10 năm |
| non_financial (HPG) | income_statement | 44 | 10 năm |
| non_financial (HPG) | cash_flow | 81 | 10 năm |
| non_financial (HPG) | **ratio** | **54** | 39 kỳ |
| banking (VCB) | balance_sheet | ~60 | 10 năm |
| banking (VCB) | income_statement | ~30 | 10 năm |
| banking (VCB) | cash_flow | ~20 | 10 năm |
| banking (VCB) | **ratio** | **54** | 39 kỳ |
| securities (SSI) | balance_sheet | 212 | 10 năm |
| securities (SSI) | income_statement | ~40 | 10 năm |
| securities (SSI) | cash_flow | 237 | 10 năm |
| insurance (BVH) | balance_sheet | 189 | 10 năm |
| insurance (BVH) | income_statement | 104 | 10 năm |

> **Ghi chú:** SSI và BVH có nhiều cột hơn HPG vì CTCK và bảo hiểm có nhiều dòng mục kế toán đặc thù hơn.

---

## 2. Ratio API — Cột đã xác nhận

Tất cả 4 templates dùng chung 1 ratio API (54 cột):

```
Kỳ báo cáo, Năm, Quý, Mã TTM, Loại tỷ lệ     ← metadata, không lưu
Số CP lưu hành (triệu), Vốn hóa               ← market data
Tỷ suất cổ tức (%)
P/E, P/B, P/S, Giá/ Dòng tiền, EV/EBITDA     ← valuation
Hệ số thanh toán tiền, Hệ số thanh toán nhanh, Hệ số thanh toán hiện hành  ← liquidity
Vốn chủ sở hữu    ← DUPLICATE (xuất hiện 2 lần ở index 16 và 50) — bỏ lần 2
Nợ/Vốn chủ, Nợ trên vốn chủ                  ← leverage (2 trường tương tự)
ROE (%), ROA (%)                               ← profitability (decimal: 0.2763 = 27.63%)
Số ngày phải thu, Số ngày tồn kho, Số ngày phải trả  ← activity
Biên LN gộp (%), Biên EBIT (%), Biên LN trước thuế (%), Biên LN sau thuế (%)
Vòng quay tài sản
EBIT, EBITDA, ROIC
Chu kỳ tiền, Vòng quay TS cố định, Đòn bẩy tài chính
── Banking-only (= 0.0 cho non-financial): ──
Biên lãi thuần (NIM), Lãi suất bình quân tài sản sinh lãi, Chi phí vốn bình quân
Thu nhập ngoài lãi, Tỷ lệ CIR, CIR, CAR
Tăng trưởng cho vay (%), Tăng trưởng tiền gửi (%)
Vốn chủ/Tổng nợ, Vốn chủ/Cho vay, Vốn chủ/Tổng tài sản
LDR (%), Nợ xấu (%), DP rủi ro/Nợ xấu, DP rủi ro/Cho vay
Tỷ lệ CASA
Mã năm tỷ lệ    ← skip
```

---

## 3. Bug Verification Results

### Bug #1: `_apply_mapping()` trả về `0.0` thay vì `None`

**File:** `etl/transformers/finance_parsers.py:145-147`

```python
# Hiện tại (SAI):
result[canonical] = val if val is not None else 0.0   # ← khi val=None → 0.0
# ...
result[canonical] = 0.0  # ← khi cột không có trong row → 0.0

# Sau fix (ĐÚNG):
result[canonical] = val   # None = "không có dữ liệu" (khác với 0 thực)
# ...
result[canonical] = None  # cột không có trong row → NULL trong DB
```

**Tác động:** Screener `WHERE gross_profit > 0` sẽ trả về banking rows có `gross_profit = 0.0`
(vì BankingParser.NULL_FIELDS set `gross_profit=None` nhưng `_apply_mapping()` ghi đè bằng `0.0`
khi cột mapping tìm không thấy trong row).

**Kết luận:** CONFIRMED BUG — sẽ fix trong Task 2.

### Bug #2: Ratio API chưa bao giờ được sync

**Xác nhận:** `jobs/sync_financials.py` chỉ sync `balance_sheet`, `income_statement`, `cash_flow`.
Không có code nào gọi `Finance(...).ratio()` để lưu vào DB.

**Tác động:** ROE, ROA, P/E, P/B, margins không có dữ liệu lịch sử trong DB.
Backend phải gọi VCI API realtime thay vì query DB — không scalable.

**Kết luận:** CONFIRMED MISSING — sẽ implement trong Task 3.

---

## 4. ROE Format Confirmation

```
HPG ROE (%) = 0.2763486737   # decimal, không phải 27.63%
```

**Quyết định lưu:** `NUMERIC(8,4)` — lưu nguyên dạng decimal (0.2763).
**Quy ước hiển thị:** nhân × 100 ở frontend/backend khi hiển thị.

---

## 5. VCB CAPEX Gap

**Phát hiện:** `BankingParser.CASH_FLOW_MAP` hiện **không có** `'Mua sắm TSCĐ'`.

Cột thực tế trong VCB cash_flow:
```
"Mua sắm TSCĐ"    → capex   (Âm → abs())
```

**Kết luận:** Cần thêm mapping này vào `banking.py`. Sẽ xử lý trong Task 3 khi tạo approach_c parsers.

---

## 6. SSI EBT Verification

**Xác nhận:** SSI income_statement không có dòng EBT trực tiếp.
Có: `CHI PHÍ THUẾ THU NHẬP DOANH NGHIỆP` (tax expense).

`SecuritiesParser.NULL_FIELDS["income_statement"] = {"ebt"}` → **ĐÚNG**.
EBT sẽ là NULL trong DB cho CTCK, không phải 0.0.

---

## 7. Duplicate Ratio Column

**Phát hiện:** `"Vốn chủ sở hữu"` xuất hiện **2 lần** ở column index 16 và 50.

**Xử lý:** `RatioParser.parse()` sẽ gọi `df.loc[:, ~df.columns.duplicated(keep='first')]`
trước khi iterate để loại bỏ cột trùng.

---

## 8. Current Mapping Inventory

| Statement | Non-Fin cols mapped | Banking | Securities | Insurance |
|---|---|---|---|---|
| balance_sheet | 26 | 15 | 14 | 12 |
| income_statement | 17 | 15 | 10 | 11 |
| cash_flow | 15 | 7 | 9 | 9 |
| **ratio** | **0** | **0** | **0** | **0** |

**Gaps:**
- Ratio: 0 mappings → cần tạo `RatioParser` với ~40 canonical fields
- Banking CF: thiếu `capex` (`"Mua sắm TSCĐ"`)
- Ratio `"Nợ trên vốn chủ"` và `"Nợ/Vốn chủ"`: 2 cột tương tự — map cả 2 vào `debt_to_equity`

---

## 9. Go/No-Go Decision

| Check | Status |
|---|---|
| API calls hoạt động | GO |
| Cột thực tế có sẵn để map | GO |
| ROE format xác nhận | GO |
| Bug #1 xác nhận và có fix | GO |
| Bug #2 xác nhận và có plan | GO |
| Schema approach C (4 tables) | GO |

**VERDICT: GO — tiến hành implement Tasks 1–8.**
