-- ============================================================
-- Migration 014: financial_reports
--
-- Bảng thống nhất cho BCĐKT, KQKD, LCTT
-- của tất cả 4 mẫu biểu (Phi tài chính, Ngân hàng, Chứng khoán, Bảo hiểm)
--
-- Conflict key: (symbol, period, period_type, statement_type)
-- raw_details merge: financial_reports.raw_details || EXCLUDED.raw_details
-- ============================================================

-- ── ENUM types ────────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE statement_type_enum AS ENUM (
        'balance_sheet',        -- Bảng cân đối kế toán
        'income_statement',     -- Kết quả kinh doanh
        'cash_flow'             -- Lưu chuyển tiền tệ
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE period_type_enum AS ENUM (
        'year',     -- Năm: "2024"
        'quarter'   -- Quý: "2024Q1", "2024Q2"...
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE fin_template_enum AS ENUM (
        'non_financial',  -- Phi tài chính (sản xuất, bán lẻ, công nghệ...)
        'banking',        -- Ngân hàng (ICB 8300)
        'securities',     -- Chứng khoán (ICB 8500)
        'insurance'       -- Bảo hiểm (ICB 8400)
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── Bảng chính ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS financial_reports (

    -- ── Định danh ─────────────────────────────────────────────────
    id              BIGSERIAL            PRIMARY KEY,
    symbol          VARCHAR(10)          NOT NULL REFERENCES companies(symbol),
    period          VARCHAR(10)          NOT NULL,   -- "2024" | "2024Q1"
    period_type     period_type_enum     NOT NULL,
    statement_type  statement_type_enum  NOT NULL,
    template        fin_template_enum    NOT NULL,
    source          VARCHAR(20)          NOT NULL DEFAULT 'vci',

    -- ── Tài sản — Cross-Industry Core ─────────────────────────────
    -- NULL = không áp dụng cho template này
    -- 0    = áp dụng nhưng không được báo cáo kỳ này
    cash_and_equivalents        NUMERIC(20, 2),  -- Tiền và tương đương tiền
    total_current_assets        NUMERIC(20, 2),  -- TÀI SẢN NGẮN HẠN
    total_non_current_assets    NUMERIC(20, 2),  -- TÀI SẢN DÀI HẠN
    total_assets                NUMERIC(20, 2),  -- TỔNG CỘNG TÀI SẢN
    total_liabilities           NUMERIC(20, 2),  -- NỢ PHẢI TRẢ
    total_equity                NUMERIC(20, 2),  -- Vốn chủ sở hữu
    charter_capital             NUMERIC(20, 2),  -- Vốn góp / Vốn điều lệ
    short_term_debt             NUMERIC(20, 2),  -- Vay ngắn hạn
    long_term_debt              NUMERIC(20, 2),  -- Vay dài hạn
    retained_earnings           NUMERIC(20, 2),  -- Lãi chưa phân phối

    -- ── Tài sản — Phi tài chính (NULL với Banking/Insurance) ──────
    inventory_net               NUMERIC(20, 2),  -- Hàng tồn kho, ròng (sau dự phòng)
    inventory_gross             NUMERIC(20, 2),  -- Hàng tồn kho (trước dự phòng)
    short_term_receivables      NUMERIC(20, 2),  -- Phải thu khách hàng
    ppe_net                     NUMERIC(20, 2),  -- GTCL TSCĐ hữu hình
    ppe_gross                   NUMERIC(20, 2),  -- Nguyên giá TSCĐ hữu hình
    accumulated_depreciation    NUMERIC(20, 2),  -- Khấu hao lũy kế TSCĐ hữu hình
    construction_in_progress    NUMERIC(20, 2),  -- Xây dựng cơ bản đang dở dang

    -- ── Tài sản — Ngân hàng (NULL với Non-Financial) ──────────────
    customer_loans_gross        NUMERIC(20, 2),  -- Cho vay khách hàng (trước dự phòng)
    loan_loss_reserve           NUMERIC(20, 2),  -- Dự phòng rủi ro cho vay KH
    customer_deposits           NUMERIC(20, 2),  -- Tiền gửi của khách hàng

    -- ── KQKD — Cross-Industry Core ────────────────────────────────
    net_revenue                 NUMERIC(20, 2),  -- Doanh thu thuần
    operating_profit            NUMERIC(20, 2),  -- Lãi/(lỗ) từ hoạt động kinh doanh
    ebt                         NUMERIC(20, 2),  -- Lãi/(lỗ) trước thuế
    net_profit                  NUMERIC(20, 2),  -- Lãi/(lỗ) thuần sau thuế
    net_profit_parent           NUMERIC(20, 2),  -- Lợi nhuận của Cổ đông Công ty mẹ
    eps_basic                   NUMERIC(15, 2),  -- Lãi cơ bản trên cổ phiếu (VND)

    -- ── KQKD — Phi tài chính (NULL với Banking/Insurance) ─────────
    gross_revenue               NUMERIC(20, 2),  -- Doanh thu bán hàng và CCDV
    cost_of_goods_sold          NUMERIC(20, 2),  -- Giá vốn hàng bán (đã abs())
    gross_profit                NUMERIC(20, 2),  -- Lợi nhuận gộp
    selling_expenses            NUMERIC(20, 2),  -- Chi phí bán hàng (đã abs())
    admin_expenses              NUMERIC(20, 2),  -- Chi phí quản lý doanh nghiệp (đã abs())
    interest_expense            NUMERIC(20, 2),  -- Chi phí lãi vay (đã abs())

    -- ── KQKD — Ngân hàng (NULL với Non-Financial) ─────────────────
    net_interest_income         NUMERIC(20, 2),  -- Thu nhập lãi thuần
    credit_provision_expense    NUMERIC(20, 2),  -- Chi phí dự phòng rủi ro tín dụng (đã abs())

    -- ── LCTT — Core (tất cả template) ─────────────────────────────
    cfo                         NUMERIC(20, 2),  -- Lưu chuyển tiền từ HĐKD (có thể âm)
    cfi                         NUMERIC(20, 2),  -- Lưu chuyển tiền từ HĐ đầu tư
    cff                         NUMERIC(20, 2),  -- Lưu chuyển tiền từ HĐ tài chính
    capex                       NUMERIC(20, 2),  -- Chi TSCĐ (đã abs())
    net_cash_change             NUMERIC(20, 2),  -- Lưu chuyển tiền thuần trong kỳ
    cash_beginning              NUMERIC(20, 2),  -- Tiền đầu kỳ
    cash_ending                 NUMERIC(20, 2),  -- Tiền cuối kỳ

    -- ── Lưu trữ thô ───────────────────────────────────────────────
    raw_details                 JSONB        NOT NULL DEFAULT '{}',

    -- ── Audit ─────────────────────────────────────────────────────
    fetched_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    created_at                  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- ── Ràng buộc ─────────────────────────────────────────────────
    CONSTRAINT uq_financial_reports
        UNIQUE (symbol, period, period_type, statement_type)
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_fr_symbol_period
    ON financial_reports (symbol, period_type, period DESC);

CREATE INDEX IF NOT EXISTS idx_fr_period_template
    ON financial_reports (period, period_type, template);

CREATE INDEX IF NOT EXISTS idx_fr_symbol_stmt
    ON financial_reports (symbol, statement_type);

CREATE INDEX IF NOT EXISTS idx_fr_raw_details_gin
    ON financial_reports USING GIN (raw_details);

-- Partial index cho báo cáo năm (truy vấn phổ biến nhất)
CREATE INDEX IF NOT EXISTS idx_fr_annual
    ON financial_reports (symbol, period DESC)
    WHERE period_type = 'year';

-- ── CHECK Constraints (NOT VALID — validate sau khi load production) ──────────
-- Dùng DO block để idempotent (bỏ qua nếu constraint đã tồn tại)

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_banking_null_inventory
        CHECK (NOT (template = 'banking' AND inventory_net IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_banking_null_cogs
        CHECK (NOT (template = 'banking' AND cost_of_goods_sold IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_nonfinancial_null_loans
        CHECK (NOT (template = 'non_financial' AND customer_loans_gross IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    ALTER TABLE financial_reports
        ADD CONSTRAINT chk_nonfinancial_null_nii
        CHECK (NOT (template = 'non_financial' AND net_interest_income IS NOT NULL))
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
