# Hướng dẫn toàn diện — Data Pipeline Chứng khoán Việt Nam

> Tài liệu này dành cho thành viên team muốn đọc hiểu, tùy chỉnh, hoặc tối ưu pipeline.
> Không yêu cầu kiến thức trước — chỉ cần biết Python cơ bản và SQL.

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
9. [Tiện ích — `utils/`](#9-tiện-ích----utils)
10. [CLI — `main.py`](#10-cli----mainpy)
11. [Docker & Triển khai](#11-docker--triển-khai)
12. [Cách tùy chỉnh & mở rộng](#12-cách-tùy-chỉnh--mở-rộng)
13. [Các lỗi thường gặp & cách xử lý](#13-các-lỗi-thường-gặp--cách-xử-lý)

---

## 1. Tổng quan

Pipeline này thu thập dữ liệu chứng khoán Việt Nam từ **vnstock API** và lưu vào **PostgreSQL**, phục vụ cho ứng dụng web phân tích cơ bản.

```
vnstock API (VCI/VND)
        │
        ▼
  [Extractor]  ─── lấy dữ liệu thô (DataFrame)
        │
        ▼
  [Transformer] ─── chuẩn hóa, đổi tên cột, ép kiểu, xử lý lỗi
        │
        ▼
  [PostgresLoader] ─── INSERT ... ON CONFLICT DO UPDATE
        │
        ▼
   PostgreSQL (stockapp)
        │
        ▼
   Web Application (readonly)
```

**4 module dữ liệu chính:**

| Module | Job | Dữ liệu | Lịch chạy |
|---|---|---|---|
| Listing | `sync_listing` | Danh mục mã, phân ngành ICB | Chủ Nhật 01:00 |
| Finance | `sync_financials` | Báo cáo tài chính (4 loại) | Ngày 1 & 15 hàng tháng 03:00 |
| Company | `sync_company` | Cổ đông, lãnh đạo, công ty con, sự kiện | Thứ Hai 02:00 |
| Trading | `sync_ratios` | Snapshot tài chính mới nhất | Hàng ngày 18:30 |

---

## 2. Cấu trúc thư mục

```
data-pipeline/
├── config/
│   ├── settings.py          ← Tất cả biến môi trường (đọc từ .env)
│   └── constants.py         ← Hằng số toàn cục (tên bảng, conflict keys, v.v.)
│
├── db/
│   ├── connection.py        ← SQLAlchemy engine, session factory
│   ├── models.py            ← ORM models (26 class, mirror schema DB)
│   ├── migrate.py           ← Chạy migration SQL files
│   └── migrations/
│       ├── 001_reference_tables.sql   ← icb_industries, companies
│       ├── 002_financial_tables.sql   ← 4 bảng BCTC
│       ├── 003_company_tables.sql     ← 5 bảng company intelligence
│       └── 004_pipeline_logs.sql      ← Bảng log vận hành
│
├── etl/
│   ├── base/
│   │   ├── extractor.py     ← Abstract BaseExtractor
│   │   ├── transformer.py   ← Abstract BaseTransformer
│   │   └── loader.py        ← Abstract BaseLoader
│   ├── extractors/
│   │   ├── listing.py       ← ListingExtractor
│   │   ├── finance.py       ← FinanceExtractor
│   │   ├── company.py       ← CompanyExtractor
│   │   └── trading.py       ← TradingExtractor
│   ├── transformers/
│   │   ├── listing.py       ← ListingTransformer
│   │   ├── finance.py       ← FinanceTransformer
│   │   ├── company.py       ← CompanyTransformer
│   │   └── trading.py       ← TradingTransformer
│   └── loaders/
│       ├── helpers.py       ← sanitize_for_postgres, df_to_records, v.v.
│       └── postgres.py      ← PostgresLoader (upsert engine)
│
├── jobs/
│   ├── sync_listing.py      ← Chạy listing module end-to-end
│   ├── sync_financials.py   ← Chạy finance module end-to-end
│   ├── sync_company.py      ← Chạy company module end-to-end
│   ├── sync_ratios.py       ← Chạy trading module end-to-end
│   └── backfill.py          ← Re-sync dữ liệu lịch sử
│
├── scheduler/
│   └── jobs.py              ← APScheduler: đăng ký 5 jobs theo lịch
│
├── utils/
│   ├── logger.py            ← Loguru: log ra console + file
│   ├── retry.py             ← @vnstock_retry() decorator
│   ├── date_utils.py        ← Parse/format kỳ báo cáo (2024, 2024Q1)
│   ├── alert.py             ← Gửi Telegram
│   └── alert_checker.py     ← Kiểm tra pipeline_logs, kích hoạt alert
│
├── main.py                  ← CLI entry point
├── Dockerfile               ← Build image pipeline
├── docker-compose.yml       ← 2 services: postgres + pipeline
├── entrypoint.sh            ← Startup script trong container
└── .env.example             ← Template biến môi trường
```

---

## 3. Luồng dữ liệu

### 3.1 Luồng chi tiết theo từng bước

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

### 3.2 Thứ tự phụ thuộc khi chạy lần đầu

```
sync_listing          ← phải chạy TRƯỚC (tạo icb_industries + companies)
    │
    ├── sync_financials   ← cần companies.symbol tồn tại (FK)
    ├── sync_company      ← cần companies.symbol tồn tại (FK)
    └── sync_ratios       ← cần companies.symbol tồn tại (FK)
```

**Lý do:** Các bảng `balance_sheets`, `shareholders`, `ratio_summary`, v.v. đều có FK trỏ về `companies(symbol)`. Nếu chạy trước khi có `companies`, INSERT sẽ lỗi FK violation.

---

## 4. Cấu hình — `config/`

### 4.1 `config/settings.py`

Tất cả cấu hình đọc từ file `.env` qua **pydantic-settings**. Không hard-code giá trị trong code.

```python
# Database
settings.database_url      # postgresql://user:pass@host:port/db (tự build từ các field dưới)
settings.db_host           # Host PostgreSQL (default: localhost, Docker: "postgres")
settings.db_port           # Port PostgreSQL (default: 5432)
settings.db_name           # Tên database (default: stockapp)
settings.db_user           # User PostgreSQL (default: postgres)
settings.db_password       # Password PostgreSQL

# Redis (cấu hình sẵn, chưa dùng trong ETL — dự phòng cho cache sau này)
settings.redis_host        # Host Redis (default: localhost)
settings.redis_port        # Port Redis (default: 6379)

# Vnstock
settings.vnstock_source    # Nguồn data: "vci" hoặc "vnd" (default: vci)
settings.vnstock_api_key   # API key cho vnstock sponsor packages — dùng trong entrypoint.sh

# Pipeline tuning
settings.max_workers       # Số luồng song song (default: 5)
settings.request_delay     # Nghỉ giữa API calls (default: 0.3s)
settings.retry_attempts    # Số lần retry khi API lỗi (default: 3)
settings.retry_wait_min    # Chờ tối thiểu giữa các lần retry (default: 1.0s)
settings.retry_wait_max    # Chờ tối đa giữa các lần retry — exponential backoff (default: 10.0s)
settings.db_chunk_size     # Rows/batch khi upsert (default: 500)

# Logging
settings.log_level         # Log level: DEBUG | INFO | WARNING | ERROR (default: INFO)
settings.log_dir           # Thư mục lưu file log (default: logs)

# Alert
settings.telegram_bot_token
settings.telegram_chat_id
settings.alert_fail_threshold  # Số lần fail trước khi gửi alert (default: 3)
```

**Để thay đổi cấu hình:** Chỉnh file `.env`, không cần sửa code.

```env
# Ví dụ: tăng số luồng và giảm delay khi máy chủ mạnh
MAX_WORKERS=10
REQUEST_DELAY=0.1
DB_CHUNK_SIZE=1000

# Ví dụ: tăng retry và khoảng chờ khi API không ổn định
RETRY_ATTEMPTS=5
RETRY_WAIT_MIN=2.0
RETRY_WAIT_MAX=30.0
```

> **Lưu ý Redis:** `redis` có trong `requirements.txt` và `config/settings.py` nhưng chưa được dùng trong logic ETL hiện tại. Đây là cấu hình dự phòng cho tính năng cache (ví dụ: cache danh sách symbols để tránh query DB nhiều lần). Nếu không cần, bỏ qua — pipeline hoạt động hoàn toàn không cần Redis.

### 4.2 `config/constants.py`

Định nghĩa các hằng số được dùng xuyên suốt pipeline:

```python
# Tên job (dùng trong pipeline_logs)
JOB_SYNC_LISTING    = "sync_listing"
JOB_SYNC_FINANCIALS = "sync_financials"
JOB_SYNC_COMPANY    = "sync_company"
JOB_SYNC_RATIOS     = "sync_ratios"

# Conflict keys: cột nào dùng làm PRIMARY KEY cho ON CONFLICT
# Ví dụ: upsert vào balance_sheets conflict trên (symbol, period)
CONFLICT_KEYS = {
    "companies":          ["symbol"],
    "balance_sheets":     ["symbol", "period"],
    "ratio_summary":      ["symbol", "year_report", "quarter_report"],
    ...
}

# Cột do server tự sinh — KHÔNG được đưa vào INSERT/UPDATE
SERVER_GENERATED_COLS = {"id", "duration_ms", "created_at"}
```

---

## 5. Cơ sở dữ liệu — `db/`

### 5.1 Sơ đồ quan hệ

```
icb_industries (id, code, name, level, parent_code)
    │
    └── companies (symbol PK, organ_name, exchange, icb_code FK→icb_industries)
            │
            ├── balance_sheets      (symbol FK, period, ...)
            ├── income_statements   (symbol FK, period, ...)
            ├── cash_flows          (symbol FK, period, ...)
            ├── financial_ratios    (symbol FK, period, ...)
            │
            ├── shareholders        (symbol FK, snapshot_date, share_holder, ...)
            ├── officers            (symbol FK, snapshot_date, officer_name, ...)
            ├── subsidiaries        (symbol FK, snapshot_date, organ_name, ...)
            ├── corporate_events    (symbol FK, ...)
            └── ratio_summary       (symbol FK, year_report, quarter_report, ...)

pipeline_logs (id, job_name, status, started_at, finished_at, duration_ms GENERATED, ...)
```

### 5.2 Mô tả từng nhóm bảng

**Bảng tham chiếu:**

| Bảng | Mô tả | Số lượng row (~) |
|---|---|---|
| `icb_industries` | 4 cấp phân ngành ICB | ~200 ngành |
| `companies` | Tất cả mã chứng khoán đang niêm yết | ~1,550 mã |

**Báo cáo tài chính** (mỗi bảng có UNIQUE trên `(symbol, period)`):

| Bảng | Mô tả | Cột đặc biệt |
|---|---|---|
| `balance_sheets` | Bảng cân đối kế toán | `raw_data JSONB` — lưu toàn bộ dữ liệu gốc |
| `income_statements` | Báo cáo kết quả kinh doanh | `raw_data JSONB` |
| `cash_flows` | Báo cáo lưu chuyển tiền tệ | `raw_data JSONB` |
| `financial_ratios` | Các chỉ số tài chính | `raw_data JSONB` |

> **`period`** có dạng `"2024"` (năm) hoặc `"2024Q1"` (quý 1 năm 2024).

**Company intelligence** (mỗi lần sync tạo snapshot mới theo `snapshot_date`):

| Bảng | Mô tả |
|---|---|
| `shareholders` | Cổ đông lớn và % sở hữu |
| `officers` | Ban lãnh đạo, chức vụ, trạng thái |
| `subsidiaries` | Công ty con / công ty liên kết |
| `corporate_events` | Chia cổ tức, phát hành thêm, tách cổ phiếu |
| `ratio_summary` | Snapshot tổng hợp chỉ số tài chính mới nhất (dùng cho screener) |

**Vận hành:**

| Bảng | Mô tả |
|---|---|
| `pipeline_logs` | Lịch sử chạy job: thành công/thất bại, số records, thời gian |

### 5.3 Cột `raw_data JSONB`

Các bảng BCTC đều có cột `raw_data` lưu **toàn bộ dữ liệu gốc từ API** dưới dạng JSON. Điều này có 2 ý nghĩa:

1. **Drill-down:** Web app có thể đọc `raw_data` để hiển thị thêm chỉ số không có trong schema chuẩn.
2. **Recovery:** Nếu schema thay đổi, dữ liệu gốc vẫn còn nguyên trong `raw_data` — không cần re-fetch từ API.

### 5.4 Chạy migration

```bash
# Lần đầu tiên (tạo toàn bộ schema)
python -m db.migrate

# Hoặc qua Docker (tự động khi init)
# docker-compose mount: ./db/migrations:/docker-entrypoint-initdb.d
```

Migrations chạy theo thứ tự file: `001_` → `002_` → `003_` → `004_`.

### 5.5 `db/connection.py`

```python
from db.connection import engine, get_session

# Dùng engine trực tiếp (cho raw SQL)
with engine.connect() as conn:
    result = conn.execute(text("SELECT COUNT(*) FROM companies"))

# Dùng session (cho ORM)
with get_session() as session:
    companies = session.query(Company).filter_by(exchange="HOSE").all()
```

---

## 6. Tầng ETL — `etl/`

### 6.1 Base classes

Mỗi module phải implement 3 abstract class:

```
BaseExtractor  → abstract method: extract(symbol, **kwargs) → DataFrame | None
BaseTransformer → abstract method: transform(df, symbol, **context) → DataFrame
BaseLoader     → abstract method: load(df, table, conflict_columns, update_columns) → int
```

Thiết kế này đảm bảo mỗi module có thể swap độc lập — ví dụ: thay PostgresLoader bằng BigQueryLoader mà không đụng extractors/transformers.

### 6.2 Extractors

Tất cả extractors kế thừa `BaseExtractor` và dùng `@vnstock_retry()` để tự retry khi API lỗi.

**`ListingExtractor`** — `etl/extractors/listing.py`

```python
extractor = ListingExtractor(source="vnd")  # QUAN TRỌNG: phải dùng "vnd" không phải "vci"
df_symbols    = extractor.extract_symbols()       # ~1,550 rows
df_industries = extractor.extract_industries()    # ~200 rows
```

> **Lý do dùng `vnd`:** Source `vci` chỉ trả về 2 cột (symbol, organ_name), thiếu exchange, type, status. Source `vnd` trả đủ.

**`FinanceExtractor`** — `etl/extractors/finance.py`

```python
extractor = FinanceExtractor(source="vci")
df = extractor.extract(symbol="HPG", report_type="balance_sheet")
# report_type: "balance_sheet" | "income_statement" | "cash_flow" | "ratio"
# Trả về cả năm + quý trong cùng 1 DataFrame (phân biệt qua cột period)
```

**`CompanyExtractor`** — `etl/extractors/company.py`

```python
extractor = CompanyExtractor(source="vci")
df_overview     = extractor.extract_overview(symbol)
df_shareholders = extractor.extract_shareholders(symbol)
df_officers     = extractor.extract_officers(symbol)
df_subsidiaries = extractor.extract_subsidiaries(symbol)
df_events       = extractor.extract_events(symbol)
```

**`TradingExtractor`** — `etl/extractors/trading.py`

```python
extractor = TradingExtractor(source="vci")
df = extractor.extract_ratio_summary(symbol)
# Trả về None nếu API không có dữ liệu (bình thường với ~22 mã)
```

### 6.3 Transformers

Transformers nhận DataFrame thô từ API và trả về DataFrame sẵn sàng upsert vào DB.

**Nhiệm vụ chính:**

| Bước | Mô tả |
|---|---|
| Đổi tên cột | Tên API (tiếng Việt/viết tắt) → tên cột DB (tiếng Anh, snake_case) |
| Ép kiểu | Đảm bảo `int`, `float`, `date` đúng kiểu; không để Python `float("nan")` vào DB |
| Xử lý overflow | NUMERIC(10,4) max là 999,999.9999 — giá trị cực đoan (P/E âm vô cực) → None |
| Thêm metadata | `symbol`, `fetched_at`, `snapshot_date`, `period_type` |
| Deduplicate | `drop_duplicates(subset=conflict_key)` trước khi load — tránh CardinalityViolation |
| Gom cột lạ | Cột API không có trong schema → gom vào `extra_metrics JSONB` hoặc `raw_data JSONB` |

**`FinanceTransformer`** — `etl/transformers/finance.py`

Đây là transformer phức tạp nhất. Phân tích kỳ báo cáo từ index:
- `"2024"` → `period="2024"`, `period_type="year"`
- `"Q1/2024"` → `period="2024Q1"`, `period_type="quarter"`

Có 4 map đổi tên: `_BS_COL_MAP` (balance sheet), `_IS_COL_MAP` (income), `_CF_COL_MAP` (cash flow), `_RATIO_COL_MAP` (ratio).

**`TradingTransformer`** — `etl/transformers/trading.py`

Xử lý tên cột viết tắt đặc thù của `ratio_summary`:

```python
_RENAME_MAP = {
    "de":            "debt_to_equity",
    "at":            "asset_turnover",
    "fat":           "fixed_asset_turnover",
    "dso":           "receivable_days",
    "dpo":           "payable_days",
    "ccc":           "cash_conversion_cycle",
    "ev_per_ebitda": "ev_ebitda",
}
```

Các cột không có trong schema DB (`ae`, `fae`, `rtq4`, `rtq10`, `rtq17`, `le`, v.v.) → gom vào `extra_metrics JSONB`.

### 6.4 PostgresLoader — `etl/loaders/postgres.py`

Đây là engine upsert trung tâm của pipeline:

```python
loader = PostgresLoader()
rows_affected = loader.load(
    df=df_transformed,
    table="balance_sheets",
    conflict_columns=["symbol", "period"],    # ON CONFLICT (symbol, period)
    update_columns=["revenue", "net_profit", "fetched_at", ...],  # DO UPDATE SET ...
)
```

**Cách hoạt động bên trong:**

1. `MetaData().reflect(engine, only=[table])` — lấy schema thực tế từ DB
2. Filter DataFrame chỉ giữ cột có trong schema (tránh lỗi khi API thêm cột mới)
3. `sanitize_for_postgres(df)` — chuyển NaN/NaT/Inf → None
4. Chia thành chunks 500 rows
5. Mỗi chunk: `pg_insert(table).values(records).on_conflict_do_update(...)`
6. `load_log()` — ghi kết quả vào `pipeline_logs`

**`helpers.py`** — các hàm tiện ích quan trọng:

```python
sanitize_for_postgres(df)  # NaN → None, numpy types → Python native
df_to_records(df)          # DataFrame → list[dict], đảm bảo JSON-serializable
chunk_dataframe(df, 500)   # Generator chia DataFrame thành batches
build_raw_data(row)        # Series → dict cho JSONB columns
```

---

## 7. Jobs — `jobs/`

Mỗi job là một module độc lập với hàm `run()` làm entry point.

### 7.1 `sync_listing.py`

```python
from jobs.sync_listing import run
result = run()
# result = {"icb_industries": 200, "companies": 1547}
```

Chạy tuần tự (không song song) vì dataset nhỏ và có FK dependency.

**Thứ tự bắt buộc:**
1. Upsert `icb_industries` trước
2. Upsert `companies` sau (FK trỏ về icb_industries)

### 7.2 `sync_financials.py`

```python
from jobs.sync_financials import run
result = run(
    symbols=["HPG", "VCB"],   # None = tất cả mã
    max_workers=5,
    report_types=["balance_sheet", "income_statement"],  # None = cả 4 loại
)
# result = {"success": 8, "failed": 0, "skipped": 0, "rows": 1240}
```

Mỗi symbol × mỗi report_type = 1 task riêng trong ThreadPoolExecutor. Với ~1,550 mã × 4 loại = ~6,200 tasks.

### 7.3 `sync_company.py`

```python
from jobs.sync_company import run
result = run(symbols=None, max_workers=5)
```

**Hai pha quan trọng:**

**Pha A (tuần tự):** Cập nhật `companies.icb_code`, `charter_capital`, `issue_share` từ overview của từng mã. Dùng `UPDATE ... WHERE symbol = ?` với COALESCE để không ghi đè giá trị đã có.

**Pha B (song song):** Upsert shareholders, officers, subsidiaries, corporate_events.

> Lý do tách 2 pha: Nếu 5 luồng cùng UPDATE `companies` song song → deadlock / lock contention.

### 7.4 `sync_ratios.py`

```python
from jobs.sync_ratios import run
result = run(symbols=None, max_workers=5)
# result = {"success": 1525, "failed": 0, "skipped": 22, "rows": 7625}
```

Job đơn giản nhất: chỉ 1 extractor → 1 transformer → 1 loader. Chạy hàng ngày sau đóng cửa (18:30).

### 7.5 `backfill.py`

Dùng khi cần re-sync lại dữ liệu lịch sử — ví dụ sau khi fix bug trong transformer:

```bash
python main.py sync_financials --symbol HPG VCB FPT --workers 3
```

---

## 8. Scheduler — `scheduler/`

### 8.1 `scheduler/jobs.py`

```python
from scheduler.jobs import build_scheduler
scheduler = build_scheduler()
scheduler.start()  # Blocking — giữ process chạy liên tục
```

**5 jobs đã đăng ký:**

| Job ID | Cron | Mô tả | misfire_grace_time |
|---|---|---|---|
| `sync_listing` | CN 01:00 | Refresh danh mục & ngành | 1 giờ |
| `sync_financials` | Ngày 1 & 15, 03:00 | BCTC 4 loại | 1 giờ |
| `sync_company` | Thứ Hai 02:00 | Company intelligence | 1 giờ |
| `sync_ratios` | Hàng ngày 18:30 | Ratio snapshot | 30 phút |
| `alert_check` | Hàng giờ :00 | Kiểm tra lỗi → Telegram | 5 phút |

**`misfire_grace_time`:** Nếu scheduler bị dừng (restart server, v.v.) và job bị bỏ lỡ, APScheduler sẽ chạy bù nếu thời gian trễ ≤ grace time. Nếu trễ hơn → bỏ qua.

**`_safe_run()` wrapper:**

```python
def _safe_run(job_fn, job_name):
    def wrapper():
        try:
            job_fn()
        except Exception as exc:
            logger.error(f"Job '{job_name}' thất bại: {exc}")
    return wrapper
```

Đảm bảo 1 job lỗi không crash toàn bộ scheduler.

### 8.2 Thay đổi lịch chạy

Ví dụ: muốn `sync_ratios` chạy lúc 19:00 thay vì 18:30:

```python
# scheduler/jobs.py
scheduler.add_job(
    _safe_run(ratios_job.run, "sync_ratios"),
    CronTrigger(hour=19, minute=0, timezone="Asia/Ho_Chi_Minh"),  # ← đổi ở đây
    ...
)
```

---

## 9. Tiện ích — `utils/`

### 9.1 `utils/logger.py`

```python
from utils.logger import logger

logger.debug("Chi tiết debug")
logger.info("Thông tin thường")
logger.warning("Cảnh báo")
logger.error("Lỗi nghiêm trọng")
logger.success("Thành công")
```

Log được ghi ra **2 nơi đồng thời:**
- Console: có màu, dễ đọc khi debug
- File: `logs/pipeline_YYYY-MM-DD.log`, xoay hàng ngày, giữ 30 ngày, nén `.zip`

Thay đổi log level qua `.env`:
```env
LOG_LEVEL=DEBUG   # DEBUG | INFO | WARNING | ERROR
```

### 9.2 `utils/retry.py`

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

Dùng **tenacity** với exponential backoff. Mặc định: 3 lần retry, chờ 1–10 giây giữa các lần (đọc từ `settings.retry_attempts`, `settings.retry_wait_min`, `settings.retry_wait_max`).

> **Quan trọng:** `@vnstock_retry()` chỉ retry khi có **exception thực sự** (timeout, HTTP 5xx, v.v.). Nếu API trả về `None` hay DataFrame rỗng, đó là kết quả hợp lệ — không retry.

### 9.3 `utils/date_utils.py`

```python
from utils.date_utils import to_period, parse_period, get_period_type

to_period(2024, 0)  # → "2024"      (0 = năm)
to_period(2024, 1)  # → "2024Q1"

parse_period("2024Q3")   # → (2024, 3)
parse_period("2024")     # → (2024, 0)

get_period_type("2024Q1")  # → "quarter"
get_period_type("2024")    # → "year"
```

### 9.4 Alert Telegram — `utils/alert.py` & `utils/alert_checker.py`

**Thiết lập:**
1. Tạo bot qua @BotFather trên Telegram → lấy `TELEGRAM_BOT_TOKEN`
2. Nhắn tin cho bot → gọi `getUpdates` API → lấy `TELEGRAM_CHAT_ID`
3. Điền vào `.env`

**Test thủ công:**
```bash
python -c "from utils.alert import send_telegram; send_telegram('test pipeline alert')"
```

**`alert_checker`** chạy tự động mỗi giờ, query `pipeline_logs`:

```sql
SELECT job_name, COUNT(*) AS fail_count
FROM pipeline_logs
WHERE status = 'failed' AND started_at >= NOW() - INTERVAL '24 hours'
GROUP BY job_name
HAVING COUNT(*) >= 3
```

Nếu có kết quả → gửi Telegram.

---

## 10. CLI — `main.py`

```bash
# Xem help
python main.py --help
python main.py sync_financials --help

# Chạy thủ công từng module
python main.py sync_listing
python main.py sync_financials
python main.py sync_financials --symbol HPG VCB FPT
python main.py sync_financials --symbol HPG --workers 3
python main.py sync_company
python main.py sync_ratios --symbol HPG VCB

# Khởi động scheduler (production)
python main.py schedule
```

---

## 11. Docker & Triển khai

### 11.1 Cấu trúc Docker

```
docker-compose.yml
├── postgres  (postgres:16-alpine)
│   ├── Tự chạy db/migrations/ khi khởi tạo lần đầu
│   ├── Dữ liệu lưu trong volume postgres_data
│   └── Expose port 5432 (để web app kết nối)
│
└── pipeline  (build từ Dockerfile)
    ├── entrypoint.sh
    │   ├── Kiểm tra flag ./logs/.vnstock_installed
    │   │   ├── Chưa có → chạy installer với VNSTOCK_API_KEY → tạo flag
    │   │   └── Đã có  → bỏ qua (tránh cài lại khi restart/rebuild)
    │   ├── Export PYTHONPATH → /root/.venv/lib/python3.12/site-packages
    │   │   (installer tạo venv riêng tại /root/.venv, cần expose cho /opt/venv)
    │   ├── Chờ PostgreSQL sẵn sàng
    │   └── exec python3 main.py schedule
    └── Mount ./logs → /app/logs (xem log không cần vào container)
```

### 11.2 Lệnh vận hành thường dùng

```bash
# Khởi động lần đầu
docker compose up -d --build

# Xem log realtime
docker compose logs -f pipeline

# Chạy thủ công một job
docker compose exec pipeline python main.py sync_ratios --symbol HPG VCB FPT

# Rebuild sau khi sửa code (không đụng DB)
docker compose up -d --build pipeline

# Dừng (giữ dữ liệu)
docker compose down

# Reset toàn bộ (xóa cả DB)
docker compose down -v
```

### 11.3 Kết nối từ Web Application

Web application kết nối vào PostgreSQL bằng user readonly riêng:

```sql
-- Chạy 1 lần sau khi deploy
CREATE USER webapp_readonly WITH PASSWORD 'webapp_password';
GRANT CONNECT ON DATABASE stockapp TO webapp_readonly;
GRANT USAGE ON SCHEMA public TO webapp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO webapp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO webapp_readonly;
```

Connection string cho web app:
```
postgresql://webapp_readonly:<password>@<server_ip>:5432/stockapp
```

---

## 12. Cách tùy chỉnh & mở rộng

### 12.1 Thêm cột mới vào bảng BCTC

**Ví dụ:** API vnstock bổ sung cột `working_capital` vào balance sheet.

**Bước 1:** Thêm cột vào migration (tạo file mới `005_add_working_capital.sql`):
```sql
ALTER TABLE balance_sheets ADD COLUMN working_capital BIGINT;
```

**Bước 2:** Thêm mapping trong `etl/transformers/finance.py`:
```python
_BS_COL_MAP = {
    ...
    "vốn lưu động": "working_capital",  # ← thêm dòng này
}
```

**Bước 3:** Chạy lại migration và backfill:
```bash
python -m db.migrate
python main.py sync_financials
```

### 12.2 Thêm module dữ liệu mới

Ví dụ: muốn thêm module `news` lấy tin tức.

**Cấu trúc cần tạo:**

```
etl/extractors/news.py        ← class NewsExtractor(BaseExtractor)
etl/transformers/news.py      ← class NewsTransformer(BaseTransformer)
jobs/sync_news.py             ← def run(symbols=None, max_workers=None)
db/migrations/005_news.sql    ← CREATE TABLE news (...)
```

**Đăng ký vào scheduler** (`scheduler/jobs.py`):
```python
import jobs.sync_news as news_job
scheduler.add_job(
    _safe_run(news_job.run, "sync_news"),
    CronTrigger(hour=20, minute=0, timezone="Asia/Ho_Chi_Minh"),
    id="sync_news",
    misfire_grace_time=1800,
)
```

**Thêm CLI command** (`main.py`):
```python
subparsers.add_parser("sync_news", help="Đồng bộ tin tức")
# ...
elif args.command == "sync_news":
    from jobs.sync_news import run
    run()
```

### 12.3 Tăng hiệu năng

| Tham số | Mặc định | Khi nào nên tăng |
|---|---|---|
| `MAX_WORKERS` | 5 | VPS có nhiều CPU, API không rate-limit |
| `DB_CHUNK_SIZE` | 500 | RAM nhiều, batch write cần nhanh hơn |
| `REQUEST_DELAY` | 0.3s | Giảm nếu API không throttle |

> **Cảnh báo:** Tăng `MAX_WORKERS` quá cao có thể bị vnstock rate-limit hoặc ban IP. Bắt đầu từ 8–10 và test trước.

### 12.4 Thay đổi nguồn dữ liệu (source)

```env
# .env
VNSTOCK_SOURCE=vnd   # thay vì vci
```

> **Lưu ý:** `sync_listing` luôn dùng `source="vnd"` bất kể cấu hình vì `vci` không trả đủ cột. Chỉ các module khác mới đọc từ settings.

### 12.5 Theo dõi pipeline_logs

```sql
-- Xem 20 lần chạy gần nhất
SELECT job_name, status, records_success, records_failed, duration_ms, started_at
FROM pipeline_logs
ORDER BY started_at DESC
LIMIT 20;

-- Đếm lỗi 7 ngày qua
SELECT job_name, COUNT(*) as fail_count
FROM pipeline_logs
WHERE status = 'failed' AND started_at >= NOW() - INTERVAL '7 days'
GROUP BY job_name
ORDER BY fail_count DESC;

-- Xem thời gian chạy trung bình
SELECT job_name, AVG(duration_ms)/1000 AS avg_seconds
FROM pipeline_logs
WHERE status = 'success'
GROUP BY job_name;
```

---

## 13. Các lỗi thường gặp & cách xử lý

### `ModuleNotFoundError: No module named 'vnstock_data'`

`vnstock_data` là sponsor package, chỉ có khi cài qua installer với API key.

```bash
# Trong môi trường local: dùng venv đã cài sẵn
venv/Scripts/python main.py sync_ratios

# Trong Docker: VNSTOCK_API_KEY phải có trong .env
```

Nếu cần **force reinstall** vnstock sponsor packages trong Docker (ví dụ: update version):

```bash
# Xóa flag file → lần khởi động tiếp theo sẽ chạy lại installer
rm ./logs/.vnstock_installed
docker compose restart pipeline
```

### `psycopg2.errors.ForeignKeyViolation`

Chạy các module Finance/Company/Trading trước khi có `sync_listing`.

```bash
python main.py sync_listing   # chạy TRƯỚC
python main.py sync_financials
```

### `psycopg2.errors.NumericValueOutOfRange`

Giá trị vượt giới hạn `NUMERIC(10,4)`. Ví dụ: P/E của một mã có EPS ≈ 0 → P/E hàng triệu.

Pipeline đã xử lý bằng `_to_float_bounded()` — giá trị cực đoan → `None`. Nếu vẫn gặp lỗi, kiểm tra xem có cột nào không qua bounded check không.

### `CardinalityViolation` / `ON CONFLICT DO UPDATE command cannot affect row a second time`

Transformer gửi 2 dòng có cùng conflict key trong 1 batch. Đã xử lý bằng `drop_duplicates(subset=conflict_key, keep="last")` trong mỗi transformer.

### `RetryError` sau 3 lần thử

API vnstock timeout hoặc symbol không tồn tại. Kiểm tra:
1. Kết nối mạng
2. API key còn hạn chưa
3. Symbol có thực sự tồn tại không

### Job chạy nhưng `skipped = N` cao

Bình thường — một số mã không có dữ liệu (mã mới niêm yết, mã bị suspend). `skipped` không phải lỗi.

### Scheduler không chạy đúng giờ sau restart

Kiểm tra `misfire_grace_time`. Nếu server down > grace time, job bị bỏ qua. Có thể chạy thủ công:

```bash
docker compose exec pipeline python main.py sync_ratios
```

---

*Tài liệu này phản ánh trạng thái pipeline tại Phase 6 (hoàn chỉnh). Cập nhật khi có thay đổi kiến trúc.*

---

## 14. Tóm tắt biến môi trường (.env)

Danh sách đầy đủ tất cả biến có thể cấu hình qua `.env`:

| Biến | Mặc định | Bắt buộc | Mô tả |
|---|---|---|---|
| `DB_HOST` | `localhost` | ✓ (Docker: `postgres`) | Host PostgreSQL |
| `DB_PORT` | `5432` | | Port PostgreSQL |
| `DB_NAME` | `stockapp` | | Tên database |
| `DB_USER` | `postgres` | | User DB |
| `DB_PASSWORD` | _(không có)_ | ✓ | Password DB |
| `REDIS_HOST` | `localhost` | | Redis host (chưa dùng) |
| `REDIS_PORT` | `6379` | | Redis port (chưa dùng) |
| `VNSTOCK_SOURCE` | `vci` | | Nguồn dữ liệu |
| `VNSTOCK_API_KEY` | _(không có)_ | ✓ (sponsor) | API key vnstock sponsor |
| `MAX_WORKERS` | `5` | | Luồng song song |
| `REQUEST_DELAY` | `0.3` | | Delay giữa API calls (giây) |
| `RETRY_ATTEMPTS` | `3` | | Số lần retry |
| `RETRY_WAIT_MIN` | `1.0` | | Chờ tối thiểu retry (giây) |
| `RETRY_WAIT_MAX` | `10.0` | | Chờ tối đa retry (giây) |
| `DB_CHUNK_SIZE` | `500` | | Rows/batch khi upsert |
| `LOG_LEVEL` | `INFO` | | Mức log |
| `LOG_DIR` | `logs` | | Thư mục log |
| `TELEGRAM_BOT_TOKEN` | _(trống)_ | | Token Telegram bot |
| `TELEGRAM_CHAT_ID` | _(trống)_ | | Chat ID nhận alert |
| `ALERT_FAIL_THRESHOLD` | `3` | | Ngưỡng fail/24h để gửi alert |
