-- ============================================================
-- Migration 012: Thêm history và company_profile vào companies
-- Dữ liệu lấy từ company.overview() (vnstock_data)
-- ============================================================

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS history        TEXT,
    ADD COLUMN IF NOT EXISTS company_profile TEXT;

COMMENT ON COLUMN companies.history         IS 'Lịch sử hình thành và phát triển doanh nghiệp (từ overview().history)';
COMMENT ON COLUMN companies.company_profile IS 'Giới thiệu tổng quan về doanh nghiệp (từ overview().company_profile)';
