-- Migration 013: Bảng tin tức doanh nghiệp
-- Nguồn: company.news() từ vnstock_data (VCI/FiinGroup)

CREATE TABLE IF NOT EXISTS company_news (
    id                 BIGSERIAL    PRIMARY KEY,
    vci_id             BIGINT       NOT NULL,               -- ID bài viết từ VCI/FiinGroup (cột `id` trong API)
    symbol             VARCHAR(10)  NOT NULL REFERENCES companies(symbol),
    news_title         TEXT,
    news_sub_title     TEXT,
    friendly_sub_title TEXT,
    news_id            BIGINT,                              -- ID phụ từ API (cột `news_id`)
    news_short_content TEXT,
    news_full_content  TEXT,                                -- HTML đầy đủ
    news_source_link   TEXT,
    news_image_url     TEXT,
    lang_code          VARCHAR(10)  DEFAULT 'vi',
    public_date        TIMESTAMPTZ,                        -- Chuyển từ Unix ms trong API
    close_price        INTEGER,                            -- Giá khớp lệnh tại thời điểm đăng
    ref_price          INTEGER,
    floor_price        INTEGER,
    ceiling_price      INTEGER,
    price_change_pct   NUMERIC(10, 8),
    created_at         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (vci_id, symbol)
);

CREATE INDEX IF NOT EXISTS idx_company_news_symbol      ON company_news(symbol);
CREATE INDEX IF NOT EXISTS idx_company_news_public_date ON company_news(public_date DESC);
CREATE INDEX IF NOT EXISTS idx_company_news_symbol_date ON company_news(symbol, public_date DESC);
