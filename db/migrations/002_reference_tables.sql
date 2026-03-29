-- ============================================================
-- Migration 002: Bảng danh mục (Reference Tables)
-- icb_industries, companies
-- ============================================================

CREATE TABLE IF NOT EXISTS icb_industries (
    icb_code        VARCHAR(10)  PRIMARY KEY,
    icb_name        VARCHAR(300) NOT NULL,
    en_icb_name     VARCHAR(300),
    level           SMALLINT     NOT NULL CHECK (level BETWEEN 1 AND 4),
    parent_code     VARCHAR(10)  REFERENCES icb_industries(icb_code),
    definition      TEXT,
    created_at      TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_icb_level       ON icb_industries(level);
CREATE INDEX IF NOT EXISTS idx_icb_parent_code ON icb_industries(parent_code);

COMMENT ON TABLE icb_industries IS
    'Phan loai nganh theo chuan ICB (Industry Classification Benchmark), 4 cap do.';
COMMENT ON COLUMN icb_industries.level IS
    '1=Linh vuc, 2=Sieu nganh, 3=Nhom nganh, 4=Nganh cu the';
COMMENT ON COLUMN icb_industries.definition IS
    'Mo ta chi tiet ve nganh (chi co o level 4), nguon: ICB FTSE Russell.';

-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
    symbol           VARCHAR(10)  PRIMARY KEY,
    company_name     VARCHAR(500) NOT NULL,
    company_name_eng VARCHAR(500),
    short_name       VARCHAR(200),
    exchange         VARCHAR(20)  NOT NULL
        CHECK (exchange IN ('HOSE', 'HNX', 'UPCOM')),
    type             VARCHAR(30)  NOT NULL
        CHECK (type IN ('STOCK', 'ETF', 'BOND', 'CW', 'FUND')),
    status           VARCHAR(20)  NOT NULL DEFAULT 'listed'
        CHECK (status IN ('listed', 'delisted', 'suspended')),
    icb_code         VARCHAR(10)
        CONSTRAINT fk_companies_icb REFERENCES icb_industries(icb_code),
    listed_date      DATE,
    delisted_date    DATE,
    charter_capital  BIGINT,
    issue_share      BIGINT,
    company_id       INTEGER,
    isin             VARCHAR(20),
    tax_code         VARCHAR(20),
    history          TEXT,
    company_profile  TEXT,
    created_at       TIMESTAMP    DEFAULT NOW(),
    updated_at       TIMESTAMP    DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_exchange ON companies(exchange);
CREATE INDEX IF NOT EXISTS idx_companies_type     ON companies(type);
CREATE INDEX IF NOT EXISTS idx_companies_status   ON companies(status);
CREATE INDEX IF NOT EXISTS idx_companies_icb_code ON companies(icb_code);

COMMENT ON TABLE companies IS
    'Danh muc toan bo chung khoan niem yet, duoc dong bo dinh ky tu vnstock_data.Listing.';
COMMENT ON COLUMN companies.history         IS 'Lich su hinh thanh va phat trien doanh nghiep';
COMMENT ON COLUMN companies.company_profile IS 'Gioi thieu tong quan ve doanh nghiep';
