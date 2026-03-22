-- ============================================================
-- Migration 009: Kích hoạt TimescaleDB + chuyển price_intraday
-- thành hypertable với retention và compression.
-- Tất cả DDL đều idempotent — an toàn khi chạy lại.
-- ============================================================

-- Bước 1: Kích hoạt extension TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- Bước 2: Bỏ cột id (surrogate key không cần thiết cho hypertable)
-- PostgresLoader loại id qua SERVER_GENERATED_COLS; _transform_message không sinh id.
ALTER TABLE price_intraday DROP COLUMN IF EXISTS id;

-- Bước 3: Bỏ UNIQUE constraint cũ, promote lên PRIMARY KEY (idempotent)
-- TimescaleDB yêu cầu PK phải bao gồm partition column (time ✓)
ALTER TABLE price_intraday DROP CONSTRAINT IF EXISTS uq_price_intraday;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'price_intraday_pkey' AND contype = 'p'
    ) THEN
        ALTER TABLE price_intraday ADD PRIMARY KEY (time, symbol, resolution);
    END IF;
END $$;

-- Bước 4: Convert sang hypertable, partition theo 'time', chunk = 1 tuần
-- migrate_data => TRUE cho phép chuyển đổi khi bảng đã có dữ liệu
SELECT create_hypertable(
    'price_intraday',
    'time',
    chunk_time_interval => INTERVAL '1 week',
    if_not_exists        => TRUE,
    migrate_data         => TRUE
);

-- Bước 5: Retention policy 180 ngày
-- Ghi chú: TimescaleDB không hỗ trợ retention theo giá trị cột (resolution).
-- Chọn 180 ngày (= yêu cầu 5m); 1m data sau 30 ngày được nén ~90% — chấp nhận được.
SELECT add_retention_policy('price_intraday', INTERVAL '180 days', if_not_exists => TRUE);

-- Bước 6: Bật columnar compression, segment theo symbol+resolution
ALTER TABLE price_intraday SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'time DESC',
    timescaledb.compress_segmentby = 'symbol, resolution'
);

-- Tự động nén chunks cũ hơn 7 ngày
SELECT add_compression_policy('price_intraday', INTERVAL '7 days', if_not_exists => TRUE);
