# Hướng dẫn toàn diện — Data Pipeline Chứng khoán Việt Nam

> Tài liệu này dành cho thành viên team muốn đọc hiểu, tùy chỉnh, hoặc tối ưu pipeline.
> Không yêu cầu kiến thức trước — chỉ cần biết Python cơ bản và SQL.

> Cập nhật: 2026-03-28 (migration 008 Approach C — 4 bảng BCTC riêng, RatioParser, ICB routing fix 87xx)

---

## Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Cấu trúc thư mục](#2-cấu-trúc-thư-mục)
3. [Luồng dữ liệu](#3-luồng-dữ-liệu)
4. [Cấu hình — `config/`](#4-cấu-hình----config)
5. [Cơ sở dữ liệu — `db/`](#5-cơ-sở-dữ-liệu----db)
6. [Tầng ETL — `etl/`](#6-tầng-etl----etl)
7. [Jobs — `jobs/`](#7-jobs----jobs)
8. [Scheduler — `scheduler/`](#8-scheduler----scheduler)
9. [Pipeline Real-time — `realtime/`](#9-pipeline-real-time----realtime)
10. [Tiện ích — `utils/`](#10-tiện-ích----utils)
11. [CLI — `main.py`](#11-cli----mainpy)
12. [Docker & Triển khai](#12-docker--triển-khai) — bao gồm [TimescaleDB (12.4)](#124-timescaledb)
13. [Cách tùy chỉnh & mở rộng](#13-cách-tùy-chỉnh--mở-rộng)
14. [Các lỗi thường gặp & cách xử lý](#14-các-lỗi-thường-gặp--cách-xử-lý)

---

## 1. Tổng quan

Pipeline thu thập dữ liệu chứng khoán Việt Nam từ nhiều nguồn (VCI, KBS, VNDirect, DNSE MDDS) và lưu vào **PostgreSQL**, phục vụ cho ứng dụng web phân tích.

Pipeline gồm **2 chế độ hoạt động:**

### Batch Pipeline (ETL theo lịch)

```
vnstock API (VCI / KBS / VNDirect)
        │
        ▼
  [Extractor]  ─── lấy dữ liệu thô (DataFrame)
        │
        ▼
  [Transformer] ─── chuẩn hóa, đổi tên cột, ép kiểu, xử lý lỗi
        │
        ▼
  [Validator]  ─── cross-check VCI vs KBS (BCTC), ghi flag bất thường
        │
        ▼
  [PostgresLoader] ─── INSERT ... ON CONFLICT DO UPDATE
        │
        ▼
   PostgreSQL (stockapp)
```

### Real-time Pipeline (MQTT Streaming)

```
DNSE MDDS (MQTT v5/WSS)
        │  OHLC candles (1m / 5m)
        ▼
  [MQTTSubscriber] ─── nhận tick/candle, publish vào Redis Streams
        │
        ▼
  Redis Streams  ─── buffer (max 500,000 messages, AOF persistent)
        │
        ▼
  [StreamProcessor] ─── validate, transform, batch upsert
        │
        ▼
   PostgreSQL → price_intraday
```

**7 batch jobs chính:**

| Module | Job | Dữ liệu | Lịch chạy |
|---|---|---|---|
| Listing | `sync_listing` | Danh mục mã, phân ngành ICB | Chủ Nhật 01:00 |
| Finance A | `sync_financials` | BCTC → `financial_reports` (Approach A — legacy) | Ngày 1 & 15 hàng tháng 03:00 |
| Finance C | `sync_financials_c` | BCTC + ratio → 4 bảng Approach C | Ngày 1 & 15 hàng tháng 04:00 |
| Company | `sync_company` | Cổ đông, lãnh đạo, công ty con, sự kiện | Thứ Hai 02:00 |
| Trading | `sync_ratios` | Snapshot tài chính mới nhất | Hàng ngày 18:30 |
| Price History | `sync_prices` | OHLCV lịch sử EOD (KBS primary + VNDirect fallback) | Thứ 2–6 lúc 19:00 |
| Alert | `alert_check` | Kiểm tra lỗi → gửi Telegram | Hàng giờ |

---

## 2. Cấu trúc thư mục

```
data-pipeline/
├── config/
│   ├── settings.py          ← Tất cả biến môi trường (đọc từ .env)
│   └── constants.py         ← Hằng số toàn cục (tên job, conflict keys, v.v.)
│
├── db/
│   ├── connection.py        ← SQLAlchemy engine, session factory
│   ├── models.py            ← ORM models (mirror schema DB)
│   ├── migrate.py           ← Chạy migration SQL files
│   └── migrations/
│       ├── 001_extensions.sql         ← CREATE EXTENSION timescaledb
│       ├── 002_reference_tables.sql   ← icb_industries (+ definition), companies (+ history, company_profile)
│       ├── 003_company_tables.sql     ← shareholders, officers, subsidiaries, corporate_events, ratio_summary
│       ├── 004_operational_tables.sql ← pipeline_logs, data_quality_flags, company_news
│       ├── 005_financial_reports.sql  ← financial_reports (bảng hợp nhất 3 loại BCTC × 4 ngành — Approach A)
│       ├── 006_price_tables.sql       ← price_history (EOD), price_intraday (1m/5m)
│       ├── 007_timescaledb.sql        ← Hypertables, retention/compression, cagg_ohlc_5m/1h/1d
│       └── 008_approach_c_schema.sql  ← fin_balance_sheet, fin_income_statement, fin_cash_flow, fin_financial_ratios
│
├── etl/
│   ├── base/
│   │   ├── extractor.py     ← Abstract BaseExtractor
│   │   ├── transformer.py   ← Abstract BaseTransformer
│   │   └── loader.py        ← Abstract BaseLoader
│   ├── extractors/
│   │   ├── listing.py       ← ListingExtractor (VND/VCI)
│   │   ├── finance.py       ← FinanceExtractor (VCI)
│   │   ├── company.py       ← CompanyExtractor (VCI)
│   │   ├── trading.py       ← TradingExtractor (VCI)
│   │   ├── dnse_price.py    ← KBSPriceExtractor (KBS qua vnstock Quote)
│   │   └── vndirect_price.py← VNDirectPriceExtractor (public REST API)
│   ├── transformers/
│   │   ├── listing.py       ← ListingTransformer
│   │   ├── finance_factory.py ← FinanceParserFactory (4 templates: non_financial/banking/securities/insurance)
│   │   ├── finance_parsers.py ← Parser implementations (bug fix: 0.0→None cho cột thiếu)
│   │   ├── mappings/        ← Field mappings per industry template
│   │   ├── approach_c/      ← Approach C parsers
│   │   │   ├── __init__.py  ← Export RatioParser, ApproachCFactory
│   │   │   ├── ratio_parser.py ← RatioParser (54 cols, decimal ROE, banking-only NIM/CAR/LDR)
│   │   │   └── factory.py   ← ApproachCFactory → (payloads, table_name)
│   │   ├── company.py       ← CompanyTransformer
│   │   ├── trading.py       ← TradingTransformer
│   │   ├── dnse_price.py    ← KBSPriceTransformer (KBS → price_history, ×1000 VND scale)
│   │   └── vndirect_price.py← VNDirectPriceTransformer (VND → price_history)
│   ├── validators/
│   │   └── cross_source.py  ← FinanceCrossValidator (VCI vs KBS, ngưỡng 2%)
│   └── loaders/
│       ├── helpers.py       ← sanitize_for_postgres, df_to_records, v.v.
│       ├── postgres.py      ← PostgresLoader (upsert engine)
│       └── approach_c_loader.py ← ApproachCLoader (wrapper → PostgresLoader cho 4 bảng Approach C)
│
├── jobs/
│   ├── sync_listing.py      ← Listing module end-to-end
│   ├── sync_financials.py   ← Finance module + cross-validation → financial_reports (Approach A)
│   ├── sync_financials_c.py ← BCTC + ratio → 4 bảng Approach C (fin_balance_sheet, ...)
│   ├── sync_company.py      ← Company module end-to-end
│   ├── sync_ratios.py       ← Trading module end-to-end
│   ├── sync_prices.py       ← Price history: KBS primary + VNDirect fallback
│   └── backfill.py          ← Re-sync dữ liệu lịch sử
│
├── realtime/
│   ├── __init__.py
│   ├── auth.py              ← DNSEAuthManager (JWT cache + 7h auto-refresh)
│   ├── watchlist.py         ← WatchlistManager (env → DB → VN30 fallback)
│   ├── session_guard.py     ← is_trading_hours() (Mon–Fri 08:45–15:10)
│   ├── subscriber.py        ← MQTTSubscriber → Redis Streams XADD
│   └── processor.py         ← StreamProcessor: Redis XREADGROUP → PostgreSQL
│
├── scheduler/
│   └── jobs.py              ← APScheduler: 6 batch jobs + 2 realtime lifecycle jobs
│
├── utils/
│   ├── logger.py            ← Loguru: log ra console + file
│   ├── retry.py             ← @vnstock_retry() decorator
│   ├── date_utils.py        ← Parse/format kỳ báo cáo (2024, 2024Q1)
│   ├── alert.py             ← Gửi Telegram
│   └── alert_checker.py     ← Kiểm tra pipeline_logs, kích hoạt alert
│
├── tests/
│   ├── realtime/
│   │   ├── test_auth.py         ← 4 tests DNSEAuthManager
│   │   ├── test_watchlist.py    ← 4 tests WatchlistManager
│   │   ├── test_session_guard.py← 8 tests parametrized
│   │   └── test_processor.py    ← 6 tests validate/transform
│   └── db/
│       └── test_timescale_migrations.py ← 21 tests kiểm tra SQL migrations 009–011
│
├── main.py                  ← CLI entry point (7 subcommands)
├── check_realtime.py        ← Smoke test: kiểm tra Redis streams + price_intraday
├── db/check_timescale.py    ← Health-check TimescaleDB sau migration (hypertables, CAggs, policies)
├── Dockerfile               ← Build image pipeline
├── docker-compose.yml       ← 5 services: postgres, redis, pipeline, rt-subscriber, rt-processor
├── entrypoint.sh            ← Startup script trong container
├── run_realtime_subscriber.bat  ← Windows launcher cho subscriber
├── run_realtime_processor.bat   ← Windows launcher cho processor
└── .env.example             ← Template biến môi trường
```

---

## 3. Luồng dữ liệu

### 3.1 Batch pipeline — từng bước chi tiết

```
main.py (CLI)
    └── jobs/sync_*.py
            ├── Lấy danh sách symbols từ DB (hoặc từ --symbol arg)
            └── ThreadPoolExecutor (5 luồng song song)
                    └── _run_one(symbol)
                            │
                            ├── [1] Extractor.extract(symbol)
                            │       └── Gọi vnstock API → DataFrame thô
                            │
                            ├── [2] Transformer.transform(df, symbol)
                            │       ├── Đổi tên cột (API name → DB name)
                            │       ├── Ép kiểu (float, int, date)
                            │       ├── Xử lý NaN/Inf/overflow
                            │       ├── Thêm metadata (symbol, fetched_at, v.v.)
                            │       └── Deduplicate conflict keys
                            │
                            ├── [3] PostgresLoader.load(df, table, ...)
                            │       ├── Reflect schema từ DB
                            │       ├── Filter cột hợp lệ
                            │       ├── Chunk 500 rows/batch
                            │       └── INSERT ... ON CONFLICT DO UPDATE
                            │
                            └── [4] PostgresLoader.load_log(...)
                                    └── Ghi kết quả vào pipeline_logs
```

### 3.2 Real-time pipeline — luồng MQTT → PostgreSQL

```
DNSE MDDS Broker (MQTT v5, WSS port 443)
        │
        │  topic: plaintext/quotes/krx/mdds/v2/ohlc/stock/{1}/{HPG}
        │         plaintext/quotes/krx/mdds/v2/ohlc/stock/{5}/{HPG}
        ▼
  MQTTSubscriber (realtime/subscriber.py)
        ├── Auth: DNSEAuthManager → JWT token (8h, auto-refresh mỗi 7h)
        ├── WatchlistManager → danh sách symbols (env/DB/VN30)
        ├── session_guard: chỉ connect trong 08:45–15:10 Thứ 2–6
        └── on_message: payload → Redis XADD (stream:ohlc:1m / stream:ohlc:5m)
                        maxlen=500,000, approximate=True
        │
        ▼
  Redis Streams (AOF persistent, 512mb max)
        │
        ▼
  StreamProcessor (realtime/processor.py)
        ├── XREADGROUP (consumer group: ohlc-processors, batch=100)
        ├── _validate_message(): kiểm tra field, resolution, close > 0
        ├── _transform_message(): ép kiểu int, thêm metadata
        ├── PostgresLoader.load() → price_intraday (upsert)
        ├── XACK khi thành công
        └── XAUTOCLAIM: reclaim message stuck > 30 phút
        │
        ▼
  PostgreSQL → price_intraday (symbol, time, resolution, open, high, low, close, volume)
```

### 3.3 Thứ tự phụ thuộc khi chạy lần đầu

```
sync_listing              ← phải chạy TRƯỚC (tạo icb_industries + companies)
    │
    ├── sync_financials   ← cần companies.symbol tồn tại (FK)
    ├── sync_company      ← cần companies.symbol tồn tại (FK)
    ├── sync_ratios       ← cần companies.symbol tồn tại (FK)
    └── sync_prices       ← cần companies.symbol tồn tại (FK)

realtime (subscriber + processor)  ← cần companies.symbol (FK price_intraday)
```

**Lý do:** Tất cả bảng dữ liệu đều có FK trỏ về `companies(symbol)`. INSERT trước khi có `companies` → FK violation.

---

## 4. Cấu hình — `config/`

### 4.1 `config/settings.py`

Tất cả cấu hình đọc từ file `.env` qua **pydantic-settings**. Không hard-code giá trị trong code.

```python
# Database
settings.database_url      # postgresql://user:pass@host:port/db (tự build)
settings.db_host           # Host PostgreSQL (default: localhost, Docker: "postgres")
settings.db_port           # Port PostgreSQL (default: 5432)
settings.db_name           # Tên database (default: stockapp)
settings.db_user           # User PostgreSQL (default: postgres)
settings.db_password       # Password PostgreSQL

# Redis (dùng cho real-time pipeline)
settings.redis_host        # Host Redis (default: localhost, Docker: "redis")
settings.redis_port        # Port Redis (default: 6379)

# Vnstock
settings.vnstock_source    # Nguồn data batch: "vci" (default)
settings.vnstock_api_key   # API key vnstock sponsor packages

# Pipeline tuning
settings.max_workers       # Số luồng song song (default: 5)
settings.request_delay     # Nghỉ giữa API calls (default: 0.3s)
settings.retry_attempts    # Số lần retry khi API lỗi (default: 3)
settings.retry_wait_min    # Chờ tối thiểu giữa retry (default: 1.0s)
settings.retry_wait_max    # Chờ tối đa — exponential backoff (default: 10.0s)
settings.db_chunk_size     # Rows/batch khi upsert (default: 500)

# Logging
settings.log_level         # DEBUG | INFO | WARNING | ERROR (default: INFO)
settings.log_dir           # Thư mục lưu file log (default: logs)

# Cron (Unix 5-field, Asia/Ho_Chi_Minh)
settings.cron_sync_listing       # default: "0 1 * * 0"     (CN 01:00)
settings.cron_sync_financials    # default: "0 3 1,15 * *"  (Ngày 1&15 03:00 — Approach A)
settings.cron_sync_financials_c  # default: "0 4 1,15 * *"  (Ngày 1&15 04:00 — Approach C, sau A)
settings.cron_sync_company       # default: "0 2 * * 1"     (T2 02:00)
settings.cron_sync_ratios        # default: "30 18 * * *"   (Hàng ngày 18:30)
settings.cron_sync_prices        # default: "0 19 * * 1-5"  (T2–6 19:00)
settings.cron_alert_check        # default: "0 * * * *"     (Hàng giờ)

# DNSE (dùng cho sync_prices và real-time)
settings.dnse_username     # Email/SĐT tài khoản DNSE (Entrade)
settings.dnse_password     # Mật khẩu DNSE

# Real-time pipeline
settings.realtime_watchlist    # CSV symbols, vd: "HPG,VCB,FPT". Rỗng = VN30 từ DB
settings.realtime_resolutions  # Timeframes, vd: "1,5" (1 phút, 5 phút)

# Alert
settings.telegram_bot_token
settings.telegram_chat_id
settings.alert_fail_threshold  # Số lần fail trước khi alert (default: 3)
```

**Thay đổi cấu hình:** Chỉ chỉnh file `.env`, không cần sửa code.

```env
# Ví dụ: tăng số luồng và giảm delay
MAX_WORKERS=10
REQUEST_DELAY=0.1

# Ví dụ: chỉ subscribe 5 mã real-time
REALTIME_WATCHLIST=HPG,VCB,FPT,VNM,VIC

# Ví dụ: thay đổi lịch sync_prices
CRON_SYNC_PRICES=30 18 * * 1-5
```

### 4.2 `config/constants.py`

```python
# Tên job (dùng trong pipeline_logs)
JOB_SYNC_LISTING      = "sync_listing"
JOB_SYNC_FINANCIALS   = "sync_financials"
JOB_SYNC_FINANCIALS_C = "sync_financials_c"   # Approach C
JOB_SYNC_COMPANY      = "sync_company"
JOB_SYNC_RATIOS       = "sync_ratios"
JOB_SYNC_PRICES       = "sync_prices"

# Conflict keys: cột nào dùng làm key cho ON CONFLICT
CONFLICT_KEYS = {
    "icb_industries":      ["icb_code"],
    "companies":           ["symbol"],
    # Approach A (legacy)
    "financial_reports":   ["symbol", "period", "period_type", "statement_type"],
    # Approach C (mới — 4 bảng riêng)
    "fin_balance_sheet":   ["symbol", "period", "period_type"],
    "fin_income_statement":["symbol", "period", "period_type"],
    "fin_cash_flow":       ["symbol", "period", "period_type"],
    "fin_financial_ratios":["symbol", "period", "period_type"],
    "ratio_summary":       ["symbol", "year_report", "quarter_report"],
    "shareholders":        ["symbol", "share_holder", "snapshot_date"],
    "officers":            ["symbol", "officer_name", "status", "snapshot_date"],
    "subsidiaries":        ["symbol", "organ_name", "snapshot_date"],
    "corporate_events":    ["symbol", "event_list_code", "record_date"],
    "company_news":        ["vci_id", "symbol"],
    "price_history":       ["symbol", "date", "source"],
    "price_intraday":      ["symbol", "time", "resolution"],
}

# Cột do server tự sinh — KHÔNG đưa vào INSERT/UPDATE
SERVER_GENERATED_COLS = {"id", "duration_ms", "created_at"}
```

---

## 5. Cơ sở dữ liệu — `db/`

### 5.1 Sơ đồ quan hệ

```
icb_industries (icb_code PK, icb_name, level, parent_code, definition)
    │
    └── companies (symbol PK, exchange, status, icb_code FK, history, company_profile)
            │
            ├── financial_reports   (symbol FK, period, period_type, statement_type,
            │                        template, 80+ numeric columns, raw_details JSONB)
            │                        ← Approach A (legacy): bảng hợp nhất balance_sheet /
            │                           income_statement / cash_flow × 4 ngành
            │
            ├── fin_balance_sheet   (symbol FK, period, period_type, template, 50+ cols)
            ├── fin_income_statement(symbol FK, period, period_type, template, 40+ cols)
            ├── fin_cash_flow       (symbol FK, period, period_type, template, 24+ cols)
            ├── fin_financial_ratios(symbol FK, period, period_type, roe, pe_ratio, nim,
            │                        car, ldr, casa, ... 48 cols ratio lịch sử)
            │                        ← Approach C (mới): 4 bảng riêng, UNIQUE (symbol, period, period_type)
            │
            ├── shareholders        (symbol FK, snapshot_date, share_holder, ...)
            ├── officers            (symbol FK, snapshot_date, officer_name, ...)
            ├── subsidiaries        (symbol FK, snapshot_date, organ_name, ...)
            ├── corporate_events    (symbol FK, event_list_code, record_date, ...)
            ├── company_news        (symbol FK, vci_id, public_date, news_title, ...)
            ├── ratio_summary       (symbol FK, year_report, quarter_report, ...)
            │
            ├── price_history       (symbol FK, date, source, open/high/low/close, ...)
            └── price_intraday      (symbol FK, time TIMESTAMPTZ, resolution, ohlc, ...)

pipeline_logs       (job_name, status, records_fetched, records_inserted, duration_ms, ...)
data_quality_flags  (symbol, table_name, period, column_name, diff_pct, flagged_at, ...)
```

### 5.2 Mô tả từng nhóm bảng

**Bảng tham chiếu:**

| Bảng | Mô tả | Số lượng row (~) |
|---|---|---|
| `icb_industries` | 4 cấp phân ngành ICB. Cột `definition TEXT` chứa mô tả chi tiết (chỉ có ở level 4, nguồn ICB FTSE Russell) | ~249 ngành |
| `companies` | Tất cả mã chứng khoán đang niêm yết. Cột `history TEXT` chứa lịch sử hình thành, `company_profile TEXT` chứa giới thiệu tổng quan — lấy từ `company.overview()` | ~1,550 mã |

**Báo cáo tài chính — Approach A (legacy)** (UNIQUE trên `(symbol, period, period_type, statement_type)`):

| Bảng | Mô tả | Cột đặc biệt |
|---|---|---|
| `financial_reports` | **Bảng hợp nhất** chứa balance_sheet + income_statement + cash_flow cho 4 loại ngành | `statement_type ENUM`, `template ENUM`, `raw_details JSONB` |

**Báo cáo tài chính — Approach C (mới)** (UNIQUE trên `(symbol, period, period_type)` mỗi bảng):

| Bảng | Mô tả | Số cột | Template hỗ trợ |
|---|---|---|---|
| `fin_balance_sheet` | Bảng cân đối kế toán | ~53 | non_financial, banking, securities, insurance |
| `fin_income_statement` | Kết quả kinh doanh | ~43 | non_financial, banking, securities, insurance |
| `fin_cash_flow` | Lưu chuyển tiền tệ | ~26 | non_financial, banking, securities, insurance |
| `fin_financial_ratios` | Chỉ số tài chính lịch sử (ROE, P/E, NIM, CAR, LDR…) | ~50 | tất cả |

Ưu điểm Approach C:
- Schema rõ ràng hơn, query nhanh hơn (không quét cột NULL thừa)
- `fin_financial_ratios` lưu ratio lịch sử — Approach A không có
- Cột thiếu = NULL thực sự (không bị điền 0.0 giả)

> `period` có dạng `"2024"` (năm) hoặc `"2024Q1"` (quý 1 năm 2024).
> Phân biệt ngành qua cột `template`: `non_financial` / `banking` / `securities` / `insurance`.

**Company intelligence:**

| Bảng | Mô tả |
|---|---|
| `shareholders` | Cổ đông lớn và % sở hữu |
| `officers` | Ban lãnh đạo, chức vụ, trạng thái |
| `subsidiaries` | Công ty con / công ty liên kết |
| `corporate_events` | Chia cổ tức, phát hành thêm, tách cổ phiếu |
| `company_news` | Tin tức doanh nghiệp từ VCI/FiinGroup — tiêu đề, nội dung HTML, link nguồn, giá cổ phiếu tại thời điểm đăng |
| `ratio_summary` | Snapshot tổng hợp chỉ số tài chính mới nhất |

**Giá cổ phiếu:**

| Bảng | Mô tả | Cột đặc biệt |
|---|---|---|
| `price_history` | OHLCV lịch sử EOD (cuối ngày) | `source` = 'kbs' hoặc 'vndirect'; `close_adj` (adjusted close, NULL nếu KBS) |
| `price_intraday` | OHLC real-time 1m/5m từ DNSE MDDS | `resolution` = 1 hoặc 5; `time TIMESTAMPTZ` |

**Vận hành & chất lượng dữ liệu:**

| Bảng | Mô tả |
|---|---|
| `pipeline_logs` | Lịch sử chạy job: thành công/thất bại, số records, thời gian |
| `data_quality_flags` | Flag bất thường từ cross-validation VCI vs KBS (diff > 2%) |

### 5.3 Cột `raw_details JSONB`

Bảng `financial_reports` có cột `raw_details` lưu **toàn bộ dữ liệu gốc từ API**:

1. **Drill-down:** Web app đọc `raw_data` để hiển thị thêm chỉ số không trong schema chuẩn.
2. **Recovery:** Nếu schema thay đổi, dữ liệu gốc vẫn còn — không cần re-fetch từ API.

### 5.4 Chạy migration

```bash
# Lần đầu tiên (tạo toàn bộ schema, 001→008)
python -m db.migrate

# Docker tự chạy khi init lần đầu (mount: ./db/migrations:/docker-entrypoint-initdb.d)

# Kiểm tra sau khi chạy migrations TimescaleDB (007)
python -m db.check_timescale
```

### 5.5 `db/connection.py`

```python
from db.connection import engine, get_session

# Dùng engine trực tiếp (raw SQL)
with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM companies"))

# Dùng session (ORM)
with get_session() as session:
    companies = session.query(Company).filter_by(exchange="HOSE").all()
```

---

## 6. Tầng ETL — `etl/`

### 6.1 Base classes

```
BaseExtractor  → abstract: extract(symbol, **kwargs) → DataFrame | None
BaseTransformer → abstract: transform(df, symbol, **context) → DataFrame
BaseLoader     → abstract: load(df, table, conflict_columns, update_columns) → int
```

Thiết kế này đảm bảo mỗi module swap độc lập — ví dụ: thay PostgresLoader bằng BigQueryLoader mà không đụng extractors/transformers.

### 6.2 Extractors

Tất cả kế thừa `BaseExtractor` và dùng `@vnstock_retry()` để tự retry khi API lỗi.

**`ListingExtractor`** — `etl/extractors/listing.py`

```python
extractor = ListingExtractor(source="vnd")  # PHẢI dùng "vnd" — "vci" thiếu cột
df_symbols    = extractor.extract_symbols()       # ~1,550 rows
df_industries = extractor.extract_industries()    # ~200 rows (vnstock API — fallback)

# ICB từ file JSON cục bộ (cách chính — 249 records, đầy đủ hơn API)
records = extractor.load_icb_from_json()          # list[dict], cấu trúc 4 cấp
# Mỗi record: icb_code, icb_name, level, parent_code, definition (level 4 only)
# File: docs/icb-industries.json (nguồn: ICB FTSE Russell, 4-level hierarchy)
```

**`FinanceExtractor`** — `etl/extractors/finance.py`

```python
extractor = FinanceExtractor(source="vci")
df = extractor.extract(symbol="HPG", report_type="balance_sheet")
# report_type: "balance_sheet" | "income_statement" | "cash_flow" | "ratio"
```

**`CompanyExtractor`** — `etl/extractors/company.py`

```python
extractor = CompanyExtractor(source="vci")
df_overview     = extractor.extract_overview(symbol)
df_shareholders = extractor.extract_shareholders(symbol)
df_officers     = extractor.extract_officers(symbol)
df_subsidiaries = extractor.extract_subsidiaries(symbol)
df_events       = extractor.extract_events(symbol)
df_news         = extractor.extract_news(symbol)    # Tin tức → company_news
```

Hoặc dùng dispatch method:

```python
df = extractor.extract(symbol, data_type="news")
# data_type: "overview" | "shareholders" | "officers" | "subsidiaries" | "events" | "news"
```

**`TradingExtractor`** — `etl/extractors/trading.py`

```python
extractor = TradingExtractor(source="vci")
df = extractor.extract_ratio_summary(symbol)
# Trả về None nếu API không có dữ liệu (bình thường với ~22 mã)
```

**`DNSEPriceExtractor`** — `etl/extractors/dnse_price.py`

```python
from etl.extractors.dnse_price import DNSEPriceExtractor
ext = DNSEPriceExtractor()
df = ext.extract_price_history("HPG", start=date(2024,1,1), end=date(2024,12,31))
# Dùng KBS qua vnstock Quote(source='kbs').history(...)
# Trả về: time, open, high, low, close, volume (đơn vị: nghìn VND — transformer nhân ×1000)
```

**`VNDirectPriceExtractor`** — `etl/extractors/vndirect_price.py`

```python
from etl.extractors.vndirect_price import VNDirectPriceExtractor
ext = VNDirectPriceExtractor()
df = ext.extract_price_history("HPG", start=date(2024,1,1), end=date(2024,12,31))
# Gọi REST public: https://finfo-api.vndirect.com.vn/v4/stock_prices/
# Trả về: time, open, high, low, close, adClose, volume, nmVolume, value
# Pagination 500 records/page tự động
```

### 6.3 Transformers

**`DNSEPriceTransformer`** — `etl/transformers/dnse_price.py`

- `_NEEDS_SCALE = True` — KBS trả nghìn VND → nhân ×1000
- `close_adj = NULL` (KBS không cung cấp adjusted close)
- `source = "kbs"`

**`VNDirectPriceTransformer`** — `etl/transformers/vndirect_price.py`

- `adClose` → `close_adj` (VNDirect có adjusted close)
- `nmVolume` → `volume_nm`, `value` → `value`
- `source = "vndirect"`

**`FinanceTransformer`** — `etl/transformers/finance.py`

Phân tích kỳ báo cáo từ index:
- `"2024"` → `period="2024"`, `period_type="year"`
- `"Q1/2024"` → `period="2024Q1"`, `period_type="quarter"`

**`TradingTransformer`** — `etl/transformers/trading.py`

Xử lý tên cột viết tắt đặc thù:
```python
_RENAME_MAP = {
    "de": "debt_to_equity", "at": "asset_turnover",
    "fat": "fixed_asset_turnover", "dso": "receivable_days",
    "ccc": "cash_conversion_cycle", "ev_per_ebitda": "ev_ebitda",
    ...
}
```
Cột lạ không có trong schema → gom vào `extra_metrics JSONB`.

### 6.4 Validator — `etl/validators/cross_source.py`

```python
from etl.validators.cross_source import FinanceCrossValidator

validator = FinanceCrossValidator()
flags = validator.validate_symbol("HPG")
# So sánh VCI (từ DB) vs KBS (fetch mới qua vnstock)
# Các bảng: balance_sheets, income_statements, cash_flows
# Flag khi |VCI - KBS×1000| / |VCI| × 100 > 2%
# Ghi vào data_quality_flags
# Trả về: số flags mới tìm thấy
```

Validator được gọi tự động trong `sync_financials` sau khi sync xong đủ 3 loại BCTC cho 1 symbol.

### 6.5 PostgresLoader — `etl/loaders/postgres.py`

```python
loader = PostgresLoader()
rows_affected = loader.load(
    df=df_transformed,
    table="balance_sheets",
    conflict_columns=["symbol", "period", "period_type"],
    update_columns=["revenue", "net_profit", "fetched_at", ...],
)
```

**Cách hoạt động:**
1. `MetaData().reflect(engine, only=[table])` — lấy schema thực từ DB
2. Filter DataFrame chỉ giữ cột có trong schema
3. `sanitize_for_postgres(df)` — chuyển NaN/NaT/Inf → None
4. Chia thành chunks 500 rows
5. `pg_insert(table).values(records).on_conflict_do_update(...)`
6. `load_log()` — ghi kết quả vào `pipeline_logs`

---

## 7. Jobs — `jobs/`

Mỗi job là module độc lập với hàm `run()` làm entry point.

### 7.1 `sync_listing.py`

```python
result = run()
# result = {"icb_industries": 249, "companies": 1981}
```

Chạy tuần tự (không song song): `icb_industries` trước, `companies` sau (FK dependency).

**Nguồn ICB:** Dữ liệu ngành ICB nạp từ **file JSON cục bộ** `docs/icb-industries.json` thay vì vnstock API. File JSON chứa 249 records đầy đủ 4 cấp phân ngành (ICB FTSE Russell), bao gồm cả cột `definition` cho ngành cấp 4. API vnstock chỉ trả ~200 records và thiếu `definition`.

### 7.2 `sync_financials.py`

```python
result = run(
    symbols=["HPG", "VCB"],   # None = tất cả mã
    max_workers=5,
    report_types=["balance_sheet", "income_statement"],  # None = cả 4 loại
)
# result = {"success": 8, "failed": 0, "skipped": 0, "rows": 1240, "flags": 2}
```

Mỗi `(symbol, report_type)` = 1 task trong ThreadPoolExecutor. Sau khi cả 3 loại BCTC của 1 symbol thành công → tự động gọi `FinanceCrossValidator`.

### 7.3 `sync_financials_c.py` (Approach C)

```python
result = run(
    symbols=["HPG", "VCB"],   # None = tất cả mã
    max_workers=5,
    report_types=["balance_sheet", "income_statement", "cash_flow", "ratio"],  # None = cả 4
)
# result = {"success": 8, "failed": 0, "skipped": 0, "rows": 1589}
```

Ghi dữ liệu vào **4 bảng Approach C** thay vì `financial_reports`. Sử dụng `ApproachCFactory` để:
- `"balance_sheet"` → `FinanceParserFactory` → `fin_balance_sheet`
- `"income_statement"` → `FinanceParserFactory` → `fin_income_statement`
- `"cash_flow"` → `FinanceParserFactory` → `fin_cash_flow`
- `"ratio"` → `RatioParser` → `fin_financial_ratios`

**ICB routing:** `FinanceParserFactory._resolve_parser()` xác định ngành từ `icb_code`. Hỗ trợ:
- FTSE 8 chữ số: `3010xxxx` → Banking, `3030xxxx` → Insurance, `3020xxxx` → Securities
- Legacy 4 chữ số: `83xx` → Banking, `84xx`/`8536` → Insurance, `85xx`/`87xx` → Securities

> **Bug fix (2026-03-28):** Mã ICB `87xx` (vd: `8777` = Môi giới CK) trước đây không được nhận dạng, gây ra việc SSI và các CTCK dùng `NonFinancialParser` sai. Đã sửa bằng cách thêm `prefix2 == "87"` → SecuritiesParser.

```bash
# Pilot test 5 mã
python main.py sync_financials_c --symbol HPG VCB SSI BVH VNM

# Full sync tất cả mã, chỉ ratio
python main.py sync_financials_c --report-type ratio
```

### 7.4 `sync_company.py`

```python
result = run(symbols=None, max_workers=5)
```

**Hai pha:**
- **Pha A (tuần tự):** `UPDATE companies` từ `company.overview()` — cập nhật `icb_code`, `charter_capital`, `issue_share`, `history`, `company_profile`. Dùng `COALESCE` để không xóa giá trị cũ nếu API trả về NULL.
- **Pha B (song song):** Upsert 5 loại dữ liệu: `shareholders`, `officers`, `subsidiaries`, `events`, `news`

> Tách 2 pha để tránh deadlock khi nhiều luồng cùng UPDATE 1 bảng.

**`news` (company_news):** Lấy ~10 tin tức mới nhất từ `company.news()`. Cột đặc biệt:
- `vci_id` (BIGINT) — ID bài viết từ VCI/FiinGroup, dùng làm conflict key
- `public_date` (TIMESTAMPTZ) — chuyển đổi từ Unix milliseconds trong API
- `news_full_content` (TEXT) — nội dung HTML đầy đủ
- `close_price`, `ref_price`, `floor_price`, `ceiling_price`, `price_change_pct` — giá tại thời điểm đăng

```bash
# Chỉ sync tin tức cho 2 mã
python main.py sync_company --symbols HPG VCB --data-types news --no-overview

# Tất cả 5 loại dữ liệu (mặc định)
python main.py sync_company
```

### 7.5 `sync_ratios.py`

```python
result = run(symbols=None, max_workers=5)
# result = {"success": 1526, "failed": 0, "skipped": ~22, "rows": ~7630}
```

Job đơn giản nhất: 1 extractor → 1 transformer → 1 loader. Chạy hàng ngày 18:30.

> **Thực tế (2026-03-24):** 1,526 symbols có ratio_summary, ~22 mã bị skip (API không trả data — bình thường với mã ít thanh khoản).

### 7.6 `sync_prices.py`

```python
result = run(
    symbols=["HPG", "VCB"],   # None = tất cả mã đang niêm yết
    max_workers=5,
    full_history=False,        # True = fetch lại 5 năm (bỏ qua incremental)
)
# result = {"success": 2, "failed": 0, "skipped": 0, "rows": 1460, "kbs": 2, "vndirect": 0}
```

**Incremental sync:**
- Mỗi run query `MAX(date)` per symbol từ `price_history`
- Fetch từ ngày tiếp theo đến hôm nay
- Lần đầu (NULL → `full_history`): fetch 5 năm lịch sử

**Nguồn và fallback:**
- **Primary:** KBS qua vnstock `Quote(source='kbs').history()`
- **Fallback tự động:** VNDirect nếu KBS lỗi hoặc trả về rỗng
- Transformer được chọn tương ứng với source thực tế dùng

```bash
# Test 3 mã
python main.py sync_prices --symbol HPG VCB FPT

# Initial load đầy đủ (~1h cho toàn bộ ~1,550 mã)
python main.py sync_prices --full-history
```

---

## 8. Scheduler — `scheduler/`

### 8.1 `scheduler/jobs.py`

```python
from scheduler.jobs import build_scheduler
scheduler = build_scheduler()
scheduler.start()  # Blocking
```

**9 jobs đã đăng ký (Asia/Ho_Chi_Minh):**

| Job ID | Cron | Lịch | misfire_grace_time |
|---|---|---|---|
| `sync_listing` | `0 1 * * 0` | CN 01:00 | 1 giờ |
| `sync_financials` | `0 3 1,15 * *` | Ngày 1&15 03:00 (Approach A) | 1 giờ |
| `sync_financials_c` | `0 4 1,15 * *` | Ngày 1&15 04:00 (Approach C) | 1 giờ |
| `sync_company` | `0 2 * * 1` | T2 02:00 | 1 giờ |
| `sync_ratios` | `30 18 * * *` | Hàng ngày 18:30 | 30 phút |
| `sync_prices` | `0 19 * * 1-5` | T2–6 19:00 | 1 giờ |
| `alert_check` | `0 * * * *` | Hàng giờ | 5 phút |
| `realtime_subscriber_start` | `0 7 * * 1-5` | T2–6 07:00 | 30 phút |
| `realtime_subscriber_stop` | `15 15 * * 1-5` | T2–6 15:15 | 30 phút |

Ngoài ra, **StreamProcessor** khởi động ngay khi `build_scheduler()` được gọi (daemon thread, chạy 24/7).

**`misfire_grace_time`:** Nếu scheduler bị dừng và job bỏ lỡ, APScheduler chạy bù nếu trễ ≤ grace time. Trễ hơn → bỏ qua.

**`_safe_run()` wrapper:** Đảm bảo 1 job lỗi không crash toàn bộ scheduler.

**`REALTIME_ENABLED=false`:** Tắt hoàn toàn realtime pipeline (2 lifecycle jobs + processor không khởi động).

### 8.2 Thay đổi lịch chạy

Cron đọc từ `.env` — chỉ cần thay đổi file `.env`:

```env
# sync_prices chạy lúc 18:30 thay vì 19:00
CRON_SYNC_PRICES=30 18 * * 1-5

# sync_ratios chạy mỗi nửa giờ (test)
CRON_SYNC_RATIOS=*/30 * * * *
```

---

## 9. Pipeline Real-time — `realtime/`

### 9.1 Tổng quan kiến trúc

Pipeline real-time nhận OHLC candle 1m/5m từ DNSE MDDS (MQTT v5 over WebSocket Secure) → đẩy vào Redis Streams → xử lý batch upsert vào PostgreSQL.

**Công nghệ:**
- **DNSE MDDS:** MQTT v5, broker `datafeed-lts-krx.dnse.com.vn:443`, JWT auth
- **paho-mqtt v2:** CallbackAPIVersion.VERSION2
- **Redis Streams:** XADD, XREADGROUP, XACK, XAUTOCLAIM
- **Session Guard:** Chỉ hoạt động T2–6, 08:45–15:10 ICT

### 9.2 `realtime/auth.py` — DNSEAuthManager

```python
from realtime.auth import DNSEAuthManager

mgr = DNSEAuthManager(username=settings.dnse_username, password=settings.dnse_password)
token = mgr.get_token()          # Fetch + cache JWT, tự refresh khi còn < 1h
investor_id = mgr.get_investor_id()  # investorId DNSE (dùng làm MQTT client ID)
mgr.invalidate()                 # Force refresh token (gọi khi MQTT auth lỗi)
```

- Token TTL: 8h. Refresh threshold: còn < 1h → tự fetch lại.
- Subscriber background thread gọi `invalidate()` + `disconnect()` mỗi 7h để reconnect với token mới.

### 9.3 `realtime/watchlist.py` — WatchlistManager

```python
from realtime.watchlist import WatchlistManager

wl = WatchlistManager()
symbols = wl.get_symbols()  # list[str], đã deduplicate
```

**Thứ tự ưu tiên:**
1. `REALTIME_WATCHLIST` trong `.env` (CSV, ví dụ: `"HPG,VCB,FPT"`)
2. Query DB: `SELECT symbol FROM companies WHERE status='listed' AND index_code LIKE '%VN30%'`
3. **Fallback hardcode:** 30 mã VN30 nếu DB lỗi hoặc không có cột `index_code`

> **Lưu ý (2026-03-24):** Bảng `companies` hiện **chưa có cột `index_code`** → DB query luôn fail và rơi vào fallback VN30 hardcode. Đây là behavior đúng — 30 mã vẫn subscribe đủ. Cần thêm migration để đồng bộ `index_code` từ vnstock nếu muốn watchlist tự động cập nhật.

### 9.4 `realtime/session_guard.py`

```python
from realtime.session_guard import is_trading_hours

is_trading_hours()  # True nếu Thứ 2–6, 07:00 ≤ now ≤ 15:10 (Asia/Ho_Chi_Minh)
```

```python
# realtime/session_guard.py
_SESSION_START = time(7, 0)    # Khởi động sớm để kết nối MQTT trước ATO
_SESSION_END   = time(15, 10)  # Đóng 10 phút sau ATC
```

Session guard được dùng trong 2 ngữ cảnh:
- `__main__` block của `subscriber.py`: thoát ngay nếu ngoài giờ (Docker restart và kiểm tra lại)
- Khi chạy qua `python main.py schedule`: APScheduler tự start/stop subscriber theo cron `07:00` / `15:15`

### 9.5 `realtime/subscriber.py` — MQTTSubscriber

```bash
# Chạy subscriber
python -m realtime.subscriber
# hoặc trên Windows:
run_realtime_subscriber.bat
```

**Topics subscribe:**
```
plaintext/quotes/krx/mdds/v2/ohlc/stock/1/{symbol}   # candle 1 phút
plaintext/quotes/krx/mdds/v2/ohlc/stock/5/{symbol}   # candle 5 phút
```

**Xử lý message:**
- Parse JSON payload
- Thêm `received_at` timestamp
- Chuyển tất cả giá trị sang `str` (Redis Streams yêu cầu)
- `XADD stream:ohlc:1m` hoặc `stream:ohlc:5m`, `maxlen=500,000`

**JWT auto-refresh:** Background daemon thread, `invalidate()` + `disconnect()` mỗi 7h → trigger reconnect với token mới.

**Reconnect backoff:** 1s → 5s → 30s → 300s khi mất kết nối.

### 9.6 `realtime/processor.py` — StreamProcessor

```bash
# Chạy processor
python -m realtime.processor
# hoặc trên Windows:
run_realtime_processor.bat
```

**Consumer group:** `ohlc-processors` (hỗ trợ scale ngang nhiều processor)

**Luồng xử lý:**
```python
# Validate (pure function — dễ test)
_validate_message(msg)  # Kiểm tra: required fields, resolution hợp lệ, close > 0

# Transform (pure function — dễ test)
_transform_message(msg)  # int(round(float(...))), source="dnse_mdds"

# Batch upsert
PostgresLoader.load(batch_df, "price_intraday", ...)

# ACK chỉ khi thành công
redis.xack(stream, group, message_id)
# KHÔNG ACK nếu DB lỗi → message sẽ được XAUTOCLAIM lại
```

**XAUTOCLAIM:** Sau 30 phút, reclaim message đang pending (processor crash giữa chừng).

### 9.7 Smoke test

```bash
# Bước 1: Start infrastructure
docker compose up -d postgres redis

# Bước 2: Chạy 2 terminals
run_realtime_processor.bat    # terminal 1
run_realtime_subscriber.bat   # terminal 2

# Bước 3: Kiểm tra sau 5 phút
python check_realtime.py
```

`check_realtime.py` kiểm tra:
- Redis ping + độ dài `stream:ohlc:1m`, `stream:ohlc:5m`
- Rows trong `price_intraday` (symbol, resolution, candle range)

> Chạy trong giờ giao dịch (T2–6, **07:00–15:10** ICT). Dữ liệu candle thực bắt đầu sau ATO (09:00).

**Kết quả smoke test 2026-03-24 (pre-market, 07:26 ICT):**

| Hạng mục | Kết quả |
|---|---|
| JWT Auth DNSE | ✅ PASS — `investorId=1002161780` |
| MQTT Connection | ✅ PASS — kết nối `datafeed-lts-krx.dnse.com.vn:443` |
| Topic Subscribe | ✅ PASS — 60 topics (30 VN30 × 1m + 5m) |
| Redis Consumer Groups | ✅ PASS — `ohlc-processors` tạo thành công |
| Stream Processor | ✅ PASS — `worker-MSI-*` khởi động |
| Watchlist DB | ⚠️ Fallback — cột `index_code` chưa có → dùng VN30 hardcode (không blocking) |
| Data flow (trong giờ) | ⏳ Chờ xác nhận sau ATO 09:00 |

Xem chi tiết: `docs/smoke_test_realtime_2026-03-24.md`

---

## 10. Tiện ích — `utils/`

### 10.1 `utils/logger.py`

```python
from utils.logger import logger

logger.debug("Chi tiết debug")
logger.info("Thông tin thường")
logger.warning("Cảnh báo")
logger.error("Lỗi nghiêm trọng")
logger.success("Thành công")
```

Log ghi ra **2 nơi đồng thời:**
- Console: có màu, dễ đọc khi debug
- File: `logs/pipeline_YYYY-MM-DD.log`, xoay hàng ngày, giữ 30 ngày, nén `.zip`

```env
LOG_LEVEL=DEBUG   # DEBUG | INFO | WARNING | ERROR
```

### 10.2 `utils/retry.py`

```python
from utils.retry import vnstock_retry

@vnstock_retry()
def my_api_call(symbol):
    return api.get_data(symbol)

# Tùy chỉnh
@vnstock_retry(attempts=5, wait_min=2.0, wait_max=30.0)
def my_slow_api_call(symbol):
    ...
```

Dùng **tenacity**, exponential backoff. Mặc định: 3 lần retry, chờ 1–10 giây.

> Chỉ retry khi có **exception thực sự**. API trả về `None` hay DataFrame rỗng = kết quả hợp lệ — không retry.

### 10.3 `utils/date_utils.py`

```python
from utils.date_utils import to_period, parse_period, get_period_type

to_period(2024, 0)  # → "2024"
to_period(2024, 1)  # → "2024Q1"
parse_period("2024Q3")  # → (2024, 3)
get_period_type("2024Q1")  # → "quarter"
```

### 10.4 Alert Telegram — `utils/alert.py` & `utils/alert_checker.py`

**Thiết lập:**
1. Tạo bot qua @BotFather → lấy `TELEGRAM_BOT_TOKEN`
2. Nhắn tin cho bot → gọi `getUpdates` → lấy `TELEGRAM_CHAT_ID`
3. Điền vào `.env`

```bash
# Test thủ công
python -c "from utils.alert import send_telegram; send_telegram('test pipeline alert')"
```

`alert_checker` chạy mỗi giờ, query `pipeline_logs`:
```sql
SELECT job_name, COUNT(*) AS fail_count
FROM pipeline_logs
WHERE status = 'failed' AND started_at >= NOW() - INTERVAL '24 hours'
GROUP BY job_name
HAVING COUNT(*) >= 3
```
Nếu có kết quả → gửi Telegram.

---

## 11. CLI — `main.py`

```bash
# Help
python main.py --help
python main.py sync_prices --help

# Batch jobs thủ công
python main.py sync_listing
python main.py sync_financials
python main.py sync_financials --symbol HPG VCB FPT
python main.py sync_financials --symbol HPG --workers 3

# Approach C — 4 bảng riêng + ratio
python main.py sync_financials_c --symbol HPG VCB SSI BVH VNM   # pilot test
python main.py sync_financials_c --report-type ratio             # chỉ sync ratio
python main.py sync_financials_c                                 # full sync tất cả mã
python main.py sync_company
python main.py sync_ratios --symbol HPG VCB

# Price history
python main.py sync_prices --symbol HPG VCB FPT   # test 3 mã
python main.py sync_prices --full-history           # initial load ~1h

# Scheduler (production)
python main.py schedule

# Scheduler (batch + realtime pipeline cùng lúc)
python main.py schedule

# Real-time standalone (debug / test ngoài scheduler)
python -m realtime.processor    # Terminal 1 — chạy 24/7
python -m realtime.subscriber   # Terminal 2 — chỉ active T2–6 nếu dùng __main__
```

---

## 12. Docker & Triển khai

### 12.1 Cấu trúc Docker — 5 services

```
docker-compose.yml
├── postgres  (timescale/timescaledb:latest-pg16)
│   ├── Tự chạy db/migrations/ khi init lần đầu (001→008)
│   ├── Dữ liệu trong volume postgres_data
│   └── Expose port 5432
│
├── redis  (redis:7-alpine)
│   ├── AOF persistence (appendonly yes)
│   ├── maxmemory 512mb, policy allkeys-lru
│   ├── Dữ liệu trong volume redis_data
│   └── Expose port 6379
│
├── pipeline  (build từ Dockerfile)
│   ├── entrypoint: entrypoint.sh  ← cài vnstock_data, check PG, chạy scheduler
│   ├── build arg: VNSTOCK_API_KEY (cài vnstock_data tại build time)
│   ├── command: python main.py schedule
│   ├── Depends on: postgres (healthy)
│   └── Mount ./logs → /app/logs
│
├── realtime-subscriber  (build từ Dockerfile)
│   ├── entrypoint: entrypoint_realtime.sh  ← KHÔNG cài vnstock (không cần)
│   ├── VNSTOCK_API_KEY="" (override — tránh tiêu thụ OS slot)
│   ├── command: python -m realtime.subscriber
│   ├── Depends on: postgres (healthy), redis (healthy)
│   └── Mount ./logs → /app/logs
│
└── realtime-processor  (build từ Dockerfile)
    ├── entrypoint: entrypoint_realtime.sh  ← KHÔNG cài vnstock (không cần)
    ├── VNSTOCK_API_KEY="" (override — tránh tiêu thụ OS slot)
    ├── command: python -m realtime.processor
    ├── Depends on: postgres (healthy), redis (healthy)
    ├── replicas: 1  (có thể scale lên)
    └── Mount ./logs → /app/logs
```

> **Quan trọng — giới hạn vnstock API key:** Gói Golden chỉ cho phép **2 thiết bị/OS** dùng cùng lúc. Nếu cả 3 containers đều chạy vnstock installer → vượt giới hạn. Giải pháp: chỉ `pipeline` dùng `entrypoint.sh` (cài vnstock); `realtime-subscriber` và `realtime-processor` dùng `entrypoint_realtime.sh` (bỏ qua installer, không dùng vnstock).

### 12.2 Lệnh vận hành thường dùng

```bash
# Khởi động đầy đủ lần đầu
docker compose up -d --build

# Chỉ khởi động batch pipeline (không real-time)
docker compose up -d postgres redis pipeline

# Xem log realtime
docker compose logs -f pipeline
docker compose logs -f realtime-subscriber
docker compose logs -f realtime-processor

# Chạy thủ công job trong container
docker compose exec pipeline python main.py sync_prices --symbol HPG VCB FPT

# Smoke test real-time (trong giờ giao dịch)
docker compose exec pipeline python check_realtime.py

# Scale processor lên 2 instances
docker compose up -d --scale realtime-processor=2

# Rebuild sau khi sửa code (giữ nguyên DB và Redis)
docker compose up -d --build pipeline realtime-subscriber realtime-processor

# Dừng (giữ dữ liệu)
docker compose down

# Reset toàn bộ (xóa cả DB và Redis)
docker compose down -v
```

### 12.3 Kết nối từ Web Application

```sql
-- Chạy 1 lần sau khi deploy
CREATE USER webapp_readonly WITH PASSWORD 'webapp_password';
GRANT CONNECT ON DATABASE stockapp TO webapp_readonly;
GRANT USAGE ON SCHEMA public TO webapp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO webapp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO webapp_readonly;
```

Connection string:
```
postgresql://webapp_readonly:<password>@<server_ip>:5432/stockapp
```

### 12.4 TimescaleDB

Docker image `timescale/timescaledb:latest-pg16` (thay thế `postgres:16-alpine`) tích hợp extension TimescaleDB 2.9+ sẵn sàng sử dụng.

**Migrations liên quan (009–011):**

| Migration | Mô tả |
|---|---|
| `006_price_tables.sql` | Tạo `price_history` (EOD) và `price_intraday` (1m/5m) với composite PK, indexes |
| `007_timescaledb.sql` | Hypertables, retention (180 ngày intraday), compression (7 ngày), continuous aggregates phân cấp |

**Continuous aggregates (hierarchical):**

```
price_intraday (1m raw, WHERE resolution = 1)
    └── cagg_ohlc_5m   (materialized_only = TRUE)   ← refresh mỗi 1 phút
            └── cagg_ohlc_1h  (materialized_only = TRUE)   ← refresh mỗi 5 phút
                    └── cagg_ohlc_1d  (materialized_only = FALSE)  ← refresh mỗi giờ
```

> `materialized_only = FALSE` ở leaf CAgg (`cagg_ohlc_1d`) cho phép đọc nến ngày hiện tại theo real-time.

**Kiểm tra sau migration:**

```bash
python -m db.check_timescale
# Kiểm tra: extension, hypertables, retention/compression policies, continuous aggregates
```

---

## 13. Cách tùy chỉnh & mở rộng

### 13.1 Thêm cột mới vào bảng BCTC

**Ví dụ:** Thêm `working_capital` vào balance sheet.

**Bước 1:** Tạo migration mới `008_add_working_capital.sql`:
```sql
ALTER TABLE balance_sheets ADD COLUMN working_capital BIGINT;
```

**Bước 2:** Thêm mapping trong `etl/transformers/finance.py`:
```python
_BS_COL_MAP = {
    ...
    "vốn lưu động": "working_capital",
}
```

**Bước 3:** Chạy migration và backfill:
```bash
python -m db.migrate
python main.py sync_financials
```

### 13.2 Thêm data_type mới vào sync_company

Nếu loại dữ liệu mới thuộc về doanh nghiệp (tương tự shareholders, news), cách đơn giản nhất là mở rộng `sync_company` thay vì tạo job mới:

**Bước 1:** Thêm migration (`db/migrations/`):
```sql
CREATE TABLE IF NOT EXISTS company_reports (
    id BIGSERIAL PRIMARY KEY,
    ...
    UNIQUE (report_id, symbol)
);
```

**Bước 2:** Thêm `extract_reports()` vào `CompanyExtractor` và `transform_reports()` vào `CompanyTransformer` (bao gồm cập nhật dispatch trong `extract()` và `transform()`).

**Bước 3:** Cập nhật `config/constants.py`:
```python
CONFLICT_KEYS["company_reports"] = ["report_id", "symbol"]
```

**Bước 4:** Cập nhật `jobs/sync_company.py`:
```python
_DATA_TYPES = [..., "reports"]
_TABLE_MAP  = {..., "reports": "company_reports"}
```

Nếu cần **job riêng** (lịch chạy khác, không liên quan companies), tạo module độc lập và đăng ký vào `scheduler/jobs.py` tương tự các job hiện có.

### 13.3 Tăng hiệu năng

| Tham số | Mặc định | Khi nào nên tăng |
|---|---|---|
| `MAX_WORKERS` | 5 | VPS nhiều CPU, API không rate-limit |
| `DB_CHUNK_SIZE` | 500 | RAM nhiều, cần batch write nhanh hơn |
| `REQUEST_DELAY` | 0.3s | Giảm nếu API không throttle |
| `realtime-processor replicas` | 1 | Khi message lag tăng cao |

> **Cảnh báo:** Tăng `MAX_WORKERS` quá cao → vnstock rate-limit hoặc ban IP. Bắt đầu từ 8–10 và test trước.

### 13.4 Theo dõi pipeline_logs

```sql
-- 20 lần chạy gần nhất
SELECT job_name, status, records_success, records_failed, duration_ms, started_at
FROM pipeline_logs
ORDER BY started_at DESC LIMIT 20;

-- Đếm lỗi 7 ngày qua
SELECT job_name, COUNT(*) as fail_count
FROM pipeline_logs
WHERE status = 'failed' AND started_at >= NOW() - INTERVAL '7 days'
GROUP BY job_name ORDER BY fail_count DESC;

-- Kiểm tra data quality flags
SELECT symbol, table_name, column_name, diff_pct, flagged_at
FROM data_quality_flags WHERE resolved = FALSE
ORDER BY diff_pct DESC LIMIT 20;

-- Candle real-time mới nhất
SELECT symbol, MAX(time) as latest_candle, COUNT(*) as total_rows
FROM price_intraday WHERE resolution = 1
GROUP BY symbol ORDER BY latest_candle DESC LIMIT 10;
```

### 13.5 Scale real-time processor

Redis Streams consumer group hỗ trợ nhiều consumer song song:

```bash
# Docker: scale lên 3 processor instances
docker compose up -d --scale realtime-processor=3

# Mỗi instance tự nhận message riêng, không trùng lặp
```

---

## 14. Các lỗi thường gặp & cách xử lý

### `ModuleNotFoundError: No module named 'vnstock_data'`

`vnstock_data` là sponsor package, cần cài qua installer với API key.

```bash
# Local: dùng venv đã cài sẵn
venv/Scripts/python main.py sync_ratios

# Docker: cần xóa thiết bị cũ trên vnstocks.com, sau đó rebuild image pipeline:
# 1. Vào https://vnstocks.com/account?section=devices → xóa thiết bị Docker cũ
# 2. Rebuild (bake vnstock_data vào image tại build time):
docker compose build pipeline
docker compose up -d pipeline
```

> **Nguyên nhân trong Docker:** Mỗi lần container bị recreate, `/root/.venv` (chứa `vnstock_data`) bị xóa. Flag file `.vnstock_installed` (trong volume `logs/`) vẫn còn → entrypoint bỏ qua installer → `vnstock_data` không tồn tại.
> **Giải pháp lâu dài:** Build arg `VNSTOCK_API_KEY` trong Dockerfile để cài `vnstock_data` vào image tại build time (baked in) — không phụ thuộc runtime installer.

### `❌ Vượt quá giới hạn thiết bị! (vnstock OS limit)`

Gói Golden giới hạn 2 OS. Xảy ra khi nhiều containers cùng chạy vnstock installer.

**Nguyên nhân:** `realtime-subscriber` và `realtime-processor` cùng build từ Dockerfile → cùng chạy entrypoint → 3 container = 3 OS slot.

**Fix:** Đảm bảo chỉ `pipeline` dùng `entrypoint.sh`. Realtime containers phải dùng `entrypoint_realtime.sh`:

```yaml
# docker-compose.yml
realtime-subscriber:
  entrypoint: ["./entrypoint_realtime.sh"]
  environment:
    VNSTOCK_API_KEY: ""   # tắt vnstock hoàn toàn

realtime-processor:
  entrypoint: ["./entrypoint_realtime.sh"]
  environment:
    VNSTOCK_API_KEY: ""
```

Nếu vẫn bị block → xóa thiết bị cũ tại: https://vnstocks.com/account?section=devices

### `psycopg2.errors.ForeignKeyViolation`

Chạy các module trước khi có `sync_listing`.

```bash
python main.py sync_listing   # chạy TRƯỚC
python main.py sync_financials
```

### `psycopg2.errors.NumericValueOutOfRange`

Giá trị vượt giới hạn `NUMERIC(10,4)`. Pipeline xử lý bằng `_to_float_bounded()` — giá trị cực đoan → `None`. Nếu vẫn gặp: kiểm tra cột nào không qua bounded check.

### MQTT subscriber không nhận được dữ liệu

1. Kiểm tra DNSE credentials trong `.env`: `DNSE_USERNAME`, `DNSE_PASSWORD`
2. Chạy smoke test auth:
   ```bash
   python -c "
   from config.settings import settings
   from realtime.auth import DNSEAuthManager
   mgr = DNSEAuthManager(settings.dnse_username, settings.dnse_password)
   print('Token OK:', mgr.get_token()[:40])
   print('Investor ID:', mgr.get_investor_id())
   "
   ```
3. Kiểm tra giờ giao dịch: chỉ T2–6, 08:45–15:10 ICT
4. Kiểm tra `REALTIME_WATCHLIST` có symbols hợp lệ

### Redis Streams lag tăng cao

Processor không xử lý kịp:

```bash
# Kiểm tra độ dài stream
python check_realtime.py

# Scale processor
docker compose up -d --scale realtime-processor=2
```

### KBS lỗi liên tục trong `sync_prices`

Pipeline tự fallback sang VNDirect. Kiểm tra log:
```bash
grep "KBS lỗi" logs/pipeline_$(date +%Y-%m-%d).log
```

Nếu cả 2 nguồn đều lỗi → kiểm tra kết nối internet, vnstock version, API key.

### `ERROR: invalid interval for date dimension`

Xảy ra khi `create_hypertable` dùng integer thay vì INTERVAL cho cột `DATE`:

```sql
-- SAI (90 bị hiểu là 90 microseconds trong TimescaleDB 2.x)
SELECT create_hypertable('price_history', 'date', chunk_time_interval => 90, ...);

-- ĐÚNG
SELECT create_hypertable('price_history', 'date', chunk_time_interval => INTERVAL '90 days', ...);
```

Migration `010_timescaledb_price_history.sql` đã dùng `INTERVAL '90 days'` — nếu gặp lỗi này là đang dùng migration cũ.

### `ERROR: policy refresh window too small`

Xảy ra khi tạo continuous aggregate policy có `start_offset - end_offset < 2 × bucket_size`:

```sql
-- Ví dụ: 5-min bucket cần window >= 10 phút
-- SAI: window = 10min - 1min = 9min < 10min
SELECT add_continuous_aggregate_policy('cagg_ohlc_5m',
    start_offset => INTERVAL '10 minutes', end_offset => INTERVAL '1 minute', ...);

-- ĐÚNG: window = 15min - 1min = 14min >= 10min
SELECT add_continuous_aggregate_policy('cagg_ohlc_5m',
    start_offset => INTERVAL '15 minutes', end_offset => INTERVAL '1 minute', ...);
```

Migration `011_continuous_aggregates.sql` đã có start_offset đúng (15m / 3h / 3 days).

### TimescaleDB extension không load khi khởi động Docker

TimescaleDB yêu cầu thêm `shared_preload_libraries` — image `timescale/timescaledb:latest-pg16` đã cấu hình sẵn. Nếu dùng `postgres:16-alpine` thuần → extension sẽ không tự load:

```bash
# Kiểm tra extension
docker compose exec postgres psql -U postgres -d stockapp -c "SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';"

# Phải dùng đúng image:
# image: timescale/timescaledb:latest-pg16   (trong docker-compose.yml)
```
