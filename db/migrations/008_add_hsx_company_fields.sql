-- ============================================================
-- Migration 008: Thêm thông tin liên hệ/mô tả từ HSX API vào companies
-- Nguồn: https://api.hsx.vn/l/api/v1/1/securities/stock
-- Chỉ áp dụng cho mã HOSE — các sàn khác để NULL
-- ============================================================

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS brief    VARCHAR(500),
    ADD COLUMN IF NOT EXISTS phone    VARCHAR(100),
    ADD COLUMN IF NOT EXISTS fax      VARCHAR(100),
    ADD COLUMN IF NOT EXISTS address  TEXT,
    ADD COLUMN IF NOT EXISTS web_url  VARCHAR(500);

COMMENT ON COLUMN companies.brief    IS 'Tên viết tắt / tên tiếng Anh (nguồn: HSX API)';
COMMENT ON COLUMN companies.phone    IS 'Số điện thoại trụ sở (nguồn: HSX API)';
COMMENT ON COLUMN companies.fax      IS 'Số fax trụ sở (nguồn: HSX API)';
COMMENT ON COLUMN companies.address  IS 'Địa chỉ trụ sở chính (nguồn: HSX API)';
COMMENT ON COLUMN companies.web_url  IS 'Website chính thức (nguồn: HSX API)';
