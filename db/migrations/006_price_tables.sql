-- ============================================================
-- Migration 006: Bảng giá (Price Tables)
-- price_history (EOD daily OHLCV)
-- price_intraday (real-time 1m/5m candles — TimescaleDB hypertable)
--
-- Thiết kế cho hypertable ngay từ đầu:
--   - Không có cột id (hypertable dùng PK composite)
--   - PK bao gồm partition column (date / time)
-- ============================================================

-- ── EOD daily price history ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS price_history (
    symbol      VARCHAR(10)  NOT NULL
        CONSTRAINT fk_ph_symbol REFERENCES companies(symbol),
    date        DATE         NOT NULL,
    open        INTEGER,
    high        INTEGER,
    low         INTEGER,
    close       INTEGER      NOT NULL,
    close_adj   INTEGER,
    volume      BIGINT,
    volume_nm   BIGINT,
    value       BIGINT,
    source      VARCHAR(20)  NOT NULL DEFAULT 'dnse',
    fetched_at  TIMESTAMP    DEFAULT NOW(),

    PRIMARY KEY (date, symbol, source)
);

CREATE INDEX IF NOT EXISTS idx_ph_symbol   ON price_history(symbol);
CREATE INDEX IF NOT EXISTS idx_ph_sym_date ON price_history(symbol, date DESC);

COMMENT ON TABLE price_history IS
    'Gia lich su OHLCV theo ngay. Nguon chinh: DNSE. Fallback: VNDirect.';
COMMENT ON COLUMN price_history.close_adj IS
    'Gia dong cua da dieu chinh — NULL khi source=dnse.';

-- ── Intraday candles (1m / 5m) ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS price_intraday (
    symbol      VARCHAR(10)  NOT NULL
        CONSTRAINT fk_pi_symbol REFERENCES companies(symbol),
    time        TIMESTAMPTZ  NOT NULL,
    resolution  SMALLINT     NOT NULL,
    open        INTEGER      NOT NULL,
    high        INTEGER      NOT NULL,
    low         INTEGER      NOT NULL,
    close       INTEGER      NOT NULL,
    volume      BIGINT,
    source      VARCHAR(20)  DEFAULT 'dnse_mdds',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),

    PRIMARY KEY (time, symbol, resolution)
);

CREATE INDEX IF NOT EXISTS idx_pi_sym_res_time
    ON price_intraday(symbol, resolution, time DESC);

CREATE INDEX IF NOT EXISTS idx_pi_time
    ON price_intraday(time DESC);

COMMENT ON TABLE price_intraday IS
    'Nen OHLC intraday tu DNSE MDDS (MQTT). resolution=1: nen 1 phut, resolution=5: nen 5 phut.';
