-- ============================================================
-- Migration 006: Bảng data quality flags
-- Ghi lại khi VCI và KBS báo cáo số liệu BCTC khác nhau > 2%
-- Dùng bởi FinanceCrossValidator (etl/validators/cross_source.py)
-- ============================================================

CREATE TABLE IF NOT EXISTS data_quality_flags (
    id           SERIAL       PRIMARY KEY,
    symbol       VARCHAR(10)  NOT NULL,
    table_name   VARCHAR(50)  NOT NULL,   -- balance_sheets / income_statements / cash_flows
    period       VARCHAR(10)  NOT NULL,   -- Năm: '2023', hoặc quý: '2023-Q3'
    column_name  VARCHAR(100) NOT NULL,   -- Tên cột bị chênh lệch (vd: total_assets)
    source_a     VARCHAR(20)  NOT NULL,   -- 'vci' (nguồn trong DB)
    value_a      NUMERIC(25, 4),          -- Giá trị từ VCI
    source_b     VARCHAR(20)  NOT NULL,   -- 'kbs' (nguồn cross-validate)
    value_b      NUMERIC(25, 4),          -- Giá trị từ KBS
    diff_pct     NUMERIC(10, 4),          -- |VCI - KBS| / |VCI| × 100 (%)
    flagged_at   TIMESTAMP    DEFAULT NOW(),
    resolved     BOOLEAN      DEFAULT FALSE,
    resolved_at  TIMESTAMP,
    notes        TEXT,

    CONSTRAINT uq_dq_flag UNIQUE (symbol, table_name, period, column_name, source_a, source_b)
);

CREATE INDEX IF NOT EXISTS idx_dq_symbol     ON data_quality_flags(symbol);
CREATE INDEX IF NOT EXISTS idx_dq_unresolved ON data_quality_flags(resolved) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_dq_flagged_at ON data_quality_flags(flagged_at DESC);

COMMENT ON TABLE data_quality_flags IS
    'Di thuong khi cross-validate BCTC giua VCI (nguon chinh, trong DB) '
    'va KBS (nguon thu 2, fetch qua vnstock Finance). '
    'diff_pct = |VCI - KBS| / |VCI| x 100. Flag khi diff_pct > 2%.';

COMMENT ON COLUMN data_quality_flags.diff_pct IS
    'Ty le chenh lech tuyet doi (%). Cong thuc: |value_a - value_b| / |value_a| x 100.';

COMMENT ON COLUMN data_quality_flags.resolved IS
    'TRUE khi da xac minh va chap nhan chenh lech (vd: khac biet ve phuong phap ke toan).';
