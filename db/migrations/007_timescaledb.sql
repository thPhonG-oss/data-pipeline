-- ============================================================
-- Migration 007: TimescaleDB — Hypertables, Retention,
--                Compression, Continuous Aggregates
--
-- Yêu cầu: migration 001 (timescaledb extension) và
--           migration 006 (price tables) đã chạy xong.
-- ============================================================

-- ── price_intraday hypertable ─────────────────────────────────────────────────

SELECT create_hypertable(
    'price_intraday',
    'time',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists        => TRUE,
    migrate_data         => TRUE
);

SELECT add_retention_policy(
    'price_intraday',
    INTERVAL '180 days',
    if_not_exists => TRUE
);

ALTER TABLE price_intraday SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'time DESC',
    timescaledb.compress_segmentby = 'symbol, resolution'
);

SELECT add_compression_policy(
    'price_intraday',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- ── price_history hypertable ──────────────────────────────────────────────────

SELECT create_hypertable(
    'price_history',
    'date',
    chunk_time_interval => INTERVAL '90 days',
    if_not_exists        => TRUE,
    migrate_data         => TRUE
);

ALTER TABLE price_history SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'date DESC',
    timescaledb.compress_segmentby = 'symbol, source'
);

SELECT add_compression_policy(
    'price_history',
    INTERVAL '90 days',
    if_not_exists => TRUE
);

-- ── Continuous Aggregates: 1m → 5m → 1H → 1D ────────────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_ohlc_5m
WITH (timescaledb.continuous, timescaledb.materialized_only = TRUE) AS
SELECT
    symbol,
    time_bucket('5 minutes'::interval, time)  AS bucket,
    5                                          AS resolution,
    first(open,  time)                         AS open,
    max(high)                                  AS high,
    min(low)                                   AS low,
    last(close,  time)                         AS close,
    sum(volume)                                AS volume
FROM price_intraday
WHERE resolution = 1
GROUP BY symbol, time_bucket('5 minutes'::interval, time);

SELECT add_continuous_aggregate_policy(
    'cagg_ohlc_5m',
    start_offset      => INTERVAL '15 minutes',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_ohlc_1h
WITH (timescaledb.continuous, timescaledb.materialized_only = TRUE) AS
SELECT
    symbol,
    time_bucket('1 hour'::interval, bucket)   AS bucket,
    60                                         AS resolution,
    first(open,  bucket)                       AS open,
    max(high)                                  AS high,
    min(low)                                   AS low,
    last(close,  bucket)                       AS close,
    sum(volume)                                AS volume
FROM cagg_ohlc_5m
GROUP BY symbol, time_bucket('1 hour'::interval, bucket);

SELECT add_continuous_aggregate_policy(
    'cagg_ohlc_1h',
    start_offset      => INTERVAL '3 hours',
    end_offset        => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists     => TRUE
);

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_ohlc_1d
WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
SELECT
    symbol,
    time_bucket('1 day'::interval, bucket)    AS bucket,
    1440                                       AS resolution,
    first(open,  bucket)                       AS open,
    max(high)                                  AS high,
    min(low)                                   AS low,
    last(close,  bucket)                       AS close,
    sum(volume)                                AS volume
FROM cagg_ohlc_1h
GROUP BY symbol, time_bucket('1 day'::interval, bucket);

SELECT add_continuous_aggregate_policy(
    'cagg_ohlc_1d',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);
