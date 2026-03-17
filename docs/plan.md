# Kế hoạch thiết kế ETL Pipeline — Phân tích cơ bản chứng khoán Việt Nam

## Mục tiêu

Xây dựng pipeline tự động thu thập, làm sạch và lưu trữ dữ liệu từ `vnstock_data` vào PostgreSQL, phục vụ mục đích **phân tích cơ bản (fundamental analysis)** cổ phiếu Việt Nam.

---

## Phần 1 — Thiết kế Schema PostgreSQL

### Sơ đồ quan hệ tổng quát

```
icb_industries (1) ──< companies (1) ──< balance_sheets
                                    ──< income_statements
                                    ──< cash_flows
                                    ──< financial_ratios
                                    ──< ratio_summary
                                    ──< shareholders
                                    ──< officers
                                    ──< subsidiaries
                                    ──< corporate_events
                                    ──< pipeline_logs
```

---

### 1.1 Bảng danh mục (Reference Tables)

#### `icb_industries` — Phân ngành ICB

```sql
CREATE TABLE icb_industries (
    icb_code        VARCHAR(10)  PRIMARY KEY,
    icb_name        VARCHAR(300) NOT NULL,
    en_icb_name     VARCHAR(300),
    level           SMALLINT     NOT NULL CHECK (level BETWEEN 1 AND 4),
    parent_code     VARCHAR(10)  REFERENCES icb_industries(icb_code),
    created_at      TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX idx_icb_level       ON icb_industries(level);
CREATE INDEX idx_icb_parent_code ON icb_industries(parent_code);

COMMENT ON TABLE icb_industries IS
    'Phân loại ngành theo chuẩn ICB (Industry Classification Benchmark), 4 cấp độ.';
COMMENT ON COLUMN icb_industries.level IS
    '1=Lĩnh vực, 2=Siêu ngành, 3=Nhóm ngành, 4=Ngành cụ thể';
```

#### `companies` — Danh mục công ty niêm yết

```sql
CREATE TABLE companies (
    symbol          VARCHAR(10)  PRIMARY KEY,
    company_name    VARCHAR(500) NOT NULL,
    company_name_eng VARCHAR(500),
    short_name      VARCHAR(200),
    exchange        VARCHAR(20)  NOT NULL CHECK (exchange IN ('HOSE','HNX','UPCOM')),
    type            VARCHAR(30)  NOT NULL CHECK (type IN ('STOCK','ETF','BOND','CW','FUND')),
    status          VARCHAR(20)  NOT NULL DEFAULT 'listed' CHECK (status IN ('listed','delisted','suspended')),
    icb_code        VARCHAR(10)  REFERENCES icb_industries(icb_code),
    listed_date     DATE,
    delisted_date   DATE,
    charter_capital BIGINT,
    issue_share     BIGINT,
    company_id      INTEGER,                 -- ID nội bộ từ VCI
    isin            VARCHAR(20),
    tax_code        VARCHAR(20),
    created_at      TIMESTAMP    DEFAULT NOW(),
    updated_at      TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX idx_companies_exchange ON companies(exchange);
CREATE INDEX idx_companies_type     ON companies(type);
CREATE INDEX idx_companies_status   ON companies(status);
CREATE INDEX idx_companies_icb_code ON companies(icb_code);

COMMENT ON TABLE companies IS
    'Danh mục toàn bộ chứng khoán niêm yết, được đồng bộ định kỳ từ vnstock_data.Listing.';
```

---

### 1.2 Bảng báo cáo tài chính (Financial Statements)

> Tất cả bảng tài chính dùng `(symbol, period, period_type)` làm composite unique key.
> `period` ví dụ: `"2024"`, `"2024Q1"`. `period_type`: `'year'` hoặc `'quarter'`.

#### `balance_sheets` — Bảng Cân Đối Kế Toán

```sql
CREATE TABLE balance_sheets (
    id                          SERIAL       PRIMARY KEY,
    symbol                      VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    period                      VARCHAR(10)  NOT NULL,  -- '2024', '2024Q1'
    period_type                 VARCHAR(10)  NOT NULL CHECK (period_type IN ('year','quarter')),

    -- TÀI SẢN NGẮN HẠN
    cash_and_equivalents        BIGINT,   -- Tiền và tương đương tiền
    short_term_investments      BIGINT,   -- Đầu tư tài chính ngắn hạn
    accounts_receivable         BIGINT,   -- Phải thu ngắn hạn
    inventory                   BIGINT,   -- Hàng tồn kho
    other_current_assets        BIGINT,   -- Tài sản ngắn hạn khác
    total_current_assets        BIGINT,   -- TỔNG TÀI SẢN NGẮN HẠN

    -- TÀI SẢN DÀI HẠN
    long_term_receivables       BIGINT,   -- Phải thu dài hạn
    fixed_assets                BIGINT,   -- Tài sản cố định (thuần)
    investment_properties       BIGINT,   -- Bất động sản đầu tư
    long_term_investments       BIGINT,   -- Đầu tư tài chính dài hạn
    intangible_assets           BIGINT,   -- Tài sản vô hình (gồm lợi thế thương mại)
    other_long_term_assets      BIGINT,   -- Tài sản dài hạn khác
    total_long_term_assets      BIGINT,   -- TỔNG TÀI SẢN DÀI HẠN

    total_assets                BIGINT,   -- TỔNG CỘNG TÀI SẢN

    -- NỢ PHẢI TRẢ
    short_term_debt             BIGINT,   -- Vay và nợ ngắn hạn
    accounts_payable            BIGINT,   -- Phải trả người bán ngắn hạn
    advances_from_customers     BIGINT,   -- Người mua trả tiền trước
    other_current_liabilities   BIGINT,   -- Nợ ngắn hạn khác
    total_current_liabilities   BIGINT,   -- TỔNG NỢ NGẮN HẠN

    long_term_debt              BIGINT,   -- Vay và nợ dài hạn
    other_long_term_liabilities BIGINT,   -- Nợ dài hạn khác
    total_long_term_liabilities BIGINT,   -- TỔNG NỢ DÀI HẠN

    total_liabilities           BIGINT,   -- TỔNG NỢ PHẢI TRẢ

    -- VỐN CHỦ SỞ HỮU
    charter_capital_fs          BIGINT,   -- Vốn điều lệ (từ BCTC)
    share_premium               BIGINT,   -- Thặng dư vốn cổ phần
    retained_earnings           BIGINT,   -- Lợi nhuận sau thuế chưa phân phối
    other_equity                BIGINT,   -- Vốn chủ sở hữu khác
    minority_interest           BIGINT,   -- Lợi ích cổ đông không kiểm soát
    total_equity                BIGINT,   -- TỔNG VỐN CHỦ SỞ HỮU

    total_liabilities_equity    BIGINT,   -- TỔNG NGUỒN VỐN (= total_assets)

    -- DỮ LIỆU GỐC ĐẦY ĐỦ
    -- Lưu toàn bộ ~140 cột thô từ API (tên cột tiếng Việt, sub-item, cột đặc thù ngành...)
    -- Dùng để drill-down hoặc khi cần cột chưa được map vào schema
    raw_data                    JSONB,

    source                      VARCHAR(20) DEFAULT 'vci',
    fetched_at                  TIMESTAMP   DEFAULT NOW(),

    UNIQUE (symbol, period, period_type)
);

CREATE INDEX idx_bs_symbol   ON balance_sheets(symbol);
CREATE INDEX idx_bs_period   ON balance_sheets(period, period_type);
CREATE INDEX idx_bs_raw_data ON balance_sheets USING GIN (raw_data);

COMMENT ON TABLE balance_sheets IS
    'Bảng cân đối kế toán theo năm và quý. '
    'Các cột tổng hợp dùng cho screener/so sánh; raw_data lưu toàn bộ ~140 cột gốc để drill-down. '
    'Nguồn: vnstock_data.Finance.balance_sheet().';
```

#### `income_statements` — Báo Cáo Kết Quả Kinh Doanh

```sql
CREATE TABLE income_statements (
    id                      SERIAL       PRIMARY KEY,
    symbol                  VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    period                  VARCHAR(10)  NOT NULL,
    period_type             VARCHAR(10)  NOT NULL CHECK (period_type IN ('year','quarter')),

    -- DOANH THU
    gross_revenue           BIGINT,   -- Doanh thu bán hàng và CCDV
    revenue_deductions      BIGINT,   -- Các khoản giảm trừ doanh thu
    net_revenue             BIGINT,   -- Doanh thu thuần

    -- CHI PHÍ & LỢI NHUẬN
    cogs                    BIGINT,   -- Giá vốn hàng bán
    gross_profit            BIGINT,   -- Lợi nhuận gộp
    financial_income        BIGINT,   -- Doanh thu tài chính
    financial_expense       BIGINT,   -- Chi phí tài chính
    interest_expense        BIGINT,   -- Chi phí lãi vay
    selling_expense         BIGINT,   -- Chi phí bán hàng
    admin_expense           BIGINT,   -- Chi phí quản lý doanh nghiệp
    operating_profit        BIGINT,   -- Lợi nhuận từ HĐKD

    other_income            BIGINT,   -- Thu nhập khác
    other_expense           BIGINT,   -- Chi phí khác
    profit_from_associates  BIGINT,   -- Lãi/lỗ từ công ty liên kết

    ebt                     BIGINT,   -- Lợi nhuận trước thuế
    income_tax              BIGINT,   -- Chi phí thuế TNDN
    profit_after_tax        BIGINT,   -- Lợi nhuận sau thuế
    minority_profit         BIGINT,   -- Lợi ích cổ đông không kiểm soát
    net_profit              BIGINT,   -- Lợi nhuận sau thuế của cổ đông công ty mẹ

    -- CỔ PHIẾU
    eps_basic               NUMERIC(15,2),  -- EPS cơ bản (đồng/cp)
    eps_diluted             NUMERIC(15,2),  -- EPS pha loãng (đồng/cp)
    shares_outstanding      BIGINT,         -- KLCP bình quân lưu hành

    -- DỮ LIỆU GỐC ĐẦY ĐỦ
    raw_data                JSONB,

    source                  VARCHAR(20) DEFAULT 'vci',
    fetched_at              TIMESTAMP   DEFAULT NOW(),

    UNIQUE (symbol, period, period_type)
);

CREATE INDEX idx_is_symbol   ON income_statements(symbol);
CREATE INDEX idx_is_period   ON income_statements(period, period_type);
CREATE INDEX idx_is_raw_data ON income_statements USING GIN (raw_data);

COMMENT ON TABLE income_statements IS
    'Báo cáo kết quả kinh doanh theo năm và quý. '
    'Các cột tổng hợp dùng cho screener/so sánh; raw_data lưu toàn bộ cột gốc để drill-down. '
    'Nguồn: vnstock_data.Finance.income_statement().';
```

#### `cash_flows` — Báo Cáo Lưu Chuyển Tiền Tệ

```sql
CREATE TABLE cash_flows (
    id                              SERIAL       PRIMARY KEY,
    symbol                          VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    period                          VARCHAR(10)  NOT NULL,
    period_type                     VARCHAR(10)  NOT NULL CHECK (period_type IN ('year','quarter')),

    -- HOẠT ĐỘNG KINH DOANH
    net_profit_before_tax           BIGINT,   -- Lợi nhuận trước thuế
    depreciation                    BIGINT,   -- Khấu hao TSCĐ và BĐSĐT
    provision                       BIGINT,   -- Dự phòng
    unrealized_fx_gain_loss         BIGINT,   -- Lãi/lỗ chênh lệch tỷ giá chưa thực hiện
    investment_income               BIGINT,   -- Lãi/lỗ từ đầu tư
    interest_expense_cf             BIGINT,   -- Chi phí lãi vay (điều chỉnh)
    change_in_receivables           BIGINT,   -- Thay đổi khoản phải thu
    change_in_inventory             BIGINT,   -- Thay đổi hàng tồn kho
    change_in_payables              BIGINT,   -- Thay đổi khoản phải trả
    other_operating_changes         BIGINT,   -- Thay đổi tài sản ngắn hạn khác
    income_tax_paid                 BIGINT,   -- Tiền thuế TNDN đã nộp
    operating_cash_flow             BIGINT,   -- LƯU CHUYỂN TIỀN TỪ HĐKD

    -- HOẠT ĐỘNG ĐẦU TƯ
    capex                           BIGINT,   -- Mua sắm TSCĐ, BĐSĐT
    proceeds_from_asset_disposal    BIGINT,   -- Thu từ thanh lý tài sản
    investment_purchases            BIGINT,   -- Chi đầu tư góp vốn
    investment_proceeds             BIGINT,   -- Thu hồi đầu tư góp vốn
    interest_and_dividends_received BIGINT,   -- Lãi và cổ tức nhận được
    investing_cash_flow             BIGINT,   -- LƯU CHUYỂN TIỀN TỪ HĐ ĐẦU TƯ

    -- HOẠT ĐỘNG TÀI CHÍNH
    proceeds_from_borrowings        BIGINT,   -- Tiền vay nhận được
    repayment_of_borrowings         BIGINT,   -- Tiền trả nợ gốc vay
    proceeds_from_equity_issuance   BIGINT,   -- Tiền từ phát hành cổ phiếu
    dividends_paid                  BIGINT,   -- Cổ tức đã trả cho cổ đông
    financing_cash_flow             BIGINT,   -- LƯU CHUYỂN TIỀN TỪ HĐ TÀI CHÍNH

    net_cash_change                 BIGINT,   -- LƯU CHUYỂN TIỀN THUẦN TRONG KỲ
    beginning_cash                  BIGINT,   -- Tiền đầu kỳ
    ending_cash                     BIGINT,   -- TIỀN CUỐI KỲ

    -- DỮ LIỆU GỐC ĐẦY ĐỦ
    raw_data                        JSONB,

    source                          VARCHAR(20) DEFAULT 'vci',
    fetched_at                      TIMESTAMP   DEFAULT NOW(),

    UNIQUE (symbol, period, period_type)
);

CREATE INDEX idx_cf_symbol   ON cash_flows(symbol);
CREATE INDEX idx_cf_period   ON cash_flows(period, period_type);
CREATE INDEX idx_cf_raw_data ON cash_flows USING GIN (raw_data);

COMMENT ON TABLE cash_flows IS
    'Báo cáo lưu chuyển tiền tệ. '
    'Các cột tổng hợp dùng cho screener/so sánh; raw_data lưu toàn bộ cột gốc để drill-down. '
    'Nguồn: vnstock_data.Finance.cash_flow().';
```

#### `financial_ratios` — Chỉ Số Tài Chính

```sql
CREATE TABLE financial_ratios (
    id                      SERIAL       PRIMARY KEY,
    symbol                  VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    period                  VARCHAR(10)  NOT NULL,
    period_type             VARCHAR(10)  NOT NULL CHECK (period_type IN ('year','quarter')),

    -- ĐỊNH GIÁ (Valuation)
    pe                      NUMERIC(12,4),  -- Giá/Thu nhập (P/E)
    pb                      NUMERIC(12,4),  -- Giá/Giá trị sổ sách (P/B)
    ps                      NUMERIC(12,4),  -- Giá/Doanh thu (P/S)
    pcf                     NUMERIC(12,4),  -- Giá/Dòng tiền (P/CF)
    ev_ebitda               NUMERIC(12,4),  -- EV/EBITDA
    ev                      BIGINT,         -- Enterprise Value (VND)

    -- KHẢ NĂNG SINH LỜI (Profitability)
    roe                     NUMERIC(10,4),  -- Tỷ suất lợi nhuận trên VCSH (%)
    roa                     NUMERIC(10,4),  -- Tỷ suất lợi nhuận trên tổng TS (%)
    roic                    NUMERIC(10,4),  -- Tỷ suất lợi nhuận trên vốn đầu tư (%)
    gross_margin            NUMERIC(10,4),  -- Biên lợi nhuận gộp (%)
    ebit_margin             NUMERIC(10,4),  -- Biên EBIT (%)
    net_profit_margin       NUMERIC(10,4),  -- Biên lợi nhuận ròng (%)
    ebitda                  BIGINT,         -- EBITDA (VND)
    ebit                    BIGINT,         -- EBIT (VND)

    -- THANH KHOẢN (Liquidity)
    current_ratio           NUMERIC(10,4),  -- Hệ số thanh toán hiện hành
    quick_ratio             NUMERIC(10,4),  -- Hệ số thanh toán nhanh
    cash_ratio              NUMERIC(10,4),  -- Hệ số thanh toán tiền mặt
    interest_coverage       NUMERIC(10,4),  -- Hệ số khả năng trả lãi

    -- ĐÒN BẨY (Leverage)
    debt_to_equity          NUMERIC(10,4),  -- Nợ/Vốn chủ sở hữu (D/E)
    debt_to_assets          NUMERIC(10,4),  -- Nợ/Tổng tài sản
    financial_leverage      NUMERIC(10,4),  -- Đòn bẩy tài chính (Assets/Equity)

    -- HIỆU QUẢ HOẠT ĐỘNG (Efficiency)
    asset_turnover          NUMERIC(10,4),  -- Vòng quay tổng tài sản
    fixed_asset_turnover    NUMERIC(10,4),  -- Vòng quay tài sản cố định
    inventory_days          NUMERIC(10,2),  -- Số ngày tồn kho (DSI)
    receivable_days         NUMERIC(10,2),  -- Số ngày phải thu (DSO)
    payable_days            NUMERIC(10,2),  -- Số ngày phải trả (DPO)
    cash_conversion_cycle   NUMERIC(10,2),  -- Chu kỳ chuyển đổi tiền mặt (CCC)

    -- CỔ PHIẾU
    eps                     NUMERIC(15,2),  -- Thu nhập trên cổ phiếu (đồng/cp)
    eps_ttm                 NUMERIC(15,2),  -- EPS trailing 12 tháng
    bvps                    NUMERIC(15,2),  -- Giá trị sổ sách trên cổ phiếu
    dividend                NUMERIC(15,2),  -- Cổ tức trên cổ phiếu (đồng/cp)

    -- CHỈ SỐ NGÀNH NGÂN HÀNG (chỉ điền khi áp dụng)
    npl_ratio               NUMERIC(10,4),  -- Tỷ lệ nợ xấu (%)
    car                     NUMERIC(10,4),  -- Hệ số an toàn vốn (CAR)
    ldr                     NUMERIC(10,4),  -- Tỷ lệ cho vay/huy động (LDR)
    nim                     NUMERIC(10,4),  -- Biên lãi thuần (NIM)

    source                  VARCHAR(20) DEFAULT 'vci',
    fetched_at              TIMESTAMP   DEFAULT NOW(),

    UNIQUE (symbol, period, period_type)
);

CREATE INDEX idx_fr_symbol ON financial_ratios(symbol);
CREATE INDEX idx_fr_period ON financial_ratios(period, period_type);
CREATE INDEX idx_fr_roe    ON financial_ratios(roe);
CREATE INDEX idx_fr_pe     ON financial_ratios(pe);

COMMENT ON TABLE financial_ratios IS
    'Chỉ số tài chính tổng hợp theo năm/quý. Nguồn: vnstock_data.Finance.ratio().';
```

---

### 1.3 Bảng thông tin doanh nghiệp (Company Intelligence)

#### `shareholders` — Cổ Đông Lớn

```sql
CREATE TABLE shareholders (
    id                  SERIAL       PRIMARY KEY,
    symbol              VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    share_holder        VARCHAR(500) NOT NULL,
    quantity            BIGINT,
    share_own_percent   NUMERIC(8,4),
    update_date         DATE,
    snapshot_date       DATE         NOT NULL DEFAULT CURRENT_DATE,

    UNIQUE (symbol, share_holder, snapshot_date)
);

CREATE INDEX idx_shareholders_symbol ON shareholders(symbol);
CREATE INDEX idx_shareholders_date   ON shareholders(snapshot_date);

COMMENT ON TABLE shareholders IS
    'Danh sách cổ đông lớn và cơ cấu sở hữu. Nguồn: vnstock_data.Company.shareholders().';
```

#### `officers` — Ban Lãnh Đạo

```sql
CREATE TABLE officers (
    id                  SERIAL       PRIMARY KEY,
    symbol              VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    officer_name        VARCHAR(300) NOT NULL,
    officer_position    VARCHAR(300),
    position_short_name VARCHAR(100),
    officer_own_percent NUMERIC(8,4),
    quantity            BIGINT,
    update_date         DATE,
    status              VARCHAR(20)  DEFAULT 'working' CHECK (status IN ('working','resigned')),
    snapshot_date       DATE         NOT NULL DEFAULT CURRENT_DATE,

    UNIQUE (symbol, officer_name, status, snapshot_date)
);

CREATE INDEX idx_officers_symbol ON officers(symbol);

COMMENT ON TABLE officers IS
    'Ban lãnh đạo và thành viên HĐQT. Nguồn: vnstock_data.Company.officers().';
```

#### `subsidiaries` — Công Ty Con & Liên Kết

```sql
CREATE TABLE subsidiaries (
    id                  SERIAL       PRIMARY KEY,
    symbol              VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    sub_organ_code      VARCHAR(20),
    organ_name          VARCHAR(500) NOT NULL,
    ownership_percent   NUMERIC(8,4),
    type                VARCHAR(50)  CHECK (type IN ('subsidiary','associated')),
    snapshot_date       DATE         NOT NULL DEFAULT CURRENT_DATE,

    UNIQUE (symbol, organ_name, snapshot_date)
);

CREATE INDEX idx_subsidiaries_symbol ON subsidiaries(symbol);

COMMENT ON TABLE subsidiaries IS
    'Công ty con và công ty liên kết. Nguồn: vnstock_data.Company.subsidiaries().';
```

#### `corporate_events` — Sự Kiện Doanh Nghiệp

```sql
CREATE TABLE corporate_events (
    id                  SERIAL       PRIMARY KEY,
    symbol              VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    event_title         VARCHAR(500),
    event_list_code     VARCHAR(20),  -- DIV=cổ tức, ISS=phát hành, AIS=niêm yết thêm, SPL=tách cổ phiếu
    event_list_name     VARCHAR(300),
    public_date         DATE,
    issue_date          DATE,
    record_date         DATE,
    exright_date        DATE,
    ratio               NUMERIC(15,6),
    value               NUMERIC(20,4),
    source_url          TEXT,
    fetched_at          TIMESTAMP    DEFAULT NOW(),

    UNIQUE (symbol, event_list_code, record_date)
);

CREATE INDEX idx_events_symbol      ON corporate_events(symbol);
CREATE INDEX idx_events_record_date ON corporate_events(record_date);
CREATE INDEX idx_events_code        ON corporate_events(event_list_code);

COMMENT ON TABLE corporate_events IS
    'Sự kiện doanh nghiệp: chia cổ tức, phát hành cổ phiếu, tách cổ phiếu, sáp nhập... '
    'Nguồn: vnstock_data.Company.events().';
```

#### `ratio_summary` — Snapshot Tài Chính Mới Nhất

```sql
CREATE TABLE ratio_summary (
    id                    SERIAL       PRIMARY KEY,
    symbol                VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    year_report           SMALLINT     NOT NULL,
    quarter_report        SMALLINT,             -- NULL nếu là dữ liệu năm
    revenue               BIGINT,
    revenue_growth        NUMERIC(10,4),
    net_profit            BIGINT,
    net_profit_growth     NUMERIC(10,4),
    ebit_margin           NUMERIC(10,4),
    roe                   NUMERIC(10,4),
    roa                   NUMERIC(10,4),
    roic                  NUMERIC(10,4),
    pe                    NUMERIC(10,4),
    pb                    NUMERIC(10,4),
    ps                    NUMERIC(10,4),
    pcf                   NUMERIC(10,4),
    eps                   NUMERIC(15,2),
    eps_ttm               NUMERIC(15,2),
    bvps                  NUMERIC(15,2),
    current_ratio         NUMERIC(10,4),
    quick_ratio           NUMERIC(10,4),
    cash_ratio            NUMERIC(10,4),
    interest_coverage     NUMERIC(10,4),
    debt_to_equity        NUMERIC(10,4),
    net_profit_margin     NUMERIC(10,4),
    gross_margin          NUMERIC(10,4),
    ev                    BIGINT,
    ev_ebitda             NUMERIC(10,4),
    ebitda                BIGINT,
    ebit                  BIGINT,
    asset_turnover        NUMERIC(10,4),
    fixed_asset_turnover  NUMERIC(10,4),
    receivable_days       NUMERIC(10,2),
    inventory_days        NUMERIC(10,2),
    payable_days          NUMERIC(10,2),
    cash_conversion_cycle NUMERIC(10,2),
    dividend              NUMERIC(15,2),
    issue_share           BIGINT,
    charter_capital       BIGINT,
    extra_metrics         JSONB,        -- Chỉ số đặc thù ngành (ngân hàng, BĐS...)
    fetched_at            TIMESTAMP     DEFAULT NOW(),

    UNIQUE (symbol, year_report, quarter_report)
);

CREATE INDEX idx_rs_symbol ON ratio_summary(symbol);
CREATE INDEX idx_rs_roe    ON ratio_summary(roe);
CREATE INDEX idx_rs_pe     ON ratio_summary(pe);

COMMENT ON TABLE ratio_summary IS
    'Snapshot tổng hợp tài chính mới nhất từ Company.ratio_summary(). '
    'Dùng cho stock screener và so sánh nhanh giữa các mã.';
```

---

### 1.4 Bảng vận hành pipeline

#### `pipeline_logs` — Nhật ký ETL

```sql
CREATE TABLE pipeline_logs (
    id               SERIAL       PRIMARY KEY,
    job_name         VARCHAR(100) NOT NULL,
    symbol           VARCHAR(10),
    status           VARCHAR(20)  NOT NULL CHECK (status IN ('running','success','failed','skipped')),
    records_fetched  INTEGER      DEFAULT 0,
    records_inserted INTEGER      DEFAULT 0,
    error_message    TEXT,
    started_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMP,
    duration_ms      INTEGER      GENERATED ALWAYS AS
                        (EXTRACT(MILLISECONDS FROM finished_at - started_at)::INTEGER) STORED
);

CREATE INDEX idx_logs_job_name   ON pipeline_logs(job_name);
CREATE INDEX idx_logs_status     ON pipeline_logs(status);
CREATE INDEX idx_logs_started_at ON pipeline_logs(started_at DESC);

COMMENT ON TABLE pipeline_logs IS 'Nhật ký chạy ETL pipeline, theo dõi trạng thái từng job.';
```

---

## Phần 2 — Thiết kế cấu trúc dự án ETL

### Nguyên tắc thiết kế

- **Tách biệt rõ ràng** Extract / Transform / Load thành các lớp độc lập
- **Tái sử dụng** thông qua abstract base class
- **Quan sát được** (observability) qua logging có cấu trúc và bảng `pipeline_logs`
- **Chịu lỗi được** (resilience) qua retry tự động, bỏ qua lỗi đơn lẻ, tiếp tục batch
- **Dễ mở rộng** — thêm nguồn dữ liệu hoặc bảng mới mà không viết lại logic chung

---

### Cấu trúc thư mục

```
data-pipeline/
│
├── config/
│   ├── __init__.py
│   ├── settings.py          # DB URL, API source, retry, max_workers...
│   └── constants.py         # Các hằng số: nguồn hợp lệ, interval, tên job...
│
├── db/
│   ├── __init__.py
│   ├── connection.py        # SQLAlchemy engine + session factory
│   ├── models.py            # ORM models (SQLAlchemy Declarative)
│   └── migrations/          # SQL files tạo schema
│       ├── 001_reference_tables.sql
│       ├── 002_financial_tables.sql
│       ├── 003_company_tables.sql
│       └── 004_pipeline_logs.sql
│
├── etl/
│   ├── __init__.py
│   │
│   ├── base/                # Abstract interfaces
│   │   ├── extractor.py     # BaseExtractor.extract(symbol, **kwargs) → DataFrame
│   │   ├── transformer.py   # BaseTransformer.transform(df, symbol) → DataFrame
│   │   └── loader.py        # BaseLoader.load(df, table, conflict_cols) → int
│   │
│   ├── extractors/          # Gọi vnstock_data API, trả về DataFrame thô
│   │   ├── listing.py       # ListingExtractor  → companies, icb_industries
│   │   ├── finance.py       # FinanceExtractor  → 4 loại BCTC
│   │   ├── company.py       # CompanyExtractor  → overview, shareholders, officers, events...
│   │   └── trading.py       # TradingExtractor  → ratio_summary, trading_stats
│   │
│   ├── transformers/        # Làm sạch, đổi tên cột tiếng Việt → English, ép kiểu
│   │   ├── listing.py
│   │   ├── finance.py       # Map ~100 cột tiếng Việt → schema columns
│   │   ├── company.py
│   │   └── trading.py
│   │
│   ├── loaders/             # Insert/upsert vào PostgreSQL
│   │   ├── postgres.py      # PostgresLoader: bulk upsert ON CONFLICT DO UPDATE
│   │   └── helpers.py       # build_upsert_query(), chunk_dataframe()...
│   │
│   └── pipeline.py          # Orchestrator: E→T→L + ghi pipeline_logs
│
├── jobs/                    # Định nghĩa từng job ETL cụ thể
│   ├── __init__.py
│   ├── sync_listing.py      # Đồng bộ danh mục + ngành ICB
│   ├── sync_financials.py   # Lấy BCTC cho toàn bộ danh mục
│   ├── sync_company.py      # Lấy cổ đông, lãnh đạo, sự kiện
│   ├── sync_ratios.py       # Lấy ratio_summary mới nhất
│   └── backfill.py          # Chạy lại lịch sử: python main.py backfill --symbol HPG
│
├── scheduler/
│   ├── __init__.py
│   └── jobs.py              # APScheduler: đăng ký tất cả jobs với lịch chạy
│
├── utils/
│   ├── __init__.py
│   ├── logger.py            # Logging chuẩn hóa
│   ├── retry.py             # Decorator retry với exponential backoff
│   └── date_utils.py        # Xử lý period: '2024Q1', '2024', parse, format...
│
├── tests/
│   ├── test_extractors.py
│   ├── test_transformers.py
│   └── test_loaders.py
│
├── docs/
│   ├── explain.md
│   └── plan.md              # (file này)
│
├── jupyter_test/            # Notebooks kiểm thử dữ liệu thô (đã có)
│
├── .env                     # DATABASE_URL, API_SOURCE, ...
├── .env.example
├── requirements.txt
└── main.py                  # Entry point CLI
```

---

### Mô tả các module cốt lõi

#### `etl/base/extractor.py`

```python
from abc import ABC, abstractmethod
import pandas as pd

class BaseExtractor(ABC):
    def __init__(self, source: str = "vci"):
        self.source = source

    @abstractmethod
    def extract(self, symbol: str, **kwargs) -> pd.DataFrame:
        """Gọi vnstock_data API, trả về DataFrame thô chưa làm sạch."""
        ...
```

#### `etl/base/transformer.py`

```python
from abc import ABC, abstractmethod
import pandas as pd

class BaseTransformer(ABC):
    @abstractmethod
    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        """Đổi tên cột, ép kiểu, loại bỏ dòng null không hợp lệ."""
        ...
```

#### `etl/base/loader.py`

```python
from abc import ABC, abstractmethod
import pandas as pd

class BaseLoader(ABC):
    @abstractmethod
    def load(self, df: pd.DataFrame, table: str, conflict_columns: list[str]) -> int:
        """Upsert DataFrame vào bảng. Trả về số dòng được insert/update."""
        ...
```

#### `etl/pipeline.py` — Orchestrator

```python
class Pipeline:
    """Kết nối Extractor → Transformer → Loader, ghi log vào pipeline_logs."""

    def __init__(self, extractor, transformer, loader, job_name: str):
        ...

    def run(self, symbol: str, **kwargs) -> dict:
        # 1. Ghi trạng thái 'running' vào pipeline_logs
        # 2. extractor.extract(symbol, **kwargs)
        # 3. transformer.transform(df, symbol)
        # 4. loader.load(df, table, conflict_columns)
        # 5. Cập nhật pipeline_logs: 'success' hoặc 'failed'
        # 6. Trả về {symbol, status, records_inserted}
        ...

    def run_batch(self, symbols: list[str], max_workers: int = 5, **kwargs):
        """Chạy song song cho nhiều mã bằng ThreadPoolExecutor."""
        ...
```

#### `etl/loaders/postgres.py` — Upsert

```python
# Chiến lược upsert: INSERT ... ON CONFLICT DO UPDATE
# Ví dụ cho balance_sheets:
INSERT INTO balance_sheets (symbol, period, period_type, total_assets, ...)
VALUES (%s, %s, %s, %s, ...)
ON CONFLICT (symbol, period, period_type)
DO UPDATE SET
    total_assets = EXCLUDED.total_assets,
    ...,
    fetched_at   = NOW()
WHERE balance_sheets.total_assets IS DISTINCT FROM EXCLUDED.total_assets;
```

---

### Luồng xử lý một job điển hình

```
APScheduler (scheduler/jobs.py)
    │
    ▼
jobs/sync_financials.py
    │  1. Lấy danh sách symbol từ bảng companies WHERE status='listed'
    │  2. Với mỗi symbol, gọi Pipeline.run_batch():
    ▼
etl/pipeline.py
    │
    ├─► [Extract]
    │   FinanceExtractor.extract(symbol, period='year', report_type='balance_sheet')
    │       └─ Finance(symbol, 'year', 'vci').balance_sheet(lang='en', mode='final')
    │
    ├─► [Transform]
    │   FinanceTransformer.transform(df, symbol, period_type='year')
    │       └─ Serialize toàn bộ DataFrame gốc → cột raw_data (JSONB)
    │       └─ Đổi tên cột tiếng Việt → tên cột schema tiếng Anh
    │       └─ Tạo cột 'period' = "2024", "2023"...
    │       └─ Ép kiểu BIGINT, loại dòng toàn null
    │
    ├─► [Load]
    │   PostgresLoader.load(df, 'balance_sheets', ['symbol','period','period_type'])
    │       └─ INSERT ... ON CONFLICT DO UPDATE SET ...
    │
    └─► pipeline_logs (ghi kết quả: success/failed, số dòng, thời gian)
```

---

## Phần 3 — Lịch chạy pipeline

| Job | Tần suất | Bảng đích | Ghi chú |
|---|---|---|---|
| `sync_listing` | Hàng tuần, Chủ Nhật 01:00 | `companies`, `icb_industries` | Cập nhật mã mới niêm yết/hủy niêm yết |
| `sync_financials` | Mỗi 2 tuần (hoặc trigger thủ công sau mùa BCTC) | `balance_sheets`, `income_statements`, `cash_flows`, `financial_ratios` | BCTC thường công bố 30–45 ngày sau khi kết thúc quý |
| `sync_company` | Hàng tuần, Thứ Hai 02:00 | `shareholders`, `officers`, `subsidiaries`, `corporate_events` | Theo dõi biến động cổ đông lớn, nhân sự lãnh đạo |
| `sync_ratios` | Hàng ngày, 18:30 (sau đóng cửa) | `ratio_summary` | Snapshot P/E, P/B, ROE... theo giá đóng cửa mới nhất |
| `backfill` | Thủ công | Tất cả | Chạy lại lịch sử khi thêm mã mới hoặc sửa lỗi transformer |

---

## Phần 4 — Dependencies

```txt
# requirements.txt (các package chính)
vnstock>=3.5.0
vnstock_data>=3.0.0

# Database
psycopg2-binary>=2.9
sqlalchemy>=2.0
alembic>=1.13          # Migration tự động (tuỳ chọn)

# Scheduling
apscheduler>=3.10

# Utilities
pandas>=2.0
python-dotenv>=1.0
tenacity>=8.0          # Retry với exponential backoff
tqdm>=4.0              # Progress bar khi chạy batch
```

---

## Phần 5 — Thứ tự triển khai

### Giai đoạn 1 — Nền tảng
1. Tạo PostgreSQL database, chạy 4 migration files
2. Viết `config/settings.py`, `db/connection.py`
3. Viết `etl/base/` (abstract classes)
4. Viết `etl/loaders/postgres.py` (bulk upsert)
5. Viết `utils/logger.py`, `utils/retry.py`

### Giai đoạn 2 — Module Danh mục
1. `etl/extractors/listing.py` — gọi `Listing.all_symbols()` + `industries_icb()`
2. `etl/transformers/listing.py` — map cột, chuẩn hóa type/exchange/status
3. `jobs/sync_listing.py`
4. Kiểm thử: chạy thủ công, kiểm tra dữ liệu trong DB

### Giai đoạn 3 — Module Tài chính *(ưu tiên cao nhất)*
1. `etl/extractors/finance.py` — gọi 4 API BCTC (balance_sheet, income_stmt, cash_flow, ratio)
2. `etl/transformers/finance.py` — map cột tiếng Việt → English dựa trên CSV đã có trong `jupyter_test`
3. `jobs/sync_financials.py` + `jobs/backfill.py`
4. Kiểm thử với HPG (thép), FPT (công nghệ), VCB (ngân hàng) — 3 ngành có cấu trúc BCTC khác nhau

### Giai đoạn 4 — Module Doanh nghiệp
1. `etl/extractors/company.py`
2. `etl/transformers/company.py`
3. `jobs/sync_company.py`

### Giai đoạn 5 — Scheduler & CLI
1. `etl/extractors/trading.py` (ratio_summary)
2. `jobs/sync_ratios.py`
3. `scheduler/jobs.py` — đăng ký tất cả jobs với APScheduler
4. `main.py` — CLI: `python main.py sync_financials --symbol HPG --period year`

### Giai đoạn 6 — Vận hành
1. Dockerize (PostgreSQL + pipeline service)
2. Dashboard theo dõi `pipeline_logs` (Metabase hoặc Superset)
3. Alert khi job liên tiếp thất bại

---

## Tóm tắt quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| Schema | Cột tổng hợp (typed) + `raw_data JSONB` cho 3 bảng BCTC | Cột typed để query/screener nhanh; JSONB giữ lại toàn bộ ~140 cột gốc để drill-down khi cần |
| Period key | `(symbol, period, period_type)` → `('HPG', '2024Q1', 'quarter')` | Human-readable, dễ filter theo năm/quý |
| Upsert | `ON CONFLICT DO UPDATE` | Chạy lại pipeline không tạo trùng lặp dữ liệu |
| Column mapping | Transformer riêng mỗi module | BCTC có ~100 cột tiếng Việt cần map rõ ràng |
| Concurrency | ThreadPoolExecutor trong `Pipeline.run_batch` | vnstock API không hỗ trợ async native |
| Logging | Bảng `pipeline_logs` trong DB | Dễ query lịch sử, alert khi job thất bại |
| Ngân hàng/BĐS | Cột đặc thù + cột `extra_metrics JSONB` | Cấu trúc BCTC ngân hàng khác hoàn toàn ngành thường |
