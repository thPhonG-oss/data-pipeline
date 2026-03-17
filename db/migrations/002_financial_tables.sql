-- ============================================================
-- Migration 002: Bảng báo cáo tài chính (Financial Statements)
-- balance_sheets, income_statements, cash_flows, financial_ratios
--
-- Quy ước period:
--   '2024'   → period_type = 'year'
--   '2024Q1' → period_type = 'quarter'
-- ============================================================

-- ── Bảng cân đối kế toán ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS balance_sheets (
    id                          SERIAL       PRIMARY KEY,
    symbol                      VARCHAR(10)  NOT NULL
        CONSTRAINT fk_bs_symbol REFERENCES companies(symbol),
    period                      VARCHAR(10)  NOT NULL,
    period_type                 VARCHAR(10)  NOT NULL
        CHECK (period_type IN ('year', 'quarter')),

    -- Tài sản ngắn hạn
    cash_and_equivalents        BIGINT,
    short_term_investments      BIGINT,
    accounts_receivable         BIGINT,
    inventory                   BIGINT,
    other_current_assets        BIGINT,
    total_current_assets        BIGINT,

    -- Tài sản dài hạn
    long_term_receivables       BIGINT,
    fixed_assets                BIGINT,
    investment_properties       BIGINT,
    long_term_investments       BIGINT,
    intangible_assets           BIGINT,
    other_long_term_assets      BIGINT,
    total_long_term_assets      BIGINT,
    total_assets                BIGINT,

    -- Nợ ngắn hạn
    short_term_debt             BIGINT,
    accounts_payable            BIGINT,
    advances_from_customers     BIGINT,
    other_current_liabilities   BIGINT,
    total_current_liabilities   BIGINT,

    -- Nợ dài hạn
    long_term_debt              BIGINT,
    other_long_term_liabilities BIGINT,
    total_long_term_liabilities BIGINT,
    total_liabilities           BIGINT,

    -- Vốn chủ sở hữu
    charter_capital_fs          BIGINT,
    share_premium               BIGINT,
    retained_earnings           BIGINT,
    other_equity                BIGINT,
    minority_interest           BIGINT,
    total_equity                BIGINT,
    total_liabilities_equity    BIGINT,

    -- Dữ liệu gốc đầy đủ (~140 cột tên tiếng Việt từ API)
    raw_data                    JSONB,

    source                      VARCHAR(20) DEFAULT 'vci',
    fetched_at                  TIMESTAMP   DEFAULT NOW(),

    CONSTRAINT uq_balance_sheets UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_bs_symbol   ON balance_sheets(symbol);
CREATE INDEX IF NOT EXISTS idx_bs_period   ON balance_sheets(period, period_type);
CREATE INDEX IF NOT EXISTS idx_bs_raw_data ON balance_sheets USING GIN (raw_data);

COMMENT ON TABLE  balance_sheets IS
    'Bảng cân đối kế toán theo năm và quý. '
    'Cột tổng hợp để screener/so sánh; raw_data lưu ~140 cột gốc để drill-down. '
    'Nguồn: vnstock_data.Finance.balance_sheet().';

-- ── Báo cáo kết quả kinh doanh ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS income_statements (
    id                      SERIAL       PRIMARY KEY,
    symbol                  VARCHAR(10)  NOT NULL
        CONSTRAINT fk_is_symbol REFERENCES companies(symbol),
    period                  VARCHAR(10)  NOT NULL,
    period_type             VARCHAR(10)  NOT NULL
        CHECK (period_type IN ('year', 'quarter')),

    -- Doanh thu
    gross_revenue           BIGINT,
    revenue_deductions      BIGINT,
    net_revenue             BIGINT,

    -- Chi phí & lợi nhuận
    cogs                    BIGINT,
    gross_profit            BIGINT,
    financial_income        BIGINT,
    financial_expense       BIGINT,
    interest_expense        BIGINT,
    selling_expense         BIGINT,
    admin_expense           BIGINT,
    operating_profit        BIGINT,
    other_income            BIGINT,
    other_expense           BIGINT,
    profit_from_associates  BIGINT,
    ebt                     BIGINT,
    income_tax              BIGINT,
    profit_after_tax        BIGINT,
    minority_profit         BIGINT,
    net_profit              BIGINT,

    -- Cổ phiếu
    eps_basic               NUMERIC(15, 2),
    eps_diluted             NUMERIC(15, 2),
    shares_outstanding      BIGINT,

    -- Dữ liệu gốc đầy đủ
    raw_data                JSONB,

    source                  VARCHAR(20) DEFAULT 'vci',
    fetched_at              TIMESTAMP   DEFAULT NOW(),

    CONSTRAINT uq_income_statements UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_is_symbol   ON income_statements(symbol);
CREATE INDEX IF NOT EXISTS idx_is_period   ON income_statements(period, period_type);
CREATE INDEX IF NOT EXISTS idx_is_raw_data ON income_statements USING GIN (raw_data);

COMMENT ON TABLE income_statements IS
    'Báo cáo kết quả kinh doanh theo năm và quý. '
    'Cột tổng hợp để screener/so sánh; raw_data lưu cột gốc để drill-down. '
    'Nguồn: vnstock_data.Finance.income_statement().';

-- ── Báo cáo lưu chuyển tiền tệ ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS cash_flows (
    id                              SERIAL       PRIMARY KEY,
    symbol                          VARCHAR(10)  NOT NULL
        CONSTRAINT fk_cf_symbol REFERENCES companies(symbol),
    period                          VARCHAR(10)  NOT NULL,
    period_type                     VARCHAR(10)  NOT NULL
        CHECK (period_type IN ('year', 'quarter')),

    -- Hoạt động kinh doanh
    net_profit_before_tax           BIGINT,
    depreciation                    BIGINT,
    provision                       BIGINT,
    unrealized_fx_gain_loss         BIGINT,
    investment_income               BIGINT,
    interest_expense_cf             BIGINT,
    change_in_receivables           BIGINT,
    change_in_inventory             BIGINT,
    change_in_payables              BIGINT,
    other_operating_changes         BIGINT,
    income_tax_paid                 BIGINT,
    operating_cash_flow             BIGINT,

    -- Hoạt động đầu tư
    capex                           BIGINT,
    proceeds_from_asset_disposal    BIGINT,
    investment_purchases            BIGINT,
    investment_proceeds             BIGINT,
    interest_and_dividends_received BIGINT,
    investing_cash_flow             BIGINT,

    -- Hoạt động tài chính
    proceeds_from_borrowings        BIGINT,
    repayment_of_borrowings         BIGINT,
    proceeds_from_equity_issuance   BIGINT,
    dividends_paid                  BIGINT,
    financing_cash_flow             BIGINT,

    net_cash_change                 BIGINT,
    beginning_cash                  BIGINT,
    ending_cash                     BIGINT,

    -- Dữ liệu gốc đầy đủ
    raw_data                        JSONB,

    source                          VARCHAR(20) DEFAULT 'vci',
    fetched_at                      TIMESTAMP   DEFAULT NOW(),

    CONSTRAINT uq_cash_flows UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_cf_symbol   ON cash_flows(symbol);
CREATE INDEX IF NOT EXISTS idx_cf_period   ON cash_flows(period, period_type);
CREATE INDEX IF NOT EXISTS idx_cf_raw_data ON cash_flows USING GIN (raw_data);

COMMENT ON TABLE cash_flows IS
    'Báo cáo lưu chuyển tiền tệ. '
    'Cột tổng hợp để screener/so sánh; raw_data lưu cột gốc để drill-down. '
    'Nguồn: vnstock_data.Finance.cash_flow().';

-- ── Chỉ số tài chính ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS financial_ratios (
    id                       SERIAL       PRIMARY KEY,
    symbol                   VARCHAR(10)  NOT NULL
        CONSTRAINT fk_fr_symbol REFERENCES companies(symbol),
    period                   VARCHAR(10)  NOT NULL,
    period_type              VARCHAR(10)  NOT NULL
        CHECK (period_type IN ('year', 'quarter')),

    -- Định giá
    pe                       NUMERIC(12, 4),
    pb                       NUMERIC(12, 4),
    ps                       NUMERIC(12, 4),
    pcf                      NUMERIC(12, 4),
    ev_ebitda                NUMERIC(12, 4),
    ev                       BIGINT,

    -- Khả năng sinh lời
    roe                      NUMERIC(10, 4),
    roa                      NUMERIC(10, 4),
    roic                     NUMERIC(10, 4),
    gross_margin             NUMERIC(10, 4),
    ebit_margin              NUMERIC(10, 4),
    net_profit_margin        NUMERIC(10, 4),
    ebitda                   BIGINT,
    ebit                     BIGINT,

    -- Thanh khoản
    current_ratio            NUMERIC(10, 4),
    quick_ratio              NUMERIC(10, 4),
    cash_ratio               NUMERIC(10, 4),
    interest_coverage        NUMERIC(10, 4),

    -- Đòn bẩy
    debt_to_equity           NUMERIC(10, 4),
    debt_to_assets           NUMERIC(10, 4),
    financial_leverage       NUMERIC(10, 4),

    -- Hiệu quả hoạt động
    asset_turnover           NUMERIC(10, 4),
    fixed_asset_turnover     NUMERIC(10, 4),
    inventory_days           NUMERIC(10, 2),
    receivable_days          NUMERIC(10, 2),
    payable_days             NUMERIC(10, 2),
    cash_conversion_cycle    NUMERIC(10, 2),

    -- Cổ phiếu
    eps                      NUMERIC(15, 2),
    eps_ttm                  NUMERIC(15, 2),
    bvps                     NUMERIC(15, 2),
    dividend                 NUMERIC(15, 2),

    -- Chỉ số ngành ngân hàng
    npl_ratio                NUMERIC(10, 4),
    car                      NUMERIC(10, 4),
    ldr                      NUMERIC(10, 4),
    nim                      NUMERIC(10, 4),

    source                   VARCHAR(20) DEFAULT 'vci',
    fetched_at               TIMESTAMP   DEFAULT NOW(),

    CONSTRAINT uq_financial_ratios UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fr_symbol ON financial_ratios(symbol);
CREATE INDEX IF NOT EXISTS idx_fr_period ON financial_ratios(period, period_type);
CREATE INDEX IF NOT EXISTS idx_fr_roe    ON financial_ratios(roe);
CREATE INDEX IF NOT EXISTS idx_fr_pe     ON financial_ratios(pe);

COMMENT ON TABLE financial_ratios IS
    'Chỉ số tài chính tổng hợp theo năm/quý. Nguồn: vnstock_data.Finance.ratio().';
