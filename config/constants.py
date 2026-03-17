"""Hằng số dùng chung trong toàn bộ pipeline."""

# ── Nguồn dữ liệu ─────────────────────────────────────────────────────────────
VALID_SOURCES = ["vci", "kbs", "vnd", "mas", "cafef", "spl"]

# ── Sàn giao dịch ─────────────────────────────────────────────────────────────
VALID_EXCHANGES = ["HOSE", "HNX", "UPCOM"]

# ── Loại chứng khoán ──────────────────────────────────────────────────────────
VALID_SECURITY_TYPES = ["STOCK", "ETF", "BOND", "CW", "FUND"]

# ── Trạng thái niêm yết ───────────────────────────────────────────────────────
VALID_STATUSES = ["listed", "delisted", "suspended"]

# ── Interval giá ──────────────────────────────────────────────────────────────
VALID_INTERVALS = ["1D", "1W", "1M", "1", "5", "15", "30", "60"]

# ── Kỳ báo cáo ───────────────────────────────────────────────────────────────
VALID_PERIOD_TYPES = ["year", "quarter"]

# ── Loại báo cáo tài chính ────────────────────────────────────────────────────
FINANCIAL_REPORT_TYPES = ["balance_sheet", "income_statement", "cash_flow", "ratio"]

# ── Tên các job ETL ───────────────────────────────────────────────────────────
JOB_SYNC_LISTING    = "sync_listing"
JOB_SYNC_FINANCIALS = "sync_financials"
JOB_SYNC_COMPANY    = "sync_company"
JOB_SYNC_RATIOS     = "sync_ratios"
JOB_BACKFILL        = "backfill"

ALL_JOBS = [
    JOB_SYNC_LISTING,
    JOB_SYNC_FINANCIALS,
    JOB_SYNC_COMPANY,
    JOB_SYNC_RATIOS,
    JOB_BACKFILL,
]

# ── Cột conflict key cho từng bảng (dùng cho ON CONFLICT) ─────────────────────
CONFLICT_KEYS: dict[str, list[str]] = {
    "icb_industries":    ["icb_code"],
    "companies":         ["symbol"],
    "balance_sheets":    ["symbol", "period", "period_type"],
    "income_statements": ["symbol", "period", "period_type"],
    "cash_flows":        ["symbol", "period", "period_type"],
    "financial_ratios":  ["symbol", "period", "period_type"],
    "ratio_summary":     ["symbol", "year_report", "quarter_report"],
    "shareholders":      ["symbol", "share_holder", "snapshot_date"],
    "officers":          ["symbol", "officer_name", "status", "snapshot_date"],
    "subsidiaries":      ["symbol", "organ_name", "snapshot_date"],
    "corporate_events":  ["symbol", "event_list_code", "record_date"],
}

# ── Cột do server tự sinh, không được ghi vào INSERT/UPDATE ───────────────────
SERVER_GENERATED_COLS = {"id", "duration_ms", "created_at"}
