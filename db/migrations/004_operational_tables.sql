-- ============================================================
-- Migration 004: Bảng vận hành (Operational Tables)
-- pipeline_logs, data_quality_flags, company_news
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_logs (
    id               SERIAL       PRIMARY KEY,
    job_name         VARCHAR(100) NOT NULL,
    symbol           VARCHAR(10),
    status           VARCHAR(20)  NOT NULL
        CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    records_fetched  INTEGER      DEFAULT 0,
    records_inserted INTEGER      DEFAULT 0,
    error_message    TEXT,
    started_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMP,
    duration_ms      INTEGER GENERATED ALWAYS AS (
        EXTRACT(MILLISECONDS FROM finished_at - started_at)::INTEGER
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_logs_job_name   ON pipeline_logs(job_name);
CREATE INDEX IF NOT EXISTS idx_logs_status     ON pipeline_logs(status);
CREATE INDEX IF NOT EXISTS idx_logs_started_at ON pipeline_logs(started_at DESC);

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS data_quality_flags (
    id           SERIAL       PRIMARY KEY,
    symbol       VARCHAR(10)  NOT NULL,
    table_name   VARCHAR(50)  NOT NULL,
    period       VARCHAR(10)  NOT NULL,
    column_name  VARCHAR(100) NOT NULL,
    source_a     VARCHAR(20)  NOT NULL,
    value_a      NUMERIC(25, 4),
    source_b     VARCHAR(20)  NOT NULL,
    value_b      NUMERIC(25, 4),
    diff_pct     NUMERIC(10, 4),
    flagged_at   TIMESTAMP    DEFAULT NOW(),
    resolved     BOOLEAN      DEFAULT FALSE,
    resolved_at  TIMESTAMP,
    notes        TEXT,

    CONSTRAINT uq_dq_flag UNIQUE (symbol, table_name, period, column_name, source_a, source_b)
);

CREATE INDEX IF NOT EXISTS idx_dq_symbol     ON data_quality_flags(symbol);
CREATE INDEX IF NOT EXISTS idx_dq_unresolved ON data_quality_flags(resolved) WHERE resolved = FALSE;
CREATE INDEX IF NOT EXISTS idx_dq_flagged_at ON data_quality_flags(flagged_at DESC);

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS company_news (
    id                 BIGSERIAL    PRIMARY KEY,
    vci_id             BIGINT       NOT NULL,
    symbol             VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    news_title         TEXT,
    news_sub_title     TEXT,
    friendly_sub_title TEXT,
    news_id            BIGINT,
    news_short_content TEXT,
    news_full_content  TEXT,
    news_source_link   TEXT,
    news_image_url     TEXT,
    lang_code          VARCHAR(10)  DEFAULT 'vi',
    public_date        TIMESTAMPTZ,
    close_price        INTEGER,
    ref_price          INTEGER,
    floor_price        INTEGER,
    ceiling_price      INTEGER,
    price_change_pct   NUMERIC(10, 8),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    UNIQUE (vci_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_company_news_symbol      ON company_news(symbol);
CREATE INDEX IF NOT EXISTS idx_company_news_public_date ON company_news(public_date DESC);
CREATE INDEX IF NOT EXISTS idx_company_news_symbol_date ON company_news(symbol, public_date DESC);
