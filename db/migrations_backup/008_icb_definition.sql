-- Migration 008: Thêm cột definition cho icb_industries
ALTER TABLE icb_industries ADD COLUMN IF NOT EXISTS definition TEXT;

COMMENT ON COLUMN icb_industries.definition IS
    'Mô tả chi tiết về ngành (chỉ có ở level 4 — Ngành cụ thể), nguồn: ICB FTSE Russell.';
