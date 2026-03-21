-- ============================================================
-- Migration 007: Bảng dữ liệu giá intraday (real-time)
-- Lưu nến OHLC 1m và 5m từ DNSE MDDS (MQTT streaming)
-- Tách hoàn toàn khỏi price_history (EOD batch)
-- ============================================================

CREATE TABLE IF NOT EXISTS price_intraday (
    id          BIGSERIAL    PRIMARY KEY,
    symbol      VARCHAR(10)  NOT NULL
                CONSTRAINT fk_pi_symbol REFERENCES companies(symbol),
    time        TIMESTAMPTZ  NOT NULL,
    resolution  SMALLINT     NOT NULL,        -- Timeframe: 1 hoặc 5 (phút)
    open        INTEGER      NOT NULL,        -- VND nguyên (DNSE MDDS trả VND nguyên)
    high        INTEGER      NOT NULL,
    low         INTEGER      NOT NULL,
    close       INTEGER      NOT NULL,
    volume      BIGINT,
    source      VARCHAR(20)  DEFAULT 'dnse_mdds',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT uq_price_intraday UNIQUE (symbol, time, resolution)
);

CREATE INDEX IF NOT EXISTS idx_pi_sym_res_time
    ON price_intraday(symbol, resolution, time DESC);

-- Note: partial index with CURRENT_DATE is not supported in PostgreSQL
-- (predicate functions must be IMMUTABLE). Use idx_pi_sym_res_time for
-- filtering recent data instead: WHERE time >= CURRENT_DATE in queries.
CREATE INDEX IF NOT EXISTS idx_pi_time
    ON price_intraday(time DESC);

COMMENT ON TABLE price_intraday IS
    'Gia intraday OHLC tu DNSE MDDS (MQTT real-time). '
    'resolution=1 la nen 1 phut, resolution=5 la nen 5 phut. '
    'Don vi gia: VND nguyen. Retention: 1m=30 ngay, 5m=180 ngay.';

COMMENT ON COLUMN price_intraday.resolution IS
    'Timeframe tinh bang phut: 1 = nen 1 phut, 5 = nen 5 phut.';
