-- ============================================================
-- Migration 011: Continuous Aggregates cho dữ liệu intraday
-- Chuỗi: 1m (raw) → 5m → 1H → 1D
-- Dùng TimescaleDB hierarchical CAggs (yêu cầu v2.9+)
-- ============================================================

-- ── Aggregate 1: cagg_ohlc_5m (từ price_intraday 1m) ────────────────────────
-- materialized_only = TRUE: bắt buộc vì cagg_ohlc_1h sẽ query view này
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

-- Refresh: cập nhật từ 10 phút trước đến 1 phút trước, mỗi 1 phút
SELECT add_continuous_aggregate_policy(
    'cagg_ohlc_5m',
    start_offset      => INTERVAL '10 minutes',
    end_offset        => INTERVAL '1 minute',
    schedule_interval => INTERVAL '1 minute',
    if_not_exists     => TRUE
);

-- ── Aggregate 2: cagg_ohlc_1h (từ cagg_ohlc_5m) ─────────────────────────────
-- materialized_only = TRUE: bắt buộc vì cagg_ohlc_1d sẽ query view này
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

-- Refresh: cập nhật từ 1 giờ trước đến 5 phút trước, mỗi 5 phút
SELECT add_continuous_aggregate_policy(
    'cagg_ohlc_1h',
    start_offset      => INTERVAL '1 hour',
    end_offset        => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists     => TRUE
);

-- ── Aggregate 3: cagg_ohlc_1d (từ cagg_ohlc_1h) ─────────────────────────────
-- materialized_only = FALSE: leaf CAgg — cho phép đọc real-time nến hiện tại
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

-- Refresh: cập nhật từ 1 ngày trước đến 1 giờ trước, mỗi 1 giờ
SELECT add_continuous_aggregate_policy(
    'cagg_ohlc_1d',
    start_offset      => INTERVAL '1 day',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE
);
