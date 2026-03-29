# Nghiên cứu: Dữ liệu Báo cáo Tài chính — vnstock3 → PostgreSQL

> **Người viết:** Claude Code (AI Research Assistant)
> **Ngày:** 2026-03-28
> **Đọc bởi:** Nhóm 6 thành viên — Đồ án tốt nghiệp
> **Dựa trên:** Phân tích trực tiếp source code, schema, và mapping files hiện tại

---

## 1. Executive Summary

Pipeline hiện tại (schema `financial_reports` — Approach A: single wide table) là **nền tảng tốt và không cần refactor schema**. Tuy nhiên có **2 vấn đề nghiêm trọng** cần fix trước Sprint 3:

**Vấn đề 1 — Critical:** API `ratio` (53 cột: ROE, ROA, P/E, P/B, gross margin...) chưa được sync vào DB bằng named columns. Screener feature đang lọc trên `ratio_summary` (dữ liệu hàng ngày từ `sync_ratios`) thay vì dữ liệu lịch sử từ BCTC. Điều này có nghĩa: **DuPont, trend analysis, và peer comparison sẽ không có dữ liệu lịch sử để vẽ chart**.

**Vấn đề 2 — Important:** `_apply_mapping()` trong `BaseFinancialParser` trả về `0.0` thay vì `None` cho các cột không tìm thấy trong DataFrame. Điều này làm sai lệch screener: filter `gross_profit > 0` sẽ trả về ngân hàng (banking không có gross_profit nhưng được lưu `0.0` thay vì `NULL`).

**Recommended solution:**
1. Giữ nguyên schema `financial_reports` (Approach A) — không refactor
2. Fix `_apply_mapping()`: trả `None` thay `0.0` khi cột không tồn tại trong DataFrame
3. Thêm bảng `financial_ratios` để lưu 53 cột ratio lịch sử (ROE, ROA, P/E, P/B, margins...)
4. Thêm `ratio` extraction vào `sync_financials` pipeline

Với 3 thay đổi này, tất cả MVP features (FA Analysis, Screener, DuPont, Peer Comparison, Storytelling) sẽ có đủ dữ liệu hoạt động.

---

## 2. Data Analysis

### 2.1 Phân tích 5 API Methods

#### Method 1: `balance_sheet(lang='vi')` — 134 cột

| Loại cột | Số lượng | Ví dụ |
|---|---|---|
| **Meta** | 2 | index (kỳ báo cáo), `report_period` |
| **Duplicate `_` prefix** | ~15 | `__Đầu tư ngắn hạn` (= giá trị của `Đầu tư ngắn hạn`) |
| **Luôn = 0 với non_financial** | ~37 | `Giao dịch mua bán lại trái phiếu Chính phủ`, `Cổ phiếu ưu đãi` |
| **Hữu ích** | ~80 | Các cột được map trong `non_financial.py`, `banking.py`, v.v. |
| **Được map thành named column** | ~25–30 | Xem bảng 2.3 |
| **Chỉ có trong `raw_details`** | ~50–55 | Chi tiết sub-items, breakdown theo loại |

**Vấn đề:** Cột `report_period` luôn = `'year'` kể cả khi fetch quarterly — period phải parse từ DataFrame index (ví dụ `"Q1/2024"`, `"2024"`). Pipeline hiện tại đã xử lý đúng trong `_parse_period()`.

#### Method 2: `income_statement(lang='vi')` — 44 cột

| Loại cột | Số lượng |
|---|---|
| Meta | 2 |
| Duplicate `_` prefix | ~5 |
| Industry-specific (zero cho ngành khác) | ~12 |
| Core cross-industry | ~15 |
| Được map thành named column | ~17 |

**Lưu ý:** Non-financial có COGS, gross profit, selling/admin expenses. Banking chỉ có interest income/expense, fee income, operating expenses. Cấu trúc hoàn toàn khác nhau → 2 set named columns riêng biệt trong schema.

#### Method 3: `cash_flow(lang='vi')` — 81 cột

| Loại cột | Số lượng |
|---|---|
| Meta | 2 |
| Duplicate `_` prefix | ~8 |
| Industry-specific | ~20 |
| Core (CFO/CFI/CFF subtotals) | ~17 |
| Được map thành named column | ~17 |

**Lưu ý Banking:** LCTT ngân hàng VN không tách rõ CFF (financing activities). `BankingParser` đặt `cff` vào `NULL_FIELDS` là đúng.

#### Method 4: `ratio(lang='vi')` — 53 cột ⚠️ CHƯA SYNC

| Nhóm | Cột | Tầm quan trọng |
|---|---|---|
| Profitability | ROE, ROA, Net Margin, Gross Margin, EBITDA Margin | **Critical cho screener** |
| Valuation | P/E, P/B, EV/EBITDA, Dividend Yield | **Critical cho screener** |
| Efficiency | Asset Turnover, Inventory Days, Receivable Days | Important |
| Leverage | D/E Ratio, Interest Coverage, Debt/Assets | Important |
| Liquidity | Current Ratio, Quick Ratio | Important |
| Per share | EPS, BVPS, CFPS, Revenue per share | Important |
| Growth | Revenue Growth YoY, Profit Growth YoY | DuPont/Storytelling |

**Đây là gap nghiêm trọng nhất.** `sync_ratios` chỉ lấy snapshot `ratio_summary` (1 row/mã/ngày từ Company API), không phải historical ratio từ Finance API. Để vẽ chart "ROE qua các năm" hay filter "ROE > 15% liên tục 5 năm", cần ratio historical data.

#### Method 5: `note(lang='vi')` — 144 cột ❌ KHÔNG CẦN CHO MVP

Note API trả về chi tiết breakdown của các dòng BCTC (ví dụ: breakdown nợ vay theo kỳ hạn, breakdown hàng tồn kho theo loại). Các MVP features không cần data này. **Bỏ qua cho Sprint 3, có thể thêm sau.**

---

### 2.2 So sánh cấu trúc BCTC theo 4 Industry Templates

#### Balance Sheet — Asset Side

| Khoản mục | Non-Financial | Banking | Securities | Insurance |
|---|---|---|---|---|
| Tiền & tương đương tiền | ✅ cash_and_equivalents | ✅ + deposits_at_state_bank | ✅ | ✅ |
| Đầu tư ngắn hạn | ✅ short_term_investments | ✅ trading_securities + investment_securities | ✅ fvtpl_assets + available_for_sale_assets | ✅ financial_investments |
| Phải thu KH | ✅ short_term_receivables | ❌ N/A | ✅ settlement_receivables | ✅ insurance_premium_receivables |
| **Hàng tồn kho** | ✅ inventory_net | ❌ NULL | ❌ NULL | ❌ NULL |
| **Cho vay KH** | ❌ NULL | ✅ customer_loans_gross | ✅ margin_lending | ❌ N/A |
| **TSCĐ** | ✅ ppe_net | ✅ ppe_net (nhỏ) | ✅ ppe_net | ✅ ppe_net |
| Total Current Assets | ✅ | ❌ (NK không tách rõ) | ✅ | ✅ |
| Total Assets | ✅ | ✅ | ✅ | ✅ |

#### Balance Sheet — Liability + Equity Side

| Khoản mục | Non-Financial | Banking | Securities | Insurance |
|---|---|---|---|---|
| Phải trả nhà cung cấp | ✅ accounts_payable | ❌ N/A | ❌ N/A | ❌ N/A |
| **Tiền gửi KH** | ❌ NULL | ✅ customer_deposits | ❌ N/A | ❌ N/A |
| **Phát hành giấy tờ có giá** | ❌ NULL | ✅ bonds_issued | ❌ N/A | ❌ N/A |
| **Dự phòng nghiệp vụ BH** | ❌ NULL | ❌ NULL | ❌ NULL | ✅ insurance_technical_reserves |
| Vay ngắn hạn | ✅ short_term_debt | ❌ (= interbank_borrowings) | ✅ | ✅ |
| Vay dài hạn | ✅ long_term_debt | ❌ | ✅ | ✅ |
| Total Equity | ✅ total_equity | ✅ | ✅ | ✅ |

#### Income Statement

| Khoản mục | Non-Financial | Banking | Securities | Insurance |
|---|---|---|---|---|
| **Doanh thu gộp → Net revenue** | ✅ gross_revenue → net_revenue | ❌ | ✅ brokerage_revenue | ✅ net_insurance_premium |
| **GVHB** | ✅ cost_of_goods_sold (abs) | ❌ NULL | ❌ NULL | ❌ NULL |
| **Lợi nhuận gộp** | ✅ gross_profit | ❌ NULL | ❌ NULL | ❌ NULL |
| **Thu nhập lãi thuần** | ❌ N/A | ✅ net_interest_income | ❌ N/A | ❌ N/A |
| **Dự phòng tín dụng** | ❌ N/A | ✅ credit_provision_expense | ❌ N/A | ❌ N/A |
| Chi phí QLDN | ✅ admin_expenses | ✅ operating_expenses | ✅ operating_expenses | ✅ admin_expenses |
| EBT | ✅ ebt | ✅ ebt | ❌ NULL (xem ghi chú) | ✅ ebt |
| Net Profit | ✅ | ✅ | ✅ | ✅ |
| EPS | ✅ | ✅ | ✅ | ✅ |

> **Ghi chú Securities EBT:** `SecuritiesParser.NULL_FIELDS` đặt `ebt = NULL` — cần kiểm tra lại với dữ liệu SSI thực tế. CTCK có thể có dòng LN trước thuế nhưng tên cột khác.

#### Cash Flow

| Khoản mục | Non-Financial | Banking | Securities | Insurance |
|---|---|---|---|---|
| CFO subtotal | ✅ cfo | ✅ cfo (chỉ subtotal) | ✅ cfo | ✅ cfo |
| CFI subtotal | ✅ cfi | ✅ cfi | ✅ cfi | ✅ cfi |
| CFF subtotal | ✅ cff | ❌ NULL | ✅ cff | ✅ cff |
| CAPEX | ✅ capex (abs) | ❌ không map | ✅ capex | ✅ capex |
| Dividends paid | ✅ dividends_paid (abs) | ✅ | ✅ | ✅ |

> **Banking CAPEX gap:** `BankingParser.CASH_FLOW_MAP` hiện không map `capex`. Ngân hàng có chi mua TSCĐ nhưng rất nhỏ so với total assets. Nên thêm.

---

### 2.3 Data Quality Issues Phát hiện

| Issue | Mô tả | Hiện trạng xử lý |
|---|---|---|
| **`_` prefix duplicates** | `__Đầu tư ngắn hạn` = giá trị trùng của `Đầu tư ngắn hạn` | Bỏ qua trong mapping — chỉ map tên không có `_` |
| **`report_period` column** | Luôn = `'year'` kể cả quarterly | Parse từ DataFrame index trong `_parse_period()` ✅ |
| **Unix timestamp ms** | `company.news.public_date` chia 1000 | ✅ đã fix (khác module) |
| **1753-01-01 sentinel** | `.NET DateTime.MinValue` trong date columns | ✅ đã fix (company transformer) |
| **NaN / Inf** | Chuỗi JSON không hợp lệ | ✅ xử lý trong `_build_raw_details()` |
| **Vietnamese unstable names** | VCI có thể đổi tên cột | ⚠️ Fallback về `0.0` — xem bug dưới |
| **0.0 vs NULL ambiguity** | Cột không tìm thấy → `0.0` thay vì `None` | ❌ **BUG — xem Section 6** |
| **Negative values** | Chi phí trả về âm từ API | ✅ `_ABS_FIELDS` + `abs()` |
| **Duplicate VN column mapping** | `insurance.py`: `financial_investments` map 2 lần | ⚠️ Chỉ first match được dùng (reverse dict) |

---

## 3. Schema Approach Comparison

### 3.1 Mô tả 4 Approaches

**Approach A — Single Wide Table (current):**
```sql
financial_reports (id, symbol, period, period_type, statement_type, template,
  [~100 named columns], raw_details JSONB)
```

**Approach B — EAV:**
```sql
financial_statements (id, symbol, period, item_code, value NUMERIC)
financial_items (item_code PK, name_vi, name_en, unit, category)
```

**Approach C — Separate tables per statement type:**
```sql
fin_balance_sheet (symbol, period, total_assets, inventory_net, customer_loans_gross, ...)
fin_income_statement (symbol, period, net_revenue, cost_of_goods_sold, net_interest_income, ...)
fin_cash_flow (symbol, period, cfo, cfi, cff, capex, ...)
```

**Approach D — Hybrid: Named core + JSONB industry-specific:**
```sql
financial_reports (symbol, period, statement_type,
  [~50 cross-industry cols],
  industry_data JSONB  -- banking/securities/insurance specifics
)
```

---

### 3.2 Ma trận đánh giá (1=Tệ, 5=Tốt)

#### Pattern 1: Time series 1 symbol (FA chart)
```sql
SELECT period, total_assets, total_equity, net_profit
FROM financial_reports
WHERE symbol='HPG' AND statement_type='balance_sheet' AND period_type='year'
ORDER BY period;
```

| Approach | Score | Lý do |
|---|---|---|
| **A (current)** | **5** | Single scan, perfect index `(symbol, statement_type, period_type, period DESC)` |
| B (EAV) | 2 | Phải PIVOT/crosstab — slow, complex, ~20× more rows |
| C (separate tables) | 5 | Direct table scan, giống A |
| D (hybrid) | 4 | Named cols cho core OK, industry cols cần JSON extract |

#### Pattern 2: Screener across many symbols (Screener feature)
```sql
SELECT symbol, roe, pe_ratio, gross_margin
FROM financial_ratios  -- bảng ratio riêng
WHERE period='2024' AND roe > 0.15 AND pe_ratio < 15
ORDER BY roe DESC LIMIT 50;
```

| Approach | Score | Lý do |
|---|---|---|
| **A (current)** | **4** | OK nếu có bảng ratio riêng; self-join IS+BS cho on-the-fly chậm hơn |
| B (EAV) | 1 | Cực kỳ chậm — phải pivot 1550×50 values |
| C (separate tables) | 5 | Có thể tạo materialized view join BS+IS cho screener |
| D (hybrid) | 4 | Tương tự A |

#### Pattern 3: Cross-statement calculation (DuPont: IS + BS)
```sql
SELECT bs.symbol, bs.period,
  is_.net_profit / NULLIF(is_.net_revenue, 0) AS net_margin,
  is_.net_revenue / NULLIF(bs.total_assets, 0) AS asset_turnover,
  bs.total_assets / NULLIF(bs.total_equity, 0) AS leverage
FROM financial_reports bs
JOIN financial_reports is_ ON bs.symbol=is_.symbol AND bs.period=is_.period
  AND bs.period_type=is_.period_type
WHERE bs.statement_type='balance_sheet' AND is_.statement_type='income_statement'
  AND bs.symbol='HPG';
```

| Approach | Score | Lý do |
|---|---|---|
| **A (current)** | **4** | Self-join trên cùng bảng, index tốt, OK cho 1 symbol |
| B (EAV) | 1 | Triple PIVOT nightmare |
| C (separate tables) | 5 | Simple JOIN giữa 2 bảng |
| D (hybrid) | 4 | Tương tự A |

#### Pattern 4: Peer comparison (same industry, same period)
```sql
SELECT symbol, net_profit, total_equity,
  net_profit/NULLIF(total_equity,0) AS roe
FROM financial_reports bs
JOIN financial_reports is_ USING (symbol, period, period_type)
WHERE bs.template='banking' AND bs.period='2024' AND bs.period_type='year'
  AND bs.statement_type='balance_sheet' AND is_.statement_type='income_statement'
ORDER BY roe DESC;
```

| Approach | Score | Lý do |
|---|---|---|
| **A (current)** | **4** | Index `(period, period_type, template)` đã có. Self-join 30 banks = fast |
| B (EAV) | 1 | N+1 pivot problem |
| C (separate tables) | 5 | JOIN BS+IS đơn giản, + có thể filter template trong view |
| D (hybrid) | 4 | Tương tự A |

#### Pattern 5: Storytelling / Trend detection (LAG, window functions)
```sql
SELECT symbol, period,
  net_profit,
  LAG(net_profit) OVER (PARTITION BY symbol ORDER BY period) AS prev_profit,
  net_profit - LAG(net_profit) OVER (PARTITION BY symbol ORDER BY period) AS delta
FROM financial_reports
WHERE statement_type='income_statement' AND period_type='year'
  AND symbol='HPG';
```

| Approach | Score | Lý do |
|---|---|---|
| **A (current)** | **5** | Window functions trực tiếp, no join needed |
| B (EAV) | 2 | Phải CTE + pivot trước window function |
| C (separate tables) | 5 | Tương tự A trên bảng chuyên biệt |
| D (hybrid) | 5 | Tương tự A |

#### Tổng điểm

| Approach | P1 | P2 | P3 | P4 | P5 | **Total** | Nhận xét |
|---|---|---|---|---|---|---|---|
| **A (current)** | 5 | 4 | 4 | 4 | 5 | **22/25** | Tốt tổng thể, cần bảng ratio riêng |
| B (EAV) | 2 | 1 | 1 | 1 | 2 | **7/25** | Không phù hợp BCTC |
| C (3 tables) | 5 | 5 | 5 | 5 | 5 | **25/25** | Tốt nhất kỹ thuật, nhưng refactor lớn |
| D (hybrid) | 4 | 4 | 4 | 4 | 5 | **21/25** | Tương đương A, phức tạp hơn không đáng |

#### Kết luận lựa chọn

Approach C lý tưởng về kỹ thuật nhưng **cần refactor toàn bộ schema + transformer** — không phù hợp với deadline June 2026. Approach A đạt 22/25 điểm và **đã có code hoạt động**. Với 2 fix nhỏ (ratio table + 0.0→NULL), Approach A đủ cho tất cả MVP features.

**Quyết định: Giữ Approach A, thêm bảng `financial_ratios`.**

---

## 4. Recommended Solution

### 4.1 Gap Analysis — Trước và Sau

| Feature MVP | Trạng thái hiện tại | Sau fix |
|---|---|---|
| FA Analysis — BS/IS/CF chart | ✅ Dữ liệu có, query OK | ✅ |
| FA Analysis — Ratio chart (ROE, P/E theo năm) | ❌ Không có historical ratio | ✅ Sau khi thêm `financial_ratios` |
| Screener — filter by ratio | ⚠️ Chỉ có snapshot từ `ratio_summary` | ✅ Sau khi thêm `financial_ratios` |
| DuPont analysis | ⚠️ Self-join IS+BS hoạt động nhưng ROE từ IS/BS thủ công | ✅ Dùng ratio data có sẵn |
| Peer comparison | ⚠️ 0.0 thay vì NULL gây sai lệch | ✅ Sau khi fix NULL |
| Storytelling trend | ⚠️ LAG trên IS/BS OK, ratio không có | ✅ |

### 4.2 Schema DDL cho `financial_ratios` (bảng mới)

```sql
-- Migration 008_financial_ratios.sql

CREATE TABLE IF NOT EXISTS financial_ratios (

    -- ── Định danh ────────────────────────────────────────────────────────────
    id              BIGSERIAL       PRIMARY KEY,
    symbol          VARCHAR(10)     NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)     NOT NULL,   -- "2024", "2024Q1"
    period_type     period_type_enum NOT NULL,  -- 'year' | 'quarter'
    source          VARCHAR(20)     NOT NULL DEFAULT 'vci',

    -- ── Profitability ─────────────────────────────────────────────────────────
    roe             NUMERIC(8, 4),   -- Return on Equity (0.15 = 15%)
    roa             NUMERIC(8, 4),   -- Return on Assets
    net_margin      NUMERIC(8, 4),   -- Net Profit Margin
    gross_margin    NUMERIC(8, 4),   -- Gross Profit Margin (N/A for banking)
    ebitda_margin   NUMERIC(8, 4),
    operating_margin NUMERIC(8, 4),

    -- ── Valuation ─────────────────────────────────────────────────────────────
    pe_ratio        NUMERIC(10, 2),  -- Price/Earnings
    pb_ratio        NUMERIC(8, 4),   -- Price/Book
    ps_ratio        NUMERIC(10, 2),  -- Price/Sales
    ev_ebitda       NUMERIC(10, 2),
    dividend_yield  NUMERIC(8, 4),

    -- ── Per Share ─────────────────────────────────────────────────────────────
    eps             NUMERIC(15, 2),  -- Earnings Per Share (VND)
    bvps            NUMERIC(15, 2),  -- Book Value Per Share
    revenue_per_share NUMERIC(15, 2),
    cfps            NUMERIC(15, 2),  -- Cash Flow Per Share

    -- ── Efficiency ────────────────────────────────────────────────────────────
    asset_turnover       NUMERIC(8, 4),
    inventory_days       NUMERIC(8, 2),   -- NULL for banking/insurance
    receivable_days      NUMERIC(8, 2),
    payable_days         NUMERIC(8, 2),   -- NULL for banking

    -- ── Leverage ──────────────────────────────────────────────────────────────
    debt_to_equity       NUMERIC(10, 4),
    debt_to_assets       NUMERIC(8, 4),
    interest_coverage    NUMERIC(10, 2),
    equity_multiplier    NUMERIC(8, 4),   -- DuPont: Total Assets / Equity

    -- ── Liquidity ─────────────────────────────────────────────────────────────
    current_ratio        NUMERIC(8, 4),
    quick_ratio          NUMERIC(8, 4),

    -- ── Growth (YoY) ──────────────────────────────────────────────────────────
    revenue_growth       NUMERIC(8, 4),   -- YoY %
    profit_growth        NUMERIC(8, 4),   -- YoY %

    -- ── Banking-specific ──────────────────────────────────────────────────────
    nim                  NUMERIC(8, 4),   -- Net Interest Margin (NULL for non-banking)
    npl_ratio            NUMERIC(8, 4),   -- Non-Performing Loan ratio
    loan_to_deposit      NUMERIC(8, 4),   -- LDR

    -- ── Raw + audit ───────────────────────────────────────────────────────────
    raw_details          JSONB   NOT NULL DEFAULT '{}',
    fetched_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_financial_ratios UNIQUE (symbol, period, period_type, source)
);

CREATE INDEX IF NOT EXISTS idx_ratio_symbol_period
    ON financial_ratios (symbol, period_type, period DESC);

CREATE INDEX IF NOT EXISTS idx_ratio_screener
    ON financial_ratios (period, period_type, roe, pe_ratio, pb_ratio)
    WHERE period_type = 'year';

COMMENT ON TABLE financial_ratios IS
    'Pre-computed financial ratios from VCI Finance API (53 cols). '
    'Used for screener, DuPont, trend analysis. '
    'Source: Finance(symbol, period, source=vci).ratio(lang=vi)';
```

### 4.3 Column Mapping — VCI Vietnamese → DB Column

#### Balance Sheet Core (all templates)

| VCI Vietnamese Name | DB Column | Type | Templates |
|---|---|---|---|
| `TỔNG CỘNG TÀI SẢN` / `TỔNG TÀI SẢN` | `total_assets` | NUMERIC(20,2) | All |
| `Tiền và tương đương tiền` | `cash_and_equivalents` | NUMERIC(20,2) | All |
| `NỢ PHẢI TRẢ` / `TỔNG NỢ PHẢI TRẢ` | `total_liabilities` | NUMERIC(20,2) | All |
| `Vốn chủ sở hữu` / `VỐN CHỦ SỞ HỮU` | `total_equity` | NUMERIC(20,2) | All |
| `Vốn góp` / `Vốn điều lệ` / `Vốn đầu tư của chủ sở hữu` | `charter_capital` | NUMERIC(20,2) | All |
| `Thặng dư vốn cổ phần` | `share_premium` | NUMERIC(20,2) | All |
| `Lãi chưa phân phối` / `Lợi nhuận chưa phân phối` | `retained_earnings` | NUMERIC(20,2) | All |
| `Lợi ích cổ đông không kiểm soát` | `minority_interest_bs` | NUMERIC(20,2) | All |
| `Tổng cộng nguồn vốn` | `total_liabilities_and_equity` | NUMERIC(20,2) | All |
| `Vay ngắn hạn` | `short_term_debt` | NUMERIC(20,2) | Non-fin, Sec, Ins |
| `Vay dài hạn` | `long_term_debt` | NUMERIC(20,2) | Non-fin, Sec, Ins |
| `Lợi thế thương mại` | `goodwill` | NUMERIC(20,2) | Non-fin |

#### Balance Sheet — Non-Financial Specific

| VCI Vietnamese Name | DB Column | Notes |
|---|---|---|
| `Hàng tồn kho, ròng` | `inventory_net` | NULL for banking/insurance/securities |
| `Hàng tồn kho` | `inventory_gross` | |
| `Dự phòng giảm giá hàng tồn kho` | `inventory_allowance` | |
| `Phải thu khách hàng` | `short_term_receivables` | |
| `GTCL TSCĐ hữu hình` | `ppe_net` | |
| `Nguyên giá TSCĐ hữu hình` | `ppe_gross` | |
| `Khấu hao lũy kế TSCĐ hữu hình` | `accumulated_depreciation` | |
| `Xây dựng cơ bản đang dở dang` | `construction_in_progress` | |

#### Balance Sheet — Banking Specific

| VCI Vietnamese Name | DB Column | Notes |
|---|---|---|
| `Tiền gửi tại Ngân hàng nhà nước` | `deposits_at_state_bank` | NULL non-banking |
| `Tiền gửi tại các TCTD khác...` | `interbank_deposits` | NULL non-banking |
| `Chứng khoán kinh doanh` | `trading_securities` | NULL non-banking |
| `Chứng khoán đầu tư` | `investment_securities` | NULL non-banking |
| `Cho vay khách hàng` | `customer_loans_gross` | NULL non-banking |
| `Dự phòng rủi ro cho vay KH` | `loan_loss_reserve` | abs() — NULL non-banking |
| `Tiền gửi của khách hàng` | `customer_deposits` | NULL non-banking |
| `Tiền gửi và vay các TCTD khác` | `interbank_borrowings` | NULL non-banking |
| `Phát hành giấy tờ có giá` | `bonds_issued` | NULL non-banking |

#### Income Statement Core (all templates)

| VCI Vietnamese Name | DB Column | abs() | Templates |
|---|---|---|---|
| `Doanh thu thuần` / `Doanh thu thuần về HĐKD` | `net_revenue` | No | All |
| `Lãi/(lỗ) từ HĐKD` / `KẾT QUẢ HOẠT ĐỘNG` | `operating_profit` | No | All |
| `Lãi/(lỗ) trước thuế` / `Tổng LNLTT` | `ebt` | No | Non-fin, Banking, Ins |
| `Lãi/(lỗ) thuần sau thuế` / `LN KT SAU THUẾ` | `net_profit` | No | All |
| `LN của Cổ đông của Công ty mẹ` | `net_profit_parent` | No | All |
| `Lợi ích của cổ đông thiểu số` | `minority_interest_is` | No | All |
| `Lãi cơ bản trên cổ phiếu (VND)` | `eps_basic` | No | All |
| `Lãi trên cổ phiếu pha loãng (VND)` | `eps_diluted` | No | All |

#### Cash Flow Core (all templates)

| VCI Vietnamese Name | DB Column | abs() |
|---|---|---|
| `Lưu chuyển tiền...từ HĐSXKD` | `cfo` | No |
| `Lưu chuyển tiền...từ HĐĐT` | `cfi` | No |
| `Lưu chuyển tiền...từ HĐTC` | `cff` | No (NULL banking) |
| `Tiền chi để mua sắm TSCĐ...` | `capex` | **Yes** |
| `Cổ tức, lợi nhuận đã trả...` | `dividends_paid` | **Yes** |
| `Lưu chuyển tiền thuần trong kỳ` | `net_cash_change` | No |
| `Tiền...đầu kỳ` | `cash_beginning` | No |
| `Tiền...cuối kỳ` | `cash_ending` | No |

#### JSONB `raw_details` — Những gì KHÔNG được map thành named column

| Loại dữ liệu | Ví dụ | Lý do để trong JSONB |
|---|---|---|
| Sub-items của tổng | Breakdown nợ vay theo từng ngân hàng | Không cần cho MVP queries |
| `_` prefix duplicate cols | `__Đầu tư ngắn hạn` | Redundant với parent col |
| Industry-specific low-priority | `Giao dịch mua bán lại trái phiếu CP` | Không có trong screener/FA analysis |
| Cột luôn = 0 cho ngành hiện tại | 37 banking cols khi đọc HPG | Audit trail only |
| Cột chưa map nhưng có giá trị | Tên cột VCI mới chưa nhận dạng | Graceful degradation |

---

## 5. Transformer Design

### 5.1 Kiến trúc hiện tại — Đánh giá

```
FinanceParserFactory.get_parser(icb_code, statement_type)
    → _resolve_parser(icb_code) → BankingParser / InsuranceParser / ...
    → parser.parse(df_raw, symbol)
        → for period_label, row in df.iterrows():
              _parse_period(period_label) → (period, period_type)
              _apply_mapping(row, FIELD_MAPS[stmt_type], NULL_FIELDS[stmt_type])
              _build_raw_details(row)
              return payload dict
```

**Điểm mạnh:** Clean factory pattern, NULL_FIELDS explicit, raw_details đầy đủ.

**Điểm yếu cần fix:**

```python
# HIỆN TẠI — Sai:
else:
    result[canonical] = 0.0  # ← "cột không tìm thấy trong DataFrame" bị lưu 0.0

# NÊN SỬA THÀNH:
else:
    result[canonical] = None  # ← cột không có trong báo cáo của kỳ này
```

**Tại sao quan trọng:** Khi screener filter `WHERE gross_profit > 0`, banks (gross_profit = 0.0) sẽ được trả về sai. Với `None`, query `WHERE gross_profit IS NOT NULL AND gross_profit > 0` sẽ loại bỏ đúng.

### 5.2 Pseudocode cho RatioParser (bảng mới)

```python
# etl/transformers/finance_ratios.py (FILE MỚI — KHÔNG SỬA FILE CŨ)

RATIO_MAP: dict[str, str] = {
    # Tên cột VCI tiếng Việt → tên cột DB
    "Vốn chủ sở hữu trên cổ phiếu (BVPS)": "bvps",
    "Lợi nhuận trên vốn chủ (ROE)":         "roe",
    "Lợi nhuận trên tài sản (ROA)":          "roa",
    "Lợi nhuận biên":                        "net_margin",
    "Lợi nhuận gộp biên":                    "gross_margin",
    "Giá trị sổ sách trên mỗi CP":           "bvps",
    "P/E":                                   "pe_ratio",
    "P/B":                                   "pb_ratio",
    "EPS (VND)":                             "eps",
    "Hệ số thanh toán hiện hành":            "current_ratio",
    "Hệ số thanh toán nhanh":               "quick_ratio",
    "Vòng quay tổng tài sản":               "asset_turnover",
    "Số ngày tồn kho":                       "inventory_days",
    "Số ngày phải thu":                      "receivable_days",
    "Nợ/Vốn chủ sở hữu":                    "debt_to_equity",
    "EV/EBITDA":                             "ev_ebitda",
    "Cổ tức/Giá (Dividend Yield)":          "dividend_yield",
    # ... (verify thêm từ df_ratio.columns.tolist() với dữ liệu thực)
}

class RatioParser:
    def parse(self, df: pd.DataFrame, symbol: str) -> list[dict]:
        payloads = []
        for period_label, row in df.iterrows():
            period, period_type = _parse_period(str(period_label))
            core = {}
            for vi_name, canonical in RATIO_MAP.items():
                if vi_name in row.index:
                    val = _to_numeric(row[vi_name])
                    core[canonical] = val  # None nếu NaN
                # Không set 0.0 — để None nếu không có
            payload = {
                "symbol": symbol,
                "period": period,
                "period_type": period_type,
                "source": "vci",
                **core,
                "raw_details": _build_raw_details(row),
            }
            payloads.append(payload)
        return payloads
```

### 5.3 Cập nhật `sync_financials.py` để thêm ratio

```python
# Thêm vào FINANCIAL_REPORT_TYPES trong constants.py:
# FINANCIAL_RATIO_TYPES = ["ratio"]  ← type riêng, bảng riêng

# Trong sync_financials._run_one(), thêm branch:
if report_type == "ratio":
    df_raw = extractor.extract_ratio(symbol)
    parser = RatioParser()
    payloads = parser.parse(df_raw, symbol)
    df = pd.DataFrame(payloads)
    rows = loader.load(df, "financial_ratios", CONFLICT_KEYS["financial_ratios"])
    return {"symbol": symbol, "report_type": "ratio", "status": "success", "rows": rows}
```

### 5.4 Xử lý VCI đổi tên cột (unstable naming)

**Vấn đề:** Nếu VCI đổi `"Lợi nhuận gộp"` thành `"Lợi nhuận gộp về bán hàng"`, cột `gross_profit` sẽ không map được và trả về `None` (sau fix) thay vì `0.0`.

**Giải pháp hiện tại:** `raw_details` JSONB chứa toàn bộ row gốc — có thể audit sau.

**Giải pháp nâng cao (optional, sau MVP):**

```python
# Thêm fallback aliases vào mapping:
INCOME_STATEMENT_MAP: dict[str, str] = {
    "Lợi nhuận gộp":                     "gross_profit",  # primary
    "Lợi nhuận gộp về bán hàng":         "gross_profit",  # alias VCI v2
    "Lợi nhuận gộp về BH và CCDV":       "gross_profit",  # alias VCI v3
    ...
}
# _apply_mapping() đã hỗ trợ multiple VI names → same canonical
# (reverse dict chỉ giữ first match, các aliases là fallback)
```

**Monitoring đề xuất:** Thêm log warning khi > 20% named columns = None cho 1 symbol:

```python
none_count = sum(1 for v in core.values() if v is None)
if none_count / len(core) > 0.2:
    logger.warning(f"{symbol}: {none_count}/{len(core)} cols unmapped — VCI column drift?")
```

---

## 6. Data Quality Rules

### 6.1 Complete list of transformations

| # | Rule | Input | Output | Áp dụng ở đâu |
|---|---|---|---|---|
| 1 | **NaN/Inf → None** | `float('nan')`, `float('inf')` | `None` | `_to_numeric()` ✅ |
| 2 | **Expense sign flip** | Âm từ API (e.g., GVHB = -1500) | Dương (1500) | `abs()` nếu trong `_ABS_FIELDS` ✅ |
| 3 | **Missing col → None** | Cột không có trong DataFrame | `None` | ❌ **CẦN FIX** (hiện = 0.0) |
| 4 | **Null field enforcement** | Cột không áp dụng cho template | `None` | `NULL_FIELDS` ✅ |
| 5 | **Period parsing** | `"Q1/2024"`, `"2024"`, `"2024-Q1"` | `("2024Q1","quarter")`, `("2024","year")` | `_parse_period()` ✅ |
| 6 | **`_` prefix cols** | `__Đầu tư ngắn hạn` | Bỏ qua | Không có trong mapping ✅ |
| 7 | **JSONB NaN serialization** | NaN trong raw dict | `None` | `_build_raw_details()` ✅ |
| 8 | **Ratio as decimal** | ROE = 15.5 (%) từ VCI | 0.155 (decimal) hoặc 15.5 | ⚠️ **Cần kiểm tra format VCI trả về** |
| 9 | **Unix ms timestamp** | `public_date = 1711400000000` | datetime | Company module ✅ |
| 10 | **.NET sentinel date** | `1753-01-01` | `None` | Company module ✅ |
| 11 | **Duplicate map key** | `financial_investments` map 2 lần (insurance.py) | First match wins | ⚠️ Xem ghi chú dưới |

### 6.2 Validation Rules (đề xuất thêm)

```python
# Sau khi _apply_mapping(), thêm soft validation:

def _validate_balance_sheet(payload: dict, symbol: str) -> None:
    """Kiểm tra accounting equation. Log warning, không raise."""
    assets = payload.get("total_assets")
    liab = payload.get("total_liabilities")
    equity = payload.get("total_equity")

    if all(v is not None and v != 0 for v in [assets, liab, equity]):
        diff = abs(assets - (liab + equity))
        if diff > 1.0:  # tolerance 1 VND (rounding)
            logger.warning(
                f"[validate] {symbol}/{payload['period']}: "
                f"Assets({assets:,.0f}) ≠ Liab({liab:,.0f}) + Equity({equity:,.0f}), "
                f"diff={diff:,.0f}"
            )

def _validate_cash_flow(payload: dict, symbol: str) -> None:
    """CFO + CFI + CFF ≈ net_cash_change."""
    cfo = payload.get("cfo") or 0
    cfi = payload.get("cfi") or 0
    cff = payload.get("cff") or 0
    net = payload.get("net_cash_change")
    if net is not None:
        diff = abs((cfo + cfi + cff) - net)
        if diff > 100:  # tolerance 100 VND (rounding)
            logger.warning(
                f"[validate] {symbol}: CF check: {cfo+cfi+cff:,.0f} ≠ net_cash {net:,.0f}"
            )
```

### 6.3 Ghi chú về Rule 8 — Ratio format

**Cần xác nhận thực tế:** VCI trả về ROE = `0.155` hay `15.5`?

```python
# Kiểm tra nhanh:
from vnstock_data import Finance
df = Finance(symbol='HPG', period='year', source='vci').ratio(lang='vi')
print(df[['Lợi nhuận trên vốn chủ (ROE)']].head())
# Nếu kết quả ~ 0.15 → decimal format (lưu trực tiếp)
# Nếu kết quả ~ 15.0 → percent format (cần chia 100 khi lưu)
```

Quyết định lưu trữ: **lưu dạng decimal** (0.155) trong DB — Spring Boot sẽ nhân 100 khi hiển thị `%`.

### 6.4 Insurance duplicate mapping issue

Trong `insurance.py`:
```python
"Các khoản đầu tư tài chính ngắn hạn"  : "financial_investments",
"Các khoản đầu tư tài chính dài hạn"   : "financial_investments",  # ← duplicate canonical
```

Vì `_apply_mapping()` build `reverse` dict (canonical → vi_name), chỉ first mapping được giữ. Nếu công ty bảo hiểm có cả short-term và long-term investments, chỉ 1 dòng được đọc. **Cần thêm cột `long_term_financial_investments` riêng hoặc tính tổng trong transformer** — nhưng đây là edge case, có thể để raw_details.

---

## 7. Migration Strategy

### 7.1 Từ schema hiện tại sang Recommended Solution

**Schema hiện tại đã đúng — không cần migration DDL.** Chỉ cần:

**Bước 1: Tạo bảng `financial_ratios` (migration mới)**
```bash
# Tạo file db/migrations/008_financial_ratios.sql (DDL ở Section 4.2)
python -m db.migrate  # migrate.py mới có tracking — chỉ chạy file 008
```

**Bước 2: Fix 0.0 → None trong transformer**
```python
# Sửa etl/transformers/finance_parsers.py, method _apply_mapping():
# Dòng: result[canonical] = 0.0
# Thành: result[canonical] = None
```
> **Lưu ý:** Sau fix này, các rows hiện có trong DB có `gross_profit = 0.0` cho banking/securities/insurance sẽ KHÔNG tự cập nhật. Cần re-sync để clean data:
```bash
docker compose exec pipeline python main.py sync_financials --report-types balance_sheet income_statement
```

**Bước 3: Thêm ratio extraction và transformer**
```
Tạo mới:
  - etl/transformers/finance_ratios.py  (RatioParser class)
  - db/migrations/008_financial_ratios.sql

Sửa:
  - config/constants.py: thêm CONFLICT_KEYS["financial_ratios"]
  - jobs/sync_financials.py: thêm ratio branch trong _run_one()
  - etl/extractors/finance.py: thêm extract_ratio() (đã có ✅)
```

**Bước 4: Initial load ratio data**
```bash
docker compose exec pipeline python main.py sync_financials --report-types ratio
# ~2-3 giờ cho 1,550 symbols × 1 loại × 5 threads
```

### 7.2 Impact trên Spring Boot

- Schema `financial_reports` không thay đổi → **không cần sửa JPA entities**
- Bảng `financial_ratios` mới → thêm entity `FinancialRatio` + repository
- Screener queries thay đổi: từ `ratio_summary` sang `financial_ratios`

### 7.3 Không cần downtime

Tất cả thay đổi là additive:
- Bảng mới (không ảnh hưởng bảng cũ)
- Fix 0.0 → None: re-sync có thể chạy nền, on-conflict-update

---

## 8. Risk & Limitations

### 8.1 Rủi ro kỹ thuật

| Rủi ro | Mức độ | Mitigation |
|---|---|---|
| **VCI đổi tên cột** | Cao | `raw_details` + log warning khi >20% cols unmapped |
| **VCI không có ratio cho 1 số mã nhỏ** | Trung bình | `status="skipped"` trong pipeline_logs |
| **Ratio format decimal vs percent** | Cao | Cần verify bằng dữ liệu thực trước khi deploy |
| **Quarterly data period parsing edge cases** | Thấp | `_parse_period()` đã handle 3 formats |
| **Banking capex = 0** | Thấp | Không map capex cho banking → None (sau fix) |
| **SecuritiesParser EBT = NULL** | Trung bình | Cần verify với SSI thực tế |

### 8.2 Những gì solution này KHÔNG xử lý

1. **`note` API (144 cols):** Chi tiết breakdown không được lưu vào named columns. Chỉ có thể truy xuất từ `raw_details` nếu đã fetch balance_sheet/IS/CF. Note API riêng biệt, không được sync.

2. **Real-time financial updates:** BCTC VN chỉ update theo quý. Pipeline sync ngày 1 & 15 là đủ. Không có realtime financial data.

3. **Data từ nguồn khác (KBS, CAFEF):** Chỉ VCI source. Cross-validation KBS đã có trong `FinanceCrossValidator` nhưng chỉ flag bất thường, không replace VCI data.

4. **Restated financials:** Khi công ty điều chỉnh số liệu BCTC cũ (restatement), VCI có thể trả về số mới. Pipeline upsert sẽ ghi đè đúng nhờ `ON CONFLICT DO UPDATE`, nhưng không có audit trail trên named columns (chỉ có trong `raw_details`).

5. **Consolidated vs Parent-only:** VCI trả về báo cáo hợp nhất (consolidated). Một số phân tích cần báo cáo riêng (parent-only), không có cách lấy từ VCI.

6. **Forward-looking data:** Analyst estimates, guidance — nằm ngoài scope pipeline.

7. **International comparisons:** Schema lưu đơn vị VND. Không có conversion sang USD/EUR.

### 8.3 Deadline risk cho Sprint 3 (April 7-20)

| Task | Effort | Risk |
|---|---|---|
| Fix 0.0 → None | 30 phút | Thấp |
| Tạo `financial_ratios` schema | 2 giờ | Thấp |
| Viết `RatioParser` | 4 giờ + verify với dữ liệu thực | **Trung bình** (ratio column names chưa xác nhận) |
| Thêm ratio vào `sync_financials` | 2 giờ | Thấp |
| Re-sync BCTC (clean 0.0 data) | ~3 giờ chạy nền | Thấp |
| Initial load ratio | ~3 giờ chạy nền | Thấp |
| Spring Boot entity + screener query | 1 ngày | Thấp |

**Tổng ước tính:** ~2 ngày code + ~6 giờ data sync background. Feasible cho Sprint 3.

**Critical path:** Verify ratio column names trước. Chạy `Finance('HPG','year','vci').ratio(lang='vi').columns.tolist()` ngay khi có môi trường để confirm mapping trước khi code.

---

*Tài liệu nghiên cứu này dựa trên phân tích source code tại commit `f0bb542`. Cập nhật nếu schema hoặc mapping files thay đổi.*
