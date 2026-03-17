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
    en_icb_name:  Mapped[Optional[str]] = mapped_column(String(300))
    level:        Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    parent_code:  Mapped[Optional[str]] = mapped_column(
        String(10), ForeignKey("icb_industries.icb_code")
    )
    created_at:   Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())


class Company(Base):
    """Danh mục toàn bộ chứng khoán niêm yết."""
    __tablename__ = "companies"

    symbol:           Mapped[str]           = mapped_column(String(10), primary_key=True)
    company_name:     Mapped[str]           = mapped_column(String(500), nullable=False)
    company_name_eng: Mapped[Optional[str]] = mapped_column(String(500))
    short_name:       Mapped[Optional[str]] = mapped_column(String(200))
    exchange:         Mapped[str]           = mapped_column(String(20), nullable=False)
    type:             Mapped[str]           = mapped_column(String(30), nullable=False)
    status:           Mapped[str]           = mapped_column(String(20), server_default="listed")
    icb_code:         Mapped[Optional[str]] = mapped_column(
        String(10), ForeignKey("icb_industries.icb_code")
    )
    listed_date:      Mapped[Optional[date]]     = mapped_column(Date)
    delisted_date:    Mapped[Optional[date]]     = mapped_column(Date)
    charter_capital:  Mapped[Optional[int]]      = mapped_column(BigInteger)
    issue_share:      Mapped[Optional[int]]      = mapped_column(BigInteger)
    company_id:       Mapped[Optional[int]]      = mapped_column(Integer)
    isin:             Mapped[Optional[str]]      = mapped_column(String(20))
    tax_code:         Mapped[Optional[str]]      = mapped_column(String(20))
    created_at:       Mapped[datetime]           = mapped_column(DateTime, server_default=func.now())
    updated_at:       Mapped[datetime]           = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. BẢNG BÁO CÁO TÀI CHÍNH (Financial Statements)
# ══════════════════════════════════════════════════════════════════════════════

class BalanceSheet(Base):
    """Bảng cân đối kế toán."""
    __tablename__ = "balance_sheets"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str] = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str] = mapped_column(String(10), nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Tài sản ngắn hạn
    cash_and_equivalents:   Mapped[Optional[int]] = mapped_column(BigInteger)
    short_term_investments: Mapped[Optional[int]] = mapped_column(BigInteger)
    accounts_receivable:    Mapped[Optional[int]] = mapped_column(BigInteger)
    inventory:              Mapped[Optional[int]] = mapped_column(BigInteger)
    other_current_assets:   Mapped[Optional[int]] = mapped_column(BigInteger)
    total_current_assets:   Mapped[Optional[int]] = mapped_column(BigInteger)

    # Tài sản dài hạn
    long_term_receivables:  Mapped[Optional[int]] = mapped_column(BigInteger)
    fixed_assets:           Mapped[Optional[int]] = mapped_column(BigInteger)
    investment_properties:  Mapped[Optional[int]] = mapped_column(BigInteger)
    long_term_investments:  Mapped[Optional[int]] = mapped_column(BigInteger)
    intangible_assets:      Mapped[Optional[int]] = mapped_column(BigInteger)
    other_long_term_assets: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_long_term_assets: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_assets:           Mapped[Optional[int]] = mapped_column(BigInteger)

    # Nợ ngắn hạn
    short_term_debt:           Mapped[Optional[int]] = mapped_column(BigInteger)
    accounts_payable:          Mapped[Optional[int]] = mapped_column(BigInteger)
    advances_from_customers:   Mapped[Optional[int]] = mapped_column(BigInteger)
    other_current_liabilities: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_current_liabilities: Mapped[Optional[int]] = mapped_column(BigInteger)

    # Nợ dài hạn
    long_term_debt:              Mapped[Optional[int]] = mapped_column(BigInteger)
    other_long_term_liabilities: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_long_term_liabilities: Mapped[Optional[int]] = mapped_column(BigInteger)
    total_liabilities:           Mapped[Optional[int]] = mapped_column(BigInteger)

    # Vốn chủ sở hữu
    charter_capital_fs:     Mapped[Optional[int]] = mapped_column(BigInteger)
    share_premium:          Mapped[Optional[int]] = mapped_column(BigInteger)
    retained_earnings:      Mapped[Optional[int]] = mapped_column(BigInteger)
    other_equity:           Mapped[Optional[int]] = mapped_column(BigInteger)
    minority_interest:      Mapped[Optional[int]] = mapped_column(BigInteger)
    total_equity:           Mapped[Optional[int]] = mapped_column(BigInteger)
    total_liabilities_equity: Mapped[Optional[int]] = mapped_column(BigInteger)

    raw_data:   Mapped[Optional[dict]] = mapped_column(JSONB)
    source:     Mapped[Optional[str]]  = mapped_column(String(20), server_default="vci")
    fetched_at: Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())


class IncomeStatement(Base):
    """Báo cáo kết quả kinh doanh."""
    __tablename__ = "income_statements"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str] = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str] = mapped_column(String(10), nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Doanh thu
    gross_revenue:      Mapped[Optional[int]] = mapped_column(BigInteger)
    revenue_deductions: Mapped[Optional[int]] = mapped_column(BigInteger)
    net_revenue:        Mapped[Optional[int]] = mapped_column(BigInteger)

    # Chi phí & lợi nhuận
    cogs:                   Mapped[Optional[int]] = mapped_column(BigInteger)
    gross_profit:           Mapped[Optional[int]] = mapped_column(BigInteger)
    financial_income:       Mapped[Optional[int]] = mapped_column(BigInteger)
    financial_expense:      Mapped[Optional[int]] = mapped_column(BigInteger)
    interest_expense:       Mapped[Optional[int]] = mapped_column(BigInteger)
    selling_expense:        Mapped[Optional[int]] = mapped_column(BigInteger)
    admin_expense:          Mapped[Optional[int]] = mapped_column(BigInteger)
    operating_profit:       Mapped[Optional[int]] = mapped_column(BigInteger)
    other_income:           Mapped[Optional[int]] = mapped_column(BigInteger)
    other_expense:          Mapped[Optional[int]] = mapped_column(BigInteger)
    profit_from_associates: Mapped[Optional[int]] = mapped_column(BigInteger)
    ebt:                    Mapped[Optional[int]] = mapped_column(BigInteger)
    income_tax:             Mapped[Optional[int]] = mapped_column(BigInteger)
    profit_after_tax:       Mapped[Optional[int]] = mapped_column(BigInteger)
    minority_profit:        Mapped[Optional[int]] = mapped_column(BigInteger)
    net_profit:             Mapped[Optional[int]] = mapped_column(BigInteger)

    # Cổ phiếu
    eps_basic:          Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    eps_diluted:        Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    shares_outstanding: Mapped[Optional[int]]   = mapped_column(BigInteger)

    raw_data:   Mapped[Optional[dict]] = mapped_column(JSONB)
    source:     Mapped[Optional[str]]  = mapped_column(String(20), server_default="vci")
    fetched_at: Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())


class CashFlow(Base):
    """Báo cáo lưu chuyển tiền tệ."""
    __tablename__ = "cash_flows"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str] = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str] = mapped_column(String(10), nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Hoạt động kinh doanh
    net_profit_before_tax:     Mapped[Optional[int]] = mapped_column(BigInteger)
    depreciation:              Mapped[Optional[int]] = mapped_column(BigInteger)
    provision:                 Mapped[Optional[int]] = mapped_column(BigInteger)
    unrealized_fx_gain_loss:   Mapped[Optional[int]] = mapped_column(BigInteger)
    investment_income:         Mapped[Optional[int]] = mapped_column(BigInteger)
    interest_expense_cf:       Mapped[Optional[int]] = mapped_column(BigInteger)
    change_in_receivables:     Mapped[Optional[int]] = mapped_column(BigInteger)
    change_in_inventory:       Mapped[Optional[int]] = mapped_column(BigInteger)
    change_in_payables:        Mapped[Optional[int]] = mapped_column(BigInteger)
    other_operating_changes:   Mapped[Optional[int]] = mapped_column(BigInteger)
    income_tax_paid:           Mapped[Optional[int]] = mapped_column(BigInteger)
    operating_cash_flow:       Mapped[Optional[int]] = mapped_column(BigInteger)

    # Hoạt động đầu tư
    capex:                           Mapped[Optional[int]] = mapped_column(BigInteger)
    proceeds_from_asset_disposal:    Mapped[Optional[int]] = mapped_column(BigInteger)
    investment_purchases:            Mapped[Optional[int]] = mapped_column(BigInteger)
    investment_proceeds:             Mapped[Optional[int]] = mapped_column(BigInteger)
    interest_and_dividends_received: Mapped[Optional[int]] = mapped_column(BigInteger)
    investing_cash_flow:             Mapped[Optional[int]] = mapped_column(BigInteger)

    # Hoạt động tài chính
    proceeds_from_borrowings:      Mapped[Optional[int]] = mapped_column(BigInteger)
    repayment_of_borrowings:       Mapped[Optional[int]] = mapped_column(BigInteger)
    proceeds_from_equity_issuance: Mapped[Optional[int]] = mapped_column(BigInteger)
    dividends_paid:                Mapped[Optional[int]] = mapped_column(BigInteger)
    financing_cash_flow:           Mapped[Optional[int]] = mapped_column(BigInteger)

    net_cash_change: Mapped[Optional[int]] = mapped_column(BigInteger)
    beginning_cash:  Mapped[Optional[int]] = mapped_column(BigInteger)
    ending_cash:     Mapped[Optional[int]] = mapped_column(BigInteger)

    raw_data:   Mapped[Optional[dict]] = mapped_column(JSONB)
    source:     Mapped[Optional[str]]  = mapped_column(String(20), server_default="vci")
    fetched_at: Mapped[datetime]       = mapped_column(DateTime, server_default=func.now())


class FinancialRatio(Base):
    """Chỉ số tài chính tổng hợp."""
    __tablename__ = "financial_ratios"
    __table_args__ = (UniqueConstraint("symbol", "period", "period_type"),)

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:      Mapped[str] = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    period:      Mapped[str] = mapped_column(String(10), nullable=False)
    period_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Định giá
    pe:       Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    pb:       Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    ps:       Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    pcf:      Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    ev_ebitda: Mapped[Optional[float]] = mapped_column(Numeric(12, 4))
    ev:       Mapped[Optional[int]]   = mapped_column(BigInteger)

    # Khả năng sinh lời
    roe:              Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    roa:              Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    roic:             Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    gross_margin:     Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ebit_margin:      Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    net_profit_margin: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ebitda:           Mapped[Optional[int]]   = mapped_column(BigInteger)
    ebit:             Mapped[Optional[int]]   = mapped_column(BigInteger)

    # Thanh khoản
    current_ratio:    Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    quick_ratio:      Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    cash_ratio:       Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    interest_coverage: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))

    # Đòn bẩy
    debt_to_equity:   Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    debt_to_assets:   Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    financial_leverage: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))

    # Hiệu quả hoạt động
    asset_turnover:       Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    fixed_asset_turnover: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    inventory_days:       Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    receivable_days:      Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    payable_days:         Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    cash_conversion_cycle: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))

    # Cổ phiếu
    eps:      Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    eps_ttm:  Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    bvps:     Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    dividend: Mapped[Optional[float]] = mapped_column(Numeric(15, 2))

    # Chỉ số ngành ngân hàng
    npl_ratio: Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    car:       Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ldr:       Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    nim:       Mapped[Optional[float]] = mapped_column(Numeric(10, 4))

    source:     Mapped[Optional[str]] = mapped_column(String(20), server_default="vci")
    fetched_at: Mapped[datetime]      = mapped_column(DateTime, server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# 3. BẢNG THÔNG TIN DOANH NGHIỆP (Company Intelligence)
# ══════════════════════════════════════════════════════════════════════════════

class Shareholder(Base):
    """Cổ đông lớn."""
    __tablename__ = "shareholders"
    __table_args__ = (UniqueConstraint("symbol", "share_holder", "snapshot_date"),)

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:            Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    share_holder:      Mapped[str]           = mapped_column(String(500), nullable=False)
    quantity:          Mapped[Optional[int]] = mapped_column(BigInteger)
    share_own_percent: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    update_date:       Mapped[Optional[date]]  = mapped_column(Date)
    snapshot_date:     Mapped[date]            = mapped_column(Date, nullable=False)


class Officer(Base):
    """Ban lãnh đạo và thành viên HĐQT."""
    __tablename__ = "officers"
    __table_args__ = (UniqueConstraint("symbol", "officer_name", "status", "snapshot_date"),)

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:              Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    officer_name:        Mapped[str]           = mapped_column(String(300), nullable=False)
    officer_position:    Mapped[Optional[str]] = mapped_column(String(300))
    position_short_name: Mapped[Optional[str]] = mapped_column(String(100))
    officer_own_percent: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    quantity:            Mapped[Optional[int]]   = mapped_column(BigInteger)
    update_date:         Mapped[Optional[date]]  = mapped_column(Date)
    status:              Mapped[str]             = mapped_column(String(20), server_default="working")
    snapshot_date:       Mapped[date]            = mapped_column(Date, nullable=False)


class Subsidiary(Base):
    """Công ty con và công ty liên kết."""
    __tablename__ = "subsidiaries"
    __table_args__ = (UniqueConstraint("symbol", "organ_name", "snapshot_date"),)

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:            Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    sub_organ_code:    Mapped[Optional[str]] = mapped_column(String(20))
    organ_name:        Mapped[str]           = mapped_column(String(500), nullable=False)
    ownership_percent: Mapped[Optional[float]] = mapped_column(Numeric(8, 4))
    type:              Mapped[Optional[str]]   = mapped_column(String(50))
    snapshot_date:     Mapped[date]            = mapped_column(Date, nullable=False)


class CorporateEvent(Base):
    """Sự kiện doanh nghiệp: cổ tức, phát hành thêm, tách cổ phiếu..."""
    __tablename__ = "corporate_events"
    __table_args__ = (UniqueConstraint("symbol", "event_list_code", "record_date"),)

    id:              Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:          Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    event_title:     Mapped[Optional[str]] = mapped_column(String(500))
    event_list_code: Mapped[Optional[str]] = mapped_column(String(20))
    event_list_name: Mapped[Optional[str]] = mapped_column(String(300))
    public_date:     Mapped[Optional[date]] = mapped_column(Date)
    issue_date:      Mapped[Optional[date]] = mapped_column(Date)
    record_date:     Mapped[Optional[date]] = mapped_column(Date)
    exright_date:    Mapped[Optional[date]] = mapped_column(Date)
    ratio:           Mapped[Optional[float]] = mapped_column(Numeric(15, 6))
    value:           Mapped[Optional[float]] = mapped_column(Numeric(20, 4))
    source_url:      Mapped[Optional[str]]   = mapped_column(Text)
    fetched_at:      Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


class RatioSummary(Base):
    """Snapshot tài chính mới nhất — dùng cho stock screener."""
    __tablename__ = "ratio_summary"
    __table_args__ = (UniqueConstraint("symbol", "year_report", "quarter_report"),)

    id:                    Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol:                Mapped[str]           = mapped_column(String(10), ForeignKey("companies.symbol"), nullable=False)
    year_report:           Mapped[int]           = mapped_column(SmallInteger, nullable=False)
    quarter_report:        Mapped[Optional[int]] = mapped_column(SmallInteger)
    revenue:               Mapped[Optional[int]]   = mapped_column(BigInteger)
    revenue_growth:        Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    net_profit:            Mapped[Optional[int]]   = mapped_column(BigInteger)
    net_profit_growth:     Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ebit_margin:           Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    roe:                   Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    roa:                   Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    roic:                  Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    pe:                    Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    pb:                    Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ps:                    Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    pcf:                   Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    eps:                   Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    eps_ttm:               Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    bvps:                  Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    current_ratio:         Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    quick_ratio:           Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    cash_ratio:            Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    interest_coverage:     Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    debt_to_equity:        Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    net_profit_margin:     Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    gross_margin:          Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ev:                    Mapped[Optional[int]]   = mapped_column(BigInteger)
    ev_ebitda:             Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    ebitda:                Mapped[Optional[int]]   = mapped_column(BigInteger)
    ebit:                  Mapped[Optional[int]]   = mapped_column(BigInteger)
    asset_turnover:        Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    fixed_asset_turnover:  Mapped[Optional[float]] = mapped_column(Numeric(10, 4))
    receivable_days:       Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    inventory_days:        Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    payable_days:          Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    cash_conversion_cycle: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    dividend:              Mapped[Optional[float]] = mapped_column(Numeric(15, 2))
    issue_share:           Mapped[Optional[int]]   = mapped_column(BigInteger)
    charter_capital:       Mapped[Optional[int]]   = mapped_column(BigInteger)
    extra_metrics:         Mapped[Optional[dict]]  = mapped_column(JSONB)
    fetched_at:            Mapped[datetime]        = mapped_column(DateTime, server_default=func.now())


# ══════════════════════════════════════════════════════════════════════════════
# 4. BẢNG VẬN HÀNH PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

class PipelineLog(Base):
    """Nhật ký chạy ETL pipeline."""
    __tablename__ = "pipeline_logs"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_name:         Mapped[str]           = mapped_column(String(100), nullable=False)
    symbol:           Mapped[Optional[str]] = mapped_column(String(10))
    status:           Mapped[str]           = mapped_column(String(20), nullable=False)
    records_fetched:  Mapped[int]           = mapped_column(Integer, server_default="0")
    records_inserted: Mapped[int]           = mapped_column(Integer, server_default="0")
    error_message:    Mapped[Optional[str]] = mapped_column(Text)
    started_at:       Mapped[datetime]      = mapped_column(DateTime, nullable=False, server_default=func.now())
    finished_at:      Mapped[Optional[datetime]] = mapped_column(DateTime)
    # duration_ms là GENERATED ALWAYS AS column — chỉ đọc, không ghi
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        Computed(
            "EXTRACT(MILLISECONDS FROM finished_at - started_at)::INTEGER",
            persisted=True,
        ),
        init=False,
    )
