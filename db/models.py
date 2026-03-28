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
    definition:   Mapped[Optional[str]] = mapped_column(Text)
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
    history:          Mapped[Optional[str]]      = mapped_column(Text)
    company_profile:  Mapped[Optional[str]]      = mapped_column(Text)
    created_at:       Mapped[datetime]           = mapped_column(DateTime, server_default=func.now())
    updated_at:       Mapped[datetime]           = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ══════════════════════════════════════════════════════════════════════════════
# 2. BẢNG BÁO CÁO TÀI CHÍNH THỐNG NHẤT
# ══════════════════════════════════════════════════════════════════════════════

class FinancialReport(Base):
    """
    Bảng tài chính thống nhất cho 4 mẫu biểu × 3 loại báo cáo.

    Thay thế các bảng cũ: balance_sheets, income_statements, cash_flows, financial_ratios.
    Discriminator: statement_type + template.
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
    cash_and_equivalents:     Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    total_current_assets:     Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    total_non_current_assets: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    total_assets:             Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    total_liabilities:        Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    total_equity:             Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    charter_capital:          Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    short_term_debt:          Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    long_term_debt:           Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    retained_earnings:        Mapped[Optional[float]] = mapped_column(Numeric(20, 2))

    # ── Tài sản — Phi tài chính (NULL với Banking/Insurance) ──────
    inventory_net:            Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    inventory_gross:          Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    short_term_receivables:   Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    ppe_net:                  Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    ppe_gross:                Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    accumulated_depreciation: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    construction_in_progress: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))

    # ── Tài sản — Ngân hàng (NULL với Non-Financial) ──────────────
    customer_loans_gross:  Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    loan_loss_reserve:     Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    customer_deposits:     Mapped[Optional[float]] = mapped_column(Numeric(20, 2))

    # ── KQKD — Cross-Industry Core ────────────────────────────────
    net_revenue:       Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    operating_profit:  Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    ebt:               Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    net_profit:        Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    net_profit_parent: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    eps_basic:         Mapped[Optional[float]] = mapped_column(Numeric(15, 2))

    # ── KQKD — Phi tài chính (NULL với Banking/Insurance) ─────────
    gross_revenue:        Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    cost_of_goods_sold:   Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    gross_profit:         Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    selling_expenses:     Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    admin_expenses:       Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    interest_expense:     Mapped[Optional[float]] = mapped_column(Numeric(20, 2))

    # ── KQKD — Ngân hàng (NULL với Non-Financial) ─────────────────
    net_interest_income:      Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    credit_provision_expense: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))

    # ── LCTT — Core (tất cả template) ─────────────────────────────
    cfo:            Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    cfi:            Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    cff:            Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    capex:          Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    net_cash_change: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    cash_beginning: Mapped[Optional[float]] = mapped_column(Numeric(20, 2))
    cash_ending:    Mapped[Optional[float]] = mapped_column(Numeric(20, 2))

    # ── Lưu trữ thô ───────────────────────────────────────────────
    raw_details: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    # ── Audit ─────────────────────────────────────────────────────
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


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
    )
