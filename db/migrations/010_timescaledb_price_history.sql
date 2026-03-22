-- ============================================================
-- Migration 010: Chuyển price_history thành hypertable.
-- Không có retention policy (giữ toàn bộ lịch sử).
-- Compression sau 90 ngày (dữ liệu EOD ít thay đổi).
-- Tất cả DDL đều idempotent — an toàn khi chạy lại.
-- ============================================================

-- Bước 1: Bỏ cột id
ALTER TABLE price_history DROP COLUMN IF EXISTS id;

-- Bước 2: Bỏ UNIQUE constraint cũ, promote lên PRIMARY KEY (idempotent)
ALTER TABLE price_history DROP CONSTRAINT IF EXISTS uq_price_history;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'price_history_pkey' AND contype = 'p'
    ) THEN
        ALTER TABLE price_history ADD PRIMARY KEY (date, symbol, source);
    END IF;
END $$;

-- Bước 3: Convert sang hypertable, partition theo 'date', chunk = 90 ngày
-- QUAN TRỌNG: price_history.date là kiểu DATE (không phải TIMESTAMPTZ).
-- TimescaleDB yêu cầu chunk_time_interval là INTEGER (số ngày) cho cột DATE.
-- Dùng 90 (ngày) thay vì INTERVAL '3 months' — INTERVAL sẽ báo lỗi với DATE.
SELECT create_hypertable(
    'price_history',
    'date',
    chunk_time_interval => 90,
    if_not_exists        => TRUE,
    migrate_data         => TRUE
);

-- Bước 4: Bật columnar compression, segment theo symbol + source
ALTER TABLE price_history SET (
    timescaledb.compress,
    timescaledb.compress_orderby   = 'date DESC',
    timescaledb.compress_segmentby = 'symbol, source'
);

-- Tự động nén chunks cũ hơn 90 ngày
SELECT add_compression_policy('price_history', INTERVAL '90 days', if_not_exists => TRUE);
