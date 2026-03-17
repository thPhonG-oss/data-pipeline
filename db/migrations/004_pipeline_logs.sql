-- ============================================================
-- Migration 004: Bảng vận hành pipeline
-- pipeline_logs
-- ============================================================

CREATE TABLE IF NOT EXISTS pipeline_logs (
    id               SERIAL      PRIMARY KEY,
    job_name         VARCHAR(100) NOT NULL,
    symbol           VARCHAR(10),
    status           VARCHAR(20)  NOT NULL
        CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    records_fetched  INTEGER      DEFAULT 0,
    records_inserted INTEGER      DEFAULT 0,
    error_message    TEXT,
    started_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMP,
    -- Thời gian chạy tính bằng milliseconds (tự tính, chỉ đọc)
    duration_ms      INTEGER GENERATED ALWAYS AS (
        EXTRACT(MILLISECONDS FROM finished_at - started_at)::INTEGER
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_logs_job_name   ON pipeline_logs(job_name);
CREATE INDEX IF NOT EXISTS idx_logs_status     ON pipeline_logs(status);
CREATE INDEX IF NOT EXISTS idx_logs_started_at ON pipeline_logs(started_at DESC);

COMMENT ON TABLE  pipeline_logs IS 'Nhật ký chạy ETL pipeline, theo dõi trạng thái từng job.';
COMMENT ON COLUMN pipeline_logs.duration_ms IS
    'Thời gian thực thi (ms). Tự tính từ finished_at - started_at, chỉ đọc.';
