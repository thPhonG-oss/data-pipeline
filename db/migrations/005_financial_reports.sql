-- ============================================================
-- Migration 005: Financial Schema — ENUMs + Approach C (4 tables)
--
-- Tables:
--   fin_balance_sheet       — Bảng cân đối kế toán
--   fin_income_statement    — Kết quả hoạt động kinh doanh
--   fin_cash_flow           — Lưu chuyển tiền tệ
--   fin_financial_ratios    — Chỉ số tài chính lịch sử (ratio API)
--
-- Mỗi bảng có:
--   template  → phân biệt cấu trúc BCTC (non_financial/banking/securities/insurance)
--   icb_code  → phân ngành cho analytics/screener không cần JOIN companies
-- ============================================================

-- ── ENUM types ────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE period_type_enum AS ENUM ('year', 'quarter');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE fin_template_enum AS ENUM (
        'non_financial', 'banking', 'securities', 'insurance'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- Bảng 1: fin_balance_sheet
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_balance_sheet (

    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,
    period_type     period_type_enum     NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',
    icb_code        VARCHAR(10),

    -- ── Cross-industry ────────────────────────────────────────────────────────
    cash_and_equivalents        NUMERIC(20, 2),
    short_term_investments      NUMERIC(20, 2),
    total_current_assets        NUMERIC(20, 2),
    total_non_current_assets    NUMERIC(20, 2),
    total_assets                NUMERIC(20, 2),
    accounts_payable            NUMERIC(20, 2),
    total_current_liabilities   NUMERIC(20, 2),
    total_long_term_liabilities NUMERIC(20, 2),
    total_liabilities           NUMERIC(20, 2),
    total_liabilities_and_equity NUMERIC(20, 2),
    charter_capital             NUMERIC(20, 2),
    share_premium               NUMERIC(20, 2),
    retained_earnings           NUMERIC(20, 2),
    minority_interest_bs        NUMERIC(20, 2),
    total_equity                NUMERIC(20, 2),
    short_term_debt             NUMERIC(20, 2),
    long_term_debt              NUMERIC(20, 2),
    goodwill                    NUMERIC(20, 2),

    -- ── Non-financial ─────────────────────────────────────────────────────────
    inventory_gross             NUMERIC(20, 2),
    inventory_allowance         NUMERIC(20, 2),
    inventory_net               NUMERIC(20, 2),
    short_term_receivables      NUMERIC(20, 2),
    ppe_gross                   NUMERIC(20, 2),
    accumulated_depreciation    NUMERIC(20, 2),
    ppe_net                     NUMERIC(20, 2),
    construction_in_progress    NUMERIC(20, 2),

    -- ── Banking ───────────────────────────────────────────────────────────────
    deposits_at_state_bank      NUMERIC(20, 2),
    interbank_deposits          NUMERIC(20, 2),
    trading_securities          NUMERIC(20, 2),
    investment_securities       NUMERIC(20, 2),
    customer_loans_gross        NUMERIC(20, 2),
    loan_loss_reserve           NUMERIC(20, 2),
    customer_deposits           NUMERIC(20, 2),
    interbank_borrowings        NUMERIC(20, 2),
    bonds_issued                NUMERIC(20, 2),

    -- ── Insurance ─────────────────────────────────────────────────────────────
    financial_investments            NUMERIC(20, 2),
    insurance_premium_receivables    NUMERIC(20, 2),
    insurance_technical_reserves     NUMERIC(20, 2),
    insurance_claims_payable         NUMERIC(20, 2),

    -- ── Securities ────────────────────────────────────────────────────────────
    margin_lending              NUMERIC(20, 2),
    fvtpl_assets                NUMERIC(20, 2),
    available_for_sale_assets   NUMERIC(20, 2),
    settlement_receivables      NUMERIC(20, 2),
    settlement_payables         NUMERIC(20, 2),

    -- ── Audit ─────────────────────────────────────────────────────────────────
    raw_details                 JSONB        NOT NULL DEFAULT '{}',
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_fin_bs UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fin_bs_symbol_period   ON fin_balance_sheet (symbol, period_type, period DESC);
CREATE INDEX IF NOT EXISTS idx_fin_bs_period_template ON fin_balance_sheet (period, period_type, template);
CREATE INDEX IF NOT EXISTS idx_fin_bs_icb_code        ON fin_balance_sheet (icb_code);
CREATE INDEX IF NOT EXISTS idx_fin_bs_annual
    ON fin_balance_sheet (symbol, period DESC) WHERE period_type = 'year';

-- ============================================================
-- Bảng 2: fin_income_statement
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_income_statement (

    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,
    period_type     period_type_enum     NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',
    icb_code        VARCHAR(10),

    -- ── Cross-industry ────────────────────────────────────────────────────────
    net_revenue                 NUMERIC(20, 2),
    operating_profit            NUMERIC(20, 2),
    ebt                         NUMERIC(20, 2),
    net_profit                  NUMERIC(20, 2),
    net_profit_parent           NUMERIC(20, 2),
    minority_interest_is        NUMERIC(20, 2),
    eps_basic                   NUMERIC(15, 2),
    eps_diluted                 NUMERIC(20, 4),

    -- ── Non-financial ─────────────────────────────────────────────────────────
    gross_revenue               NUMERIC(20, 2),
    revenue_deductions          NUMERIC(20, 2),
    cost_of_goods_sold          NUMERIC(20, 2),
    gross_profit                NUMERIC(20, 2),
    financial_income            NUMERIC(20, 2),
    financial_expenses          NUMERIC(20, 2),
    selling_expenses            NUMERIC(20, 2),
    admin_expenses              NUMERIC(20, 2),
    interest_expense            NUMERIC(20, 2),
    income_tax                  NUMERIC(20, 2),

    -- ── Banking ───────────────────────────────────────────────────────────────
    interest_income                  NUMERIC(20, 2),
    fee_and_commission_income        NUMERIC(20, 2),
    forex_trading_income             NUMERIC(20, 2),
    trading_securities_income        NUMERIC(20, 2),
    investment_securities_income     NUMERIC(20, 2),
    other_income                     NUMERIC(20, 2),
    total_operating_income           NUMERIC(20, 2),
    operating_expenses               NUMERIC(20, 2),
    net_interest_income              NUMERIC(20, 2),
    pre_provision_profit             NUMERIC(20, 2),
    credit_provision_expense         NUMERIC(20, 2),

    -- ── Insurance ─────────────────────────────────────────────────────────────
    net_insurance_premium            NUMERIC(20, 2),
    net_insurance_claims             NUMERIC(20, 2),
    insurance_acquisition_costs      NUMERIC(20, 2),

    -- ── Securities ────────────────────────────────────────────────────────────
    brokerage_revenue           NUMERIC(20, 2),
    advisory_revenue            NUMERIC(20, 2),

    -- ── Audit ─────────────────────────────────────────────────────────────────
    raw_details                 JSONB        NOT NULL DEFAULT '{}',
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_fin_is UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fin_is_symbol_period   ON fin_income_statement (symbol, period_type, period DESC);
CREATE INDEX IF NOT EXISTS idx_fin_is_period_template ON fin_income_statement (period, period_type, template);
CREATE INDEX IF NOT EXISTS idx_fin_is_icb_code        ON fin_income_statement (icb_code);
CREATE INDEX IF NOT EXISTS idx_fin_is_annual
    ON fin_income_statement (symbol, period DESC) WHERE period_type = 'year';

-- ============================================================
-- Bảng 3: fin_cash_flow
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_cash_flow (

    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,
    period_type     period_type_enum     NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',
    icb_code        VARCHAR(10),

    -- ── CF (all templates) ────────────────────────────────────────────────────
    cf_ebt                      NUMERIC(20, 2),
    depreciation_amortization   NUMERIC(20, 2),
    cf_interest_expense         NUMERIC(20, 2),
    change_in_receivables       NUMERIC(20, 2),
    change_in_inventory         NUMERIC(20, 2),
    change_in_payables          NUMERIC(20, 2),
    cfo                         NUMERIC(20, 2),
    capex                       NUMERIC(20, 2),
    asset_disposal_proceeds     NUMERIC(20, 2),
    cfi                         NUMERIC(20, 2),
    debt_proceeds               NUMERIC(20, 2),
    debt_repayment              NUMERIC(20, 2),
    dividends_paid              NUMERIC(20, 2),
    cff                         NUMERIC(20, 2),
    net_cash_change             NUMERIC(20, 2),
    cash_beginning              NUMERIC(20, 2),
    cash_ending                 NUMERIC(20, 2),

    -- ── Audit ─────────────────────────────────────────────────────────────────
    raw_details                 JSONB        NOT NULL DEFAULT '{}',
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_fin_cf UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fin_cf_symbol_period ON fin_cash_flow (symbol, period_type, period DESC);
CREATE INDEX IF NOT EXISTS idx_fin_cf_icb_code      ON fin_cash_flow (icb_code);
CREATE INDEX IF NOT EXISTS idx_fin_cf_annual
    ON fin_cash_flow (symbol, period DESC) WHERE period_type = 'year';

-- ============================================================
-- Bảng 4: fin_financial_ratios
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_financial_ratios (

    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,
    period_type     period_type_enum     NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',
    icb_code        VARCHAR(10),

    -- ── Market data ───────────────────────────────────────────────────────────
    shares_outstanding_millions  BIGINT,
    market_cap                   NUMERIC(22, 2),
    dividend_yield               NUMERIC(8, 4),

    -- ── Valuation ─────────────────────────────────────────────────────────────
    pe_ratio        NUMERIC(12, 4),
    pb_ratio        NUMERIC(12, 4),
    ps_ratio        NUMERIC(12, 4),
    price_to_cf     NUMERIC(12, 4),
    ev_to_ebitda    NUMERIC(12, 4),

    -- ── Liquidity ─────────────────────────────────────────────────────────────
    cash_ratio      NUMERIC(10, 4),
    quick_ratio     NUMERIC(10, 4),
    current_ratio   NUMERIC(10, 4),

    -- ── Leverage ──────────────────────────────────────────────────────────────
    debt_to_equity      NUMERIC(10, 4),
    financial_leverage  NUMERIC(10, 4),

    -- ── Profitability (decimal: 0.2763 = 27.63%) ──────────────────────────────
    roe             NUMERIC(8, 4),
    roa             NUMERIC(8, 4),
    roic            NUMERIC(8, 4),
    gross_margin    NUMERIC(8, 4),
    ebit_margin     NUMERIC(8, 4),
    pre_tax_margin  NUMERIC(8, 4),
    net_margin      NUMERIC(8, 4),

    -- ── Activity ──────────────────────────────────────────────────────────────
    asset_turnover          NUMERIC(10, 4),
    fixed_asset_turnover    NUMERIC(10, 4),
    days_receivable         NUMERIC(10, 2),
    days_inventory          NUMERIC(10, 2),
    days_payable            NUMERIC(10, 2),
    cash_cycle              NUMERIC(10, 2),

    -- ── Absolute values ───────────────────────────────────────────────────────
    ebit    NUMERIC(22, 2),
    ebitda  NUMERIC(22, 2),

    -- ── Banking-specific (NULL cho non-financial/securities/insurance) ─────────
    nim                       NUMERIC(8, 4),
    avg_earning_asset_yield   NUMERIC(8, 4),
    avg_cost_of_funds         NUMERIC(8, 4),
    non_interest_income_ratio NUMERIC(8, 4),
    cir                       NUMERIC(8, 4),
    car                       NUMERIC(8, 4),
    ldr                       NUMERIC(8, 4),
    npl_ratio                 NUMERIC(8, 4),
    npl_coverage              NUMERIC(8, 4),
    provision_to_loans        NUMERIC(8, 4),
    loan_growth               NUMERIC(8, 4),
    deposit_growth            NUMERIC(8, 4),
    equity_to_assets          NUMERIC(8, 4),
    casa_ratio                NUMERIC(8, 4),

    -- ── Audit ─────────────────────────────────────────────────────────────────
    raw_details     JSONB        NOT NULL DEFAULT '{}',
    fetched_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_fin_ratios UNIQUE (symbol, period, period_type)
);

CREATE INDEX IF NOT EXISTS idx_fin_ratios_symbol_period ON fin_financial_ratios (symbol, period_type, period DESC);
CREATE INDEX IF NOT EXISTS idx_fin_ratios_icb_code      ON fin_financial_ratios (icb_code);
CREATE INDEX IF NOT EXISTS idx_fin_ratios_template      ON fin_financial_ratios (template);
CREATE INDEX IF NOT EXISTS idx_fin_ratios_annual
    ON fin_financial_ratios (symbol, period DESC) WHERE period_type = 'year';
CREATE INDEX IF NOT EXISTS idx_fin_ratios_roe_annual
    ON fin_financial_ratios (roe DESC)
    WHERE period_type = 'year' AND roe IS NOT NULL;
