-- ============================================================
-- Migration 015: Xóa các bảng tài chính cũ
--
-- Các bảng này được thay thế bởi bảng thống nhất financial_reports
-- (xem migration 014_financial_reports.sql).
--
-- Bảng bị xóa:
--   - balance_sheets    → financial_reports (statement_type='balance_sheet')
--   - income_statements → financial_reports (statement_type='income_statement')
--   - cash_flows        → financial_reports (statement_type='cash_flow')
--   - financial_ratios  → financial_reports (statement_type không dùng — ratio riêng)
--
-- Điều kiện tiên quyết:
--   Migration 014 đã chạy xong và dữ liệu đã được migrate sang financial_reports.
-- ============================================================

DROP TABLE IF EXISTS balance_sheets     CASCADE;
DROP TABLE IF EXISTS income_statements  CASCADE;
DROP TABLE IF EXISTS cash_flows         CASCADE;
DROP TABLE IF EXISTS financial_ratios   CASCADE;
