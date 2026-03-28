-- ============================================================
-- Migration 005: financial_reports
--
-- Bảng thống nhất BCĐKT / KQKD / LCTT cho 4 mẫu biểu:
--   non_financial (sản xuất/bán lẻ/công nghệ)
--   banking       (ICB 3010xxxx)
--   securities    (ICB 3020xxxx)
--   insurance     (ICB 3030xxxx)
--
-- Conflict key: (symbol, period, period_type, statement_type)
-- ============================================================

-- ── ENUM types ────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE statement_type_enum AS ENUM (
        'balance_sheet',
        'income_statement',
        'cash_flow'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE period_type_enum AS ENUM (
        'year',
        'quarter'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE fin_template_enum AS ENUM (
        'non_financial',
        'banking',
        'securities',
        'insurance'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── Bảng chính ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS financial_reports (

    -- ── Định danh ─────────────────────────────────────────────────────────────
    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,
    period_type     period_type_enum     NOT NULL,
    statement_type  statement_type_enum  NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',

    -- ── Cross-industry BS core ─────────────────────────────────────────────
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

    -- ── Non-financial BS ──────────────────────────────────────────────────────
    inventory_gross             NUMERIC(20, 2),
    inventory_allowance         NUMERIC(20, 2),
    inventory_net               NUMERIC(20, 2),
    short_term_receivables      NUMERIC(20, 2),
    ppe_gross                   NUMERIC(20, 2),
    accumulated_depreciation    NUMERIC(20, 2),
    ppe_net                     NUMERIC(20, 2),
    construction_in_progress    NUMERIC(20, 2),

    -- ── Banking BS ────────────────────────────────────────────────────────────
    deposits_at_state_bank      NUMERIC(20, 2),
    interbank_deposits          NUMERIC(20, 2),
    trading_securities          NUMERIC(20, 2),
    investment_securities       NUMERIC(20, 2),
    customer_loans_gross        NUMERIC(20, 2),
    loan_loss_reserve           NUMERIC(20, 2),
    customer_deposits           NUMERIC(20, 2),
    interbank_borrowings        NUMERIC(20, 2),
    bonds_issued                NUMERIC(20, 2),

    -- ── Insurance BS ──────────────────────────────────────────────────────────
    financial_investments       NUMERIC(20, 2),
    insurance_premium_receivables NUMERIC(20, 2),
    insurance_technical_reserves  NUMERIC(20, 2),
    insurance_claims_payable    NUMERIC(20, 2),

    -- ── Securities BS ─────────────────────────────────────────────────────────
    margin_lending              NUMERIC(20, 2),
    fvtpl_assets                NUMERIC(20, 2),
    available_for_sale_assets   NUMERIC(20, 2),
    settlement_receivables      NUMERIC(20, 2),
    settlement_payables         NUMERIC(20, 2),

    -- ── Cross-industry IS core ─────────────────────────────────────────────
    net_revenue                 NUMERIC(20, 2),
    operating_profit            NUMERIC(20, 2),
    ebt                         NUMERIC(20, 2),
    net_profit                  NUMERIC(20, 2),
    net_profit_parent           NUMERIC(20, 2),
    minority_interest_is        NUMERIC(20, 2),
    eps_basic                   NUMERIC(15, 2),
    eps_diluted                 NUMERIC(20, 4),

    -- ── Non-financial IS ──────────────────────────────────────────────────────
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

    -- ── Banking IS ────────────────────────────────────────────────────────────
    interest_income             NUMERIC(20, 2),
    fee_and_commission_income   NUMERIC(20, 2),
    forex_trading_income        NUMERIC(20, 2),
    trading_securities_income   NUMERIC(20, 2),
    investment_securities_income NUMERIC(20, 2),
    other_income                NUMERIC(20, 2),
    total_operating_income      NUMERIC(20, 2),
    operating_expenses          NUMERIC(20, 2),
    net_interest_income         NUMERIC(20, 2),
    pre_provision_profit        NUMERIC(20, 2),
    credit_provision_expense    NUMERIC(20, 2),

    -- ── Insurance IS ──────────────────────────────────────────────────────────
    net_insurance_premium       NUMERIC(20, 2),
    net_insurance_claims        NUMERIC(20, 2),
    insurance_acquisition_costs NUMERIC(20, 2),

    -- ── Securities IS ─────────────────────────────────────────────────────────
    brokerage_revenue           NUMERIC(20, 2),
    advisory_revenue            NUMERIC(20, 2),

    -- ── CF core (all templates) ───────────────────────────────────────────────
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

    -- ── Raw + audit ───────────────────────────────────────────────────────────
    raw_details                 JSONB        NOT NULL DEFAULT '{}',
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_financial_reports
        UNIQUE (symbol, period, period_type, statement_type)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_fr_symbol_period
    ON financial_reports (symbol, period_type, period DESC);

CREATE INDEX IF NOT EXISTS idx_fr_period_template
    ON financial_reports (period, period_type, template);

CREATE INDEX IF NOT EXISTS idx_fr_symbol_stmt
    ON financial_reports (symbol, statement_type);

CREATE INDEX IF NOT EXISTS idx_fr_raw_details_gin
    ON financial_reports USING GIN (raw_details);

CREATE INDEX IF NOT EXISTS idx_fr_annual
    ON financial_reports (symbol, period DESC)
    WHERE period_type = 'year';

-- ── CHECK Constraints (NOT VALID) ────────────────────────────────────────────

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_banking_null_inventory
        CHECK (NOT (template = 'banking' AND inventory_net IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_banking_null_cogs
        CHECK (NOT (template = 'banking' AND cost_of_goods_sold IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_nonfinancial_null_loans
        CHECK (NOT (template = 'non_financial' AND customer_loans_gross IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_nonfinancial_null_nii
        CHECK (NOT (template = 'non_financial' AND net_interest_income IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
