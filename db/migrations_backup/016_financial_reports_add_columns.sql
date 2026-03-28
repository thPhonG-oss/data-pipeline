-- Migration 016: Bổ sung cột còn thiếu trong financial_reports
-- Thêm tất cả canonical fields mà parsers sản xuất ra nhưng chưa có cột lưu trữ.
-- Gồm: banking-specific, insurance-specific, securities-specific, và non-financial extras.

ALTER TABLE financial_reports

    -- ── Cross-industry extras ─────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS share_premium              NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS minority_interest_bs       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS minority_interest_is       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS eps_diluted                NUMERIC(20,4),
    ADD COLUMN IF NOT EXISTS total_current_liabilities  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS total_long_term_liabilities NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS total_liabilities_and_equity NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS accounts_payable           NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS goodwill                   NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS short_term_investments     NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS inventory_allowance        NUMERIC(20,2),

    -- ── Non-financial IS extras ───────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS revenue_deductions         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS financial_income           NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS financial_expenses         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS income_tax                 NUMERIC(20,2),

    -- ── Non-financial CF extras ───────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS cf_ebt                     NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS depreciation_amortization  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS cf_interest_expense        NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS change_in_receivables      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS change_in_inventory        NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS change_in_payables         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS asset_disposal_proceeds    NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS debt_proceeds              NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS debt_repayment             NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS dividends_paid             NUMERIC(20,2),

    -- ── Banking BS ────────────────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS deposits_at_state_bank     NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS interbank_deposits         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS trading_securities         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS investment_securities      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS interbank_borrowings       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS bonds_issued               NUMERIC(20,2),

    -- ── Banking IS ────────────────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS interest_income            NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS fee_and_commission_income  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS forex_trading_income       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS trading_securities_income  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS investment_securities_income NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS other_income               NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS operating_expenses         NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS pre_provision_profit       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS total_operating_income     NUMERIC(20,2),

    -- ── Insurance BS ──────────────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS financial_investments      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS insurance_premium_receivables NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS insurance_technical_reserves  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS insurance_claims_payable   NUMERIC(20,2),

    -- ── Insurance IS ──────────────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS net_insurance_premium      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS net_insurance_claims       NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS insurance_acquisition_costs NUMERIC(20,2),

    -- ── Securities BS ─────────────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS margin_lending             NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS fvtpl_assets               NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS available_for_sale_assets  NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS settlement_receivables     NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS settlement_payables        NUMERIC(20,2),

    -- ── Securities IS ─────────────────────────────────────────────────────────
    ADD COLUMN IF NOT EXISTS brokerage_revenue          NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS advisory_revenue           NUMERIC(20,2);
