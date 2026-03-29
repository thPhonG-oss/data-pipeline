"""SQLAlchemy ORM models — ánh xạ sang tất cả bảng trong schema."""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.connection import Base

# ══════════════════════════════════════════════════════════════════════════════
# 1. BẢNG DANH MỤC (Reference Tables)
# ══════════════════════════════════════════════════════════════════════════════

class IcbIndustry(Base):
    """Phân loại ngành ICB 4 cấp."""
    __tablename__ = "icb_industries"

    icb_code:     Mapped[str]           = mapped_column(String(10), primary_key=True)
    icb_name:     Mapped[str]           = mapped_column(String(300), nullable=False)
    en_icb_name:  Mapped[str | None] = mapped_column(String(300))
    level:        Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    parent_code:  Mapped[str | None] = mapped_column(
        String(10), ForeignKey("icb_industries.icb_code")
    )
    definition:   Mapped[str | None] = mapped_column(Text)
    created_at:   Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())


class Company(Base):
    """Danh mục toàn bộ chứng khoán niêm yết."""
    __tablename__ = "companies"

    symbol:           Mapped[str]           = mapped_column(String(10), primary_key=True)
    company_name:     Mapped[str]           = mapped_column(String(500), nullable=False)
    company_name_eng: Mapped[str | None] = mapped_column(String(500))
    short_name:       Mapped[str | None] = mapped_column(String(200))
    exchange:         Mapped[str]           = mapped_column(String(20), nullable=False)
    type:             Mapped[str]           = mapped_column(String(30), nullable=False)
    status:           Mapped[str]           = mapped_column(String(20), server_default="listed")
    icb_code:         Mapped[str | None] = mapped_column(
        String(10), ForeignKey("icb_industries.icb_code")
    )
    listed_date:      Mapped[date | None]     = mapped_column(Date)
    delisted_date:    Mapped[date | None]     = mapped_column(Date)
    charter_capital:  Mapped[int | None]      = mapped_column(BigInteger)
    issue_share:      Mapped[int | None]      = mapped_column(BigInteger)
    company_id:       Mapped[int | None]      = mapped_column(Integer)
    isin:             Mapped[str | None]      = mapped_column(String(20))
    tax_code:         Mapped[str | None]      = mapped_column(String(20))
    history:          Mapped[str | None]      = mapped_column(Text)
    company_profile:  Mapped[str | None]      = mapped_column(Text)
    # ── Thông tin liên hệ từ HSX API (migration 008) ─────────────────────────
    brief:            Mapped[str | None]      = mapped_column(String(500))
    phone:            Mapped[str | None]      = mapped_column(String(100))
    fax:              Mapped[str | None]      = mapped_column(String(100))
    address:          Mapped[str | None]      = mapped_column(Text)
    web_url:          Mapped[str | None]      = mapped_column(String(500))
    created_at:       Mapped[datetime]           = mapped_column(DateTime, server_default=func.now())
    updated_at:       Mapped[datetime]           = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. BẢNG BÁO CÁO TÀI CHÍNH — APPROACH A (DEPRECATED)
# ══════════════════════════════════════════════════════════════════════════════

class FinancialReport(Base):
    """
    [DEPRECATED — Approach A] Bảng tài chính wide table.

    Sẽ bị xóa sau khi backend migrate sang 4 bảng Approach C.
    Xem: docs/task8_deprecation_plan.md
    Dùng FinBalanceSheet / FinIncomeStatement / FinCashFlow / FinFinancialRatios thay thế.
    """
    __tablename__ = "financial_reports"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type", "statement_type"),)

    id:             Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:         Mapped[str] = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:         Mapped[str] = mapped_column(String(10), nullable=False)
    period_type:    Mapped[str] = mapped_column(String(10), nullable=False)   # 'year' | 'quarter'
    statement_type: Mapped[str] = mapped_column(String(20), nullable=False)   # 'balance_sheet' | ...
    template:       Mapped[str] = mapped_column(String(20), nullable=False)   # 'non_financial' | ...
    source:         Mapped[str] = mapped_column(String(20), server_default="vci")

    # ── Tài sản — Cross-Industry Core ─────────────────────────────
    cash_and_equivalents:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_current_assets:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_non_current_assets: Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_assets:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_liabilities:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_equity:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    charter_capital:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    short_term_debt:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    long_term_debt:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    retained_earnings:        Mapped[float | None] = mapped_column(Numeric(20, 2))

    # ── Tài sản — Phi tài chính (NULL với Banking/Insurance) ──────
    inventory_net:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    inventory_gross:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    short_term_receivables:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    ppe_net:                  Mapped[float | None] = mapped_column(Numeric(20, 2))
    ppe_gross:                Mapped[float | None] = mapped_column(Numeric(20, 2))
    accumulated_depreciation: Mapped[float | None] = mapped_column(Numeric(20, 2))
    construction_in_progress: Mapped[float | None] = mapped_column(Numeric(20, 2))

    # ── Tài sản — Ngân hàng (NULL với Non-Financial) ──────────────
    customer_loans_gross:  Mapped[float | None] = mapped_column(Numeric(20, 2))
    loan_loss_reserve:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    customer_deposits:     Mapped[float | None] = mapped_column(Numeric(20, 2))

    # ── KQKD — Cross-Industry Core ────────────────────────────────
    net_revenue:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    operating_profit:  Mapped[float | None] = mapped_column(Numeric(20, 2))
    ebt:               Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_profit:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_profit_parent: Mapped[float | None] = mapped_column(Numeric(20, 2))
    eps_basic:         Mapped[float | None] = mapped_column(Numeric(15, 2))

    # ── KQKD — Phi tài chính (NULL với Banking/Insurance) ─────────
    gross_revenue:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    cost_of_goods_sold:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    gross_profit:         Mapped[float | None] = mapped_column(Numeric(20, 2))
    selling_expenses:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    admin_expenses:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    interest_expense:     Mapped[float | None] = mapped_column(Numeric(20, 2))

    # ── KQKD — Ngân hàng (NULL với Non-Financial) ─────────────────
    net_interest_income:      Mapped[float | None] = mapped_column(Numeric(20, 2))
    credit_provision_expense: Mapped[float | None] = mapped_column(Numeric(20, 2))

    # ── LCTT — Core (tất cả template) ─────────────────────────────
    cfo:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    cfi:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    cff:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    capex:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_cash_change: Mapped[float | None] = mapped_column(Numeric(20, 2))
    cash_beginning: Mapped[float | None] = mapped_column(Numeric(20, 2))
    cash_ending:    Mapped[float | None] = mapped_column(Numeric(20, 2))

    # ── Lưu trữ thô ───────────────────────────────────────────────
    raw_details: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    # ── Audit ─────────────────────────────────────────────────────
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# 3. BẢNG BÁO CÁO TÀI CHÍNH — APPROACH C (4 bảng riêng)
# ══════════════════════════════════════════════════════════════════════════════

class FinBalanceSheet(Base):
    """Bảng cân đối kế toán — Approach C."""
    __tablename__ = "fin_balance_sheet"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:             Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:         Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:         Mapped[str]           = mapped_column(String(10), nullable=False)
    period_type:    Mapped[str]           = mapped_column(String(10), nullable=False)
    template:       Mapped[str]           = mapped_column(String(20), nullable=False)
    source:         Mapped[str]           = mapped_column(String(20), server_default="vci")
    icb_code:       Mapped[str | None] = mapped_column(String(10))

    # Cross-industry
    cash_and_equivalents:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    short_term_investments:      Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_current_assets:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_non_current_assets:    Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_assets:                Mapped[float | None] = mapped_column(Numeric(20, 2))
    accounts_payable:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_current_liabilities:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_long_term_liabilities: Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_liabilities:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_liabilities_and_equity: Mapped[float | None] = mapped_column(Numeric(20, 2))
    charter_capital:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    share_premium:               Mapped[float | None] = mapped_column(Numeric(20, 2))
    retained_earnings:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    minority_interest_bs:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_equity:                Mapped[float | None] = mapped_column(Numeric(20, 2))
    short_term_debt:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    long_term_debt:              Mapped[float | None] = mapped_column(Numeric(20, 2))
    goodwill:                    Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Non-financial
    inventory_gross:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    inventory_allowance:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    inventory_net:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    short_term_receivables:    Mapped[float | None] = mapped_column(Numeric(20, 2))
    ppe_gross:                 Mapped[float | None] = mapped_column(Numeric(20, 2))
    accumulated_depreciation:  Mapped[float | None] = mapped_column(Numeric(20, 2))
    ppe_net:                   Mapped[float | None] = mapped_column(Numeric(20, 2))
    construction_in_progress:  Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Banking
    deposits_at_state_bank:    Mapped[float | None] = mapped_column(Numeric(20, 2))
    interbank_deposits:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    trading_securities:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    investment_securities:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    customer_loans_gross:      Mapped[float | None] = mapped_column(Numeric(20, 2))
    loan_loss_reserve:         Mapped[float | None] = mapped_column(Numeric(20, 2))
    customer_deposits:         Mapped[float | None] = mapped_column(Numeric(20, 2))
    interbank_borrowings:      Mapped[float | None] = mapped_column(Numeric(20, 2))
    bonds_issued:              Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Insurance
    financial_investments:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    insurance_premium_receivables:  Mapped[float | None] = mapped_column(Numeric(20, 2))
    insurance_technical_reserves:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    insurance_claims_payable:       Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Securities
    margin_lending:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    fvtpl_assets:              Mapped[float | None] = mapped_column(Numeric(20, 2))
    available_for_sale_assets: Mapped[float | None] = mapped_column(Numeric(20, 2))
    settlement_receivables:    Mapped[float | None] = mapped_column(Numeric(20, 2))
    settlement_payables:       Mapped[float | None] = mapped_column(Numeric(20, 2))

    raw_details: Mapped[dict]     = mapped_column(JSONB, server_default="{}")
    fetched_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FinIncomeStatement(Base):
    """Kết quả hoạt động kinh doanh — Approach C."""
    __tablename__ = "fin_income_statement"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str]           = mapped_column(String(10), nullable=False)
    period_type: Mapped[str]           = mapped_column(String(10), nullable=False)
    template:    Mapped[str]           = mapped_column(String(20), nullable=False)
    source:      Mapped[str]           = mapped_column(String(20), server_default="vci")
    icb_code:    Mapped[str | None] = mapped_column(String(10))

    # Cross-industry
    net_revenue:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    operating_profit:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    ebt:                  Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_profit:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_profit_parent:    Mapped[float | None] = mapped_column(Numeric(20, 2))
    minority_interest_is: Mapped[float | None] = mapped_column(Numeric(20, 2))
    eps_basic:            Mapped[float | None] = mapped_column(Numeric(15, 2))
    eps_diluted:          Mapped[float | None] = mapped_column(Numeric(20, 4))

    # Non-financial
    gross_revenue:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    revenue_deductions:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    cost_of_goods_sold:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    gross_profit:         Mapped[float | None] = mapped_column(Numeric(20, 2))
    financial_income:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    financial_expenses:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    selling_expenses:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    admin_expenses:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    interest_expense:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    income_tax:           Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Banking
    interest_income:                 Mapped[float | None] = mapped_column(Numeric(20, 2))
    fee_and_commission_income:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    forex_trading_income:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    trading_securities_income:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    investment_securities_income:    Mapped[float | None] = mapped_column(Numeric(20, 2))
    other_income:                    Mapped[float | None] = mapped_column(Numeric(20, 2))
    total_operating_income:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    operating_expenses:              Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_interest_income:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    pre_provision_profit:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    credit_provision_expense:        Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Insurance
    net_insurance_premium:          Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_insurance_claims:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    insurance_acquisition_costs:    Mapped[float | None] = mapped_column(Numeric(20, 2))

    # Securities
    brokerage_revenue: Mapped[float | None] = mapped_column(Numeric(20, 2))
    advisory_revenue:  Mapped[float | None] = mapped_column(Numeric(20, 2))

    raw_details: Mapped[dict]     = mapped_column(JSONB, server_default="{}")
    fetched_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FinCashFlow(Base):
    """Lưu chuyển tiền tệ — Approach C."""
    __tablename__ = "fin_cash_flow"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str]           = mapped_column(String(10), nullable=False)
    period_type: Mapped[str]           = mapped_column(String(10), nullable=False)
    template:    Mapped[str]           = mapped_column(String(20), nullable=False)
    source:      Mapped[str]           = mapped_column(String(20), server_default="vci")
    icb_code:    Mapped[str | None] = mapped_column(String(10))

    cf_ebt:                    Mapped[float | None] = mapped_column(Numeric(20, 2))
    depreciation_amortization: Mapped[float | None] = mapped_column(Numeric(20, 2))
    cf_interest_expense:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    change_in_receivables:     Mapped[float | None] = mapped_column(Numeric(20, 2))
    change_in_inventory:       Mapped[float | None] = mapped_column(Numeric(20, 2))
    change_in_payables:        Mapped[float | None] = mapped_column(Numeric(20, 2))
    cfo:                       Mapped[float | None] = mapped_column(Numeric(20, 2))
    capex:                     Mapped[float | None] = mapped_column(Numeric(20, 2))
    asset_disposal_proceeds:   Mapped[float | None] = mapped_column(Numeric(20, 2))
    cfi:                       Mapped[float | None] = mapped_column(Numeric(20, 2))
    debt_proceeds:             Mapped[float | None] = mapped_column(Numeric(20, 2))
    debt_repayment:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    dividends_paid:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    cff:                       Mapped[float | None] = mapped_column(Numeric(20, 2))
    net_cash_change:           Mapped[float | None] = mapped_column(Numeric(20, 2))
    cash_beginning:            Mapped[float | None] = mapped_column(Numeric(20, 2))
    cash_ending:               Mapped[float | None] = mapped_column(Numeric(20, 2))

    raw_details: Mapped[dict]     = mapped_column(JSONB, server_default="{}")
    fetched_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FinFinancialRatios(Base):
    """Chỉ số tài chính lịch sử (ratio API) — Approach C."""
    __tablename__ = "fin_financial_ratios"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str]           = mapped_column(String(10), nullable=False)
    period_type: Mapped[str]           = mapped_column(String(10), nullable=False)
    template:    Mapped[str]           = mapped_column(String(20), nullable=False)
    source:      Mapped[str]           = mapped_column(String(20), server_default="vci")
    icb_code:    Mapped[str | None] = mapped_column(String(10))

    # Market data
    shares_outstanding_millions: Mapped[int | None]   = mapped_column(BigInteger)
    market_cap:                  Mapped[float | None] = mapped_column(Numeric(22, 2))
    dividend_yield:              Mapped[float | None] = mapped_column(Numeric(8, 4))

    # Valuation
    pe_ratio:    Mapped[float | None] = mapped_column(Numeric(12, 4))
    pb_ratio:    Mapped[float | None] = mapped_column(Numeric(12, 4))
    ps_ratio:    Mapped[float | None] = mapped_column(Numeric(12, 4))
    price_to_cf: Mapped[float | None] = mapped_column(Numeric(12, 4))
    ev_to_ebitda: Mapped[float | None] = mapped_column(Numeric(12, 4))

    # Liquidity
    cash_ratio:    Mapped[float | None] = mapped_column(Numeric(10, 4))
    quick_ratio:   Mapped[float | None] = mapped_column(Numeric(10, 4))
    current_ratio: Mapped[float | None] = mapped_column(Numeric(10, 4))

    # Leverage
    debt_to_equity:     Mapped[float | None] = mapped_column(Numeric(10, 4))
    financial_leverage: Mapped[float | None] = mapped_column(Numeric(10, 4))

    # Profitability (decimal: 0.2763 = 27.63%)
    roe:          Mapped[float | None] = mapped_column(Numeric(8, 4))
    roa:          Mapped[float | None] = mapped_column(Numeric(8, 4))
    roic:         Mapped[float | None] = mapped_column(Numeric(8, 4))
    gross_margin: Mapped[float | None] = mapped_column(Numeric(8, 4))
    ebit_margin:  Mapped[float | None] = mapped_column(Numeric(8, 4))
    pre_tax_margin: Mapped[float | None] = mapped_column(Numeric(8, 4))
    net_margin:   Mapped[float | None] = mapped_column(Numeric(8, 4))

    # Activity
    asset_turnover:       Mapped[float | None] = mapped_column(Numeric(10, 4))
    fixed_asset_turnover: Mapped[float | None] = mapped_column(Numeric(10, 4))
    days_receivable:      Mapped[float | None] = mapped_column(Numeric(10, 2))
    days_inventory:       Mapped[float | None] = mapped_column(Numeric(10, 2))
    days_payable:         Mapped[float | None] = mapped_column(Numeric(10, 2))
    cash_cycle:           Mapped[float | None] = mapped_column(Numeric(10, 2))

    # Absolute values
    ebit:   Mapped[float | None] = mapped_column(Numeric(22, 2))
    ebitda: Mapped[float | None] = mapped_column(Numeric(22, 2))

    # Banking-specific (NULL cho non-financial/securities/insurance)
    nim:                      Mapped[float | None] = mapped_column(Numeric(8, 4))
    avg_earning_asset_yield:  Mapped[float | None] = mapped_column(Numeric(8, 4))
    avg_cost_of_funds:        Mapped[float | None] = mapped_column(Numeric(8, 4))
    non_interest_income_ratio: Mapped[float | None] = mapped_column(Numeric(8, 4))
    cir:                      Mapped[float | None] = mapped_column(Numeric(8, 4))
    car:                      Mapped[float | None] = mapped_column(Numeric(8, 4))
    ldr:                      Mapped[float | None] = mapped_column(Numeric(8, 4))
    npl_ratio:                Mapped[float | None] = mapped_column(Numeric(8, 4))
    npl_coverage:             Mapped[float | None] = mapped_column(Numeric(8, 4))
    provision_to_loans:       Mapped[float | None] = mapped_column(Numeric(8, 4))
    loan_growth:              Mapped[float | None] = mapped_column(Numeric(8, 4))
    deposit_growth:           Mapped[float | None] = mapped_column(Numeric(8, 4))
    equity_to_assets:         Mapped[float | None] = mapped_column(Numeric(8, 4))
    casa_ratio:               Mapped[float | None] = mapped_column(Numeric(8, 4))

    raw_details: Mapped[dict]     = mapped_column(JSONB, server_default="{}")
    fetched_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# 4. BẢNG THÔNG TIN DOANH NGHIỆP (Company Intelligence)
# ══════════════════════════════════════════════════════════════════════════════

class Shareholder(Base):
    """Cổ đông lớn."""
    __tablename__ = "shareholders"
    __table_args__ = (UniqueConstraint("symbol", "share_holder", "snapshot_date"),)

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:            Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    share_holder:      Mapped[str]           = mapped_column(String(500), nullable=False)
    quantity:          Mapped[int | None] = mapped_column(BigInteger)
    share_own_percent: Mapped[float | None] = mapped_column(Numeric(8, 4))
    update_date:       Mapped[date | None]  = mapped_column(Date)
    snapshot_date:     Mapped[date]            = mapped_column(Date, nullable=False)


class Officer(Base):
    """Ban lãnh đạo và thành viên HĐQT."""
    __tablename__ = "officers"
    __table_args__ = (UniqueConstraint("symbol", "officer_name", "status", "snapshot_date"),)

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:              Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    officer_name:        Mapped[str]           = mapped_column(String(300), nullable=False)
    officer_position:    Mapped[str | None] = mapped_column(String(300))
    position_short_name: Mapped[str | None] = mapped_column(String(100))
    officer_own_percent: Mapped[float | None] = mapped_column(Numeric(8, 4))
    quantity:            Mapped[int | None]   = mapped_column(BigInteger)
    update_date:         Mapped[date | None]  = mapped_column(Date)
    status:              Mapped[str]             = mapped_column(String(20), server_default="working")
    snapshot_date:       Mapped[date]            = mapped_column(Date, nullable=False)


class Subsidiary(Base):
    """Công ty con và công ty liên kết."""
    __tablename__ = "subsidiaries"
    __table_args__ = (UniqueConstraint("symbol", "organ_name", "snapshot_date"),)

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:            Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    sub_organ_code:    Mapped[str | None] = mapped_column(String(20))
    organ_name:        Mapped[str]           = mapped_column(String(500), nullable=False)
    ownership_percent: Mapped[float | None] = mapped_column(Numeric(8, 4))
    type:              Mapped[str | None]   = mapped_column(String(50))
    snapshot_date:     Mapped[date]            = mapped_column(Date, nullable=False)


class CorporateEvent(Base):
    """Sự kiện doanh nghiệp: cổ tức, phát hành thêm, tách cổ phiếu..."""
    __tablename__ = "corporate_events"
    __table_args__ = (UniqueConstraint("symbol", "event_list_code", "record_date"),)

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:          Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    event_title:     Mapped[str | None] = mapped_column(String(500))
    event_list_code: Mapped[str | None] = mapped_column(String(20))
    event_list_name: Mapped[str | None] = mapped_column(String(300))
    public_date:     Mapped[date | None] = mapped_column(Date)
    issue_date:      Mapped[date | None] = mapped_column(Date)
    record_date:     Mapped[date | None] = mapped_column(Date)
    exright_date:    Mapped[date | None] = mapped_column(Date)
    ratio:           Mapped[float | None] = mapped_column(Numeric(15, 6))
    value:           Mapped[float | None] = mapped_column(Numeric(20, 4))
    source_url:      Mapped[str | None]   = mapped_column(Text)
    fetched_at:      Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


class RatioSummary(Base):
    """Snapshot tài chính mới nhất — dùng cho stock screener."""
    __tablename__ = "ratio_summary"
    __table_args__ = (UniqueConstraint("symbol", "year_report", "quarter_report"),)

    id:                    Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:                Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    year_report:           Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    quarter_report:        Mapped[int | None] = mapped_column(SmallInteger)
    revenue:               Mapped[int | None]   = mapped_column(BigInteger)
    revenue_growth:        Mapped[float | None] = mapped_column(Numeric(10, 4))
    net_profit:            Mapped[int | None]   = mapped_column(BigInteger)
    net_profit_growth:     Mapped[float | None] = mapped_column(Numeric(10, 4))
    ebit_margin:           Mapped[float | None] = mapped_column(Numeric(10, 4))
    roe:                   Mapped[float | None] = mapped_column(Numeric(10, 4))
    roa:                   Mapped[float | None] = mapped_column(Numeric(10, 4))
    roic:                  Mapped[float | None] = mapped_column(Numeric(10, 4))
    pe:                    Mapped[float | None] = mapped_column(Numeric(10, 4))
    pb:                    Mapped[float | None] = mapped_column(Numeric(10, 4))
    ps:                    Mapped[float | None] = mapped_column(Numeric(10, 4))
    pcf:                   Mapped[float | None] = mapped_column(Numeric(10, 4))
    eps:                   Mapped[float | None] = mapped_column(Numeric(15, 2))
    eps_ttm:               Mapped[float | None] = mapped_column(Numeric(15, 2))
    bvps:                  Mapped[float | None] = mapped_column(Numeric(15, 2))
    current_ratio:         Mapped[float | None] = mapped_column(Numeric(10, 4))
    quick_ratio:           Mapped[float | None] = mapped_column(Numeric(10, 4))
    cash_ratio:            Mapped[float | None] = mapped_column(Numeric(10, 4))
    interest_coverage:     Mapped[float | None] = mapped_column(Numeric(10, 4))
    debt_to_equity:        Mapped[float | None] = mapped_column(Numeric(10, 4))
    net_profit_margin:     Mapped[float | None] = mapped_column(Numeric(10, 4))
    gross_margin:          Mapped[float | None] = mapped_column(Numeric(10, 4))
    ev:                    Mapped[int | None]   = mapped_column(BigInteger)
    ev_ebitda:             Mapped[float | None] = mapped_column(Numeric(10, 4))
    ebitda:                Mapped[int | None]   = mapped_column(BigInteger)
    ebit:                  Mapped[int | None]   = mapped_column(BigInteger)
    asset_turnover:        Mapped[float | None] = mapped_column(Numeric(10, 4))
    fixed_asset_turnover:  Mapped[float | None] = mapped_column(Numeric(10, 4))
    receivable_days:       Mapped[float | None] = mapped_column(Numeric(10, 2))
    inventory_days:        Mapped[float | None] = mapped_column(Numeric(10, 2))
    payable_days:          Mapped[float | None] = mapped_column(Numeric(10, 2))
    cash_conversion_cycle: Mapped[float | None] = mapped_column(Numeric(10, 2))
    dividend:              Mapped[float | None] = mapped_column(Numeric(15, 2))
    issue_share:           Mapped[int | None]   = mapped_column(BigInteger)
    charter_capital:       Mapped[int | None]   = mapped_column(BigInteger)
    extra_metrics:         Mapped[dict | None]  = mapped_column(JSONB)
    fetched_at:            Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# 4. BẢNG VẬN HÀNH PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

class PipelineLog(Base):
    """Nhật ký chạy ETL pipeline."""
    __tablename__ = "pipeline_logs"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name:         Mapped[str]           = mapped_column(String(100), nullable=False)
    symbol:           Mapped[str | None] = mapped_column(String(10))
    status:           Mapped[str]           = mapped_column(String(20), nullable=False)
    records_fetched:  Mapped[int]           = mapped_column(Integer, server_default="0")
    records_inserted: Mapped[int]           = mapped_column(Integer, server_default="0")
    error_message:    Mapped[str | None] = mapped_column(Text)
    started_at:       Mapped[datetime]      = mapped_column(DateTime, nullable=False, server_default=func.now())
    finished_at:      Mapped[datetime | None] = mapped_column(DateTime)
    # duration_ms là GENERATED ALWAYS AS column — chỉ đọc, không ghi
    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        Computed(
            "EXTRACT(MILLISECONDS FROM finished_at - started_at)::INTEGER",
            persisted=True,
        ),
    )
