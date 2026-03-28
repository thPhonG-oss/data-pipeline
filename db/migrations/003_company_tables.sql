-- ============================================================
-- Migration 003: Bảng thông tin doanh nghiệp (Company Intelligence)
-- shareholders, officers, subsidiaries, corporate_events, ratio_summary
-- ============================================================

CREATE TABLE IF NOT EXISTS shareholders (
    id                  SERIAL       PRIMARY KEY,
    symbol              VARCHAR(10)  NOT NULL
        CONSTRAINT fk_sh_symbol REFERENCES companies(symbol),
    share_holder        VARCHAR(500) NOT NULL,
    quantity            BIGINT,
    share_own_percent   NUMERIC(8, 4),
    update_date         DATE,
    snapshot_date       DATE         NOT NULL DEFAULT CURRENT_DATE,

    CONSTRAINT uq_shareholders UNIQUE (symbol, share_holder, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_shareholders_symbol ON shareholders(symbol);
CREATE INDEX IF NOT EXISTS idx_shareholders_date   ON shareholders(snapshot_date);

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS officers (
    id                   SERIAL       PRIMARY KEY,
    symbol               VARCHAR(10)  NOT NULL
        CONSTRAINT fk_of_symbol REFERENCES companies(symbol),
    officer_name         VARCHAR(300) NOT NULL,
    officer_position     VARCHAR(300),
    position_short_name  VARCHAR(100),
    officer_own_percent  NUMERIC(8, 4),
    quantity             BIGINT,
    update_date          DATE,
    status               VARCHAR(20)  DEFAULT 'working'
        CHECK (status IN ('working', 'resigned')),
    snapshot_date        DATE         NOT NULL DEFAULT CURRENT_DATE,

    CONSTRAINT uq_officers UNIQUE (symbol, officer_name, status, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_officers_symbol ON officers(symbol);

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS subsidiaries (
    id                  SERIAL       PRIMARY KEY,
    symbol              VARCHAR(10)  NOT NULL
        CONSTRAINT fk_sub_symbol REFERENCES companies(symbol),
    sub_organ_code      VARCHAR(20),
    organ_name          VARCHAR(500) NOT NULL,
    ownership_percent   NUMERIC(8, 4),
    type                VARCHAR(50)
        CHECK (type IN ('subsidiary', 'associated')),
    snapshot_date       DATE         NOT NULL DEFAULT CURRENT_DATE,

    CONSTRAINT uq_subsidiaries UNIQUE (symbol, organ_name, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_subsidiaries_symbol ON subsidiaries(symbol);

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS corporate_events (
    id               SERIAL       PRIMARY KEY,
    symbol           VARCHAR(10)  NOT NULL
        CONSTRAINT fk_ev_symbol REFERENCES companies(symbol),
    event_title      VARCHAR(500),
    event_list_code  VARCHAR(20),
    event_list_name  VARCHAR(300),
    public_date      DATE,
    issue_date       DATE,
    record_date      DATE,
    exright_date     DATE,
    ratio            NUMERIC(15, 6),
    value            NUMERIC(20, 4),
    source_url       TEXT,
    fetched_at       TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT uq_corporate_events UNIQUE (symbol, event_list_code, record_date)
);

CREATE INDEX IF NOT EXISTS idx_events_symbol      ON corporate_events(symbol);
CREATE INDEX IF NOT EXISTS idx_events_record_date ON corporate_events(record_date);
CREATE INDEX IF NOT EXISTS idx_events_code        ON corporate_events(event_list_code);

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ratio_summary (
    id                     SERIAL       PRIMARY KEY,
    symbol                 VARCHAR(10)  NOT NULL
        CONSTRAINT fk_rs_symbol REFERENCES companies(symbol),
    year_report            SMALLINT     NOT NULL,
    quarter_report         SMALLINT,
    revenue                BIGINT,
    revenue_growth         NUMERIC(10, 4),
    net_profit             BIGINT,
    net_profit_growth      NUMERIC(10, 4),
    ebit_margin            NUMERIC(10, 4),
    roe                    NUMERIC(10, 4),
    roa                    NUMERIC(10, 4),
    roic                   NUMERIC(10, 4),
    pe                     NUMERIC(10, 4),
    pb                     NUMERIC(10, 4),
    ps                     NUMERIC(10, 4),
    pcf                    NUMERIC(10, 4),
    eps                    NUMERIC(15, 2),
    eps_ttm                NUMERIC(15, 2),
    bvps                   NUMERIC(15, 2),
    current_ratio          NUMERIC(10, 4),
    quick_ratio            NUMERIC(10, 4),
    cash_ratio             NUMERIC(10, 4),
    interest_coverage      NUMERIC(10, 4),
    debt_to_equity         NUMERIC(10, 4),
    net_profit_margin      NUMERIC(10, 4),
    gross_margin           NUMERIC(10, 4),
    ev                     BIGINT,
    ev_ebitda              NUMERIC(10, 4),
    ebitda                 BIGINT,
    ebit                   BIGINT,
    asset_turnover         NUMERIC(10, 4),
    fixed_asset_turnover   NUMERIC(10, 4),
    receivable_days        NUMERIC(10, 2),
    inventory_days         NUMERIC(10, 2),
    payable_days           NUMERIC(10, 2),
    cash_conversion_cycle  NUMERIC(10, 2),
    dividend               NUMERIC(15, 2),
    issue_share            BIGINT,
    charter_capital        BIGINT,
    extra_metrics          JSONB,
    fetched_at             TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT uq_ratio_summary UNIQUE (symbol, year_report, quarter_report)
);

CREATE INDEX IF NOT EXISTS idx_rs_symbol ON ratio_summary(symbol);
CREATE INDEX IF NOT EXISTS idx_rs_roe    ON ratio_summary(roe);
CREATE INDEX IF NOT EXISTS idx_rs_pe     ON ratio_summary(pe);
