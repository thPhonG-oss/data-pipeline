-- ============================================================
-- Migration 005: Bảng giá lịch sử OHLCV
-- Nguồn chính:    DNSE LightSpeed API (qua vnstock Quote, feed trực tiếp từ sàn)
-- Nguồn dự phòng: VNDirect finfo-api (public, không cần auth)
--
-- Đơn vị lưu trữ: close/open/high/low/close_adj = VND nguyên
-- → DNSE qua vnstock: kiểm tra đơn vị khi implement (có thể đã normalize)
-- → VNDirect trả về nghìn VND → nhân ×1000 trước khi lưu
-- ============================================================

CREATE TABLE IF NOT EXISTS price_history (
    id          SERIAL       PRIMARY KEY,
    symbol      VARCHAR(10)  NOT NULL
        CONSTRAINT fk_ph_symbol REFERENCES companies(symbol),
    date        DATE         NOT NULL,

    open        INTEGER,          -- Giá mở cửa (VND)
    high        INTEGER,          -- Giá cao nhất trong phiên (VND)
    low         INTEGER,          -- Giá thấp nhất trong phiên (VND)
    close       INTEGER NOT NULL, -- Giá đóng cửa (VND)
    close_adj   INTEGER,          -- Giá đóng cửa điều chỉnh — NULL khi source=dnse
    volume      BIGINT,           -- Khối lượng khớp (cổ phiếu)
    volume_nm   BIGINT,           -- Khối lượng khớp lệnh thông thường (VNDirect: nmVolume)
    value       BIGINT,           -- Giá trị giao dịch (triệu VND)

    source      VARCHAR(20)  DEFAULT 'dnse',
    fetched_at  TIMESTAMP    DEFAULT NOW(),

    CONSTRAINT uq_price_history UNIQUE (symbol, date, source)
);

CREATE INDEX IF NOT EXISTS idx_ph_symbol   ON price_history(symbol);
CREATE INDEX IF NOT EXISTS idx_ph_date     ON price_history(date DESC);
CREATE INDEX IF NOT EXISTS idx_ph_sym_date ON price_history(symbol, date DESC);

COMMENT ON TABLE price_history IS
    'Giá lịch sử OHLCV theo ngày. '
    'Nguồn chính: DNSE LightSpeed API qua vnstock Quote(source=DNSE). '
    'Nguồn dự phòng: VNDirect finfo-api (public, không cần auth). '
    'close_adj = NULL khi source=dnse (DNSE không cung cấp adjusted close). '
    'Đơn vị: open/high/low/close/close_adj = VND nguyên.';

COMMENT ON COLUMN price_history.close_adj IS
    'Giá đóng cửa đã điều chỉnh — dùng để tính P/E, P/B, return chính xác khi có sự kiện cổ tức, tách cổ phiếu. NULL khi source=dnse.';

COMMENT ON COLUMN price_history.value IS
    'Giá trị giao dịch, đơn vị triệu VND.';

COMMENT ON COLUMN price_history.volume_nm IS
    'Khối lượng khớp lệnh thông thường (normal match). Chỉ có từ VNDirect (nmVolume). NULL khi source=dnse.';
