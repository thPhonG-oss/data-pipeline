# Giai đoạn 1 — Nền tảng (Foundation)

**Trạng thái:** Hoàn thành
**Ngày hoàn thành:** 2026-03-18

## Tổng quan

Giai đoạn 1 xây dựng toàn bộ lớp nền tảng mà các giai đoạn sau đều phụ thuộc vào: schema cơ sở dữ liệu, cấu hình, kết nối DB, các abstract base class của ETL, loader chung, và các tiện ích dùng chung.

---

## Phần 1 — Database Schema (Migrations)

### 4 file migration trong `db/migrations/`

Chạy theo thứ tự tên file bằng `python -m db.migrate`.

| File | Nội dung |
|---|---|
| `001_reference_tables.sql` | `icb_industries`, `companies` |
| `002_financial_tables.sql` | `balance_sheets`, `income_statements`, `cash_flows`, `financial_ratios` |
| `003_company_tables.sql` | `shareholders`, `officers`, `subsidiaries`, `corporate_events`, `ratio_summary` |
| `004_pipeline_logs.sql` | `pipeline_logs` |

**Quyết định thiết kế quan trọng:**
- Tất cả bảng tài chính dùng `UNIQUE (symbol, period, period_type)` — cho phép upsert không trùng lặp.
- Ba bảng BCTC chính (`balance_sheets`, `income_statements`, `cash_flows`) có thêm cột `raw_data JSONB` để lưu toàn bộ ~140 cột gốc từ API.
- `pipeline_logs.duration_ms` là **cột generated**: `EXTRACT(MILLISECONDS FROM finished_at - started_at)::INTEGER STORED` — không được ghi vào INSERT.
- `icb_industries.parent_code` self-reference → phải insert node cha trước node con.

### `db/migrate.py`

Script chạy migration. Dùng `psycopg2` trực tiếp (không qua SQLAlchemy) để thực thi SQL thuần.

```
python -m db.migrate
```

Cơ chế: glob toàn bộ `*.sql` trong thư mục `db/migrations/`, sort theo tên, thực thi tuần tự. Nếu bất kỳ file nào lỗi → dừng ngay, exit code 1.

---

## Phần 2 — Cấu hình (`config/`)

### `config/settings.py`

Dùng **pydantic-settings** (`BaseSettings`) — tự động đọc từ file `.env` và biến môi trường.

```python
from config.settings import settings

settings.database_url      # postgresql://postgres:postgres@localhost:5432/stockapp
settings.max_workers       # 5
settings.request_delay     # 0.3 (giây nghỉ giữa API calls)
settings.retry_attempts    # 3
settings.db_chunk_size     # 500 (số dòng mỗi batch upsert)
settings.vnstock_source    # "vci"
```

`database_url` là `@computed_field` — tự ghép từ host/port/name/user/password.

**Tất cả giá trị đều có default**, không cần file `.env` để chạy ở môi trường dev. Override bằng cách đặt biến môi trường hoặc viết vào `.env`.

### `config/constants.py`

Hằng số dùng chung toàn pipeline:

```python
CONFLICT_KEYS: dict[str, list[str]] = {
    "icb_industries":    ["icb_code"],
    "companies":         ["symbol"],
    "balance_sheets":    ["symbol", "period", "period_type"],
    "income_statements": ["symbol", "period", "period_type"],
    "cash_flows":        ["symbol", "period", "period_type"],
    "financial_ratios":  ["symbol", "period", "period_type"],
    "ratio_summary":     ["symbol", "year_report", "quarter_report"],
    "shareholders":      ["symbol", "share_holder", "snapshot_date"],
    "officers":          ["symbol", "officer_name", "status", "snapshot_date"],
    "subsidiaries":      ["symbol", "organ_name", "snapshot_date"],
    "corporate_events":  ["symbol", "event_list_code", "record_date"],
}

SERVER_GENERATED_COLS = {"id", "duration_ms", "created_at"}
```

`SERVER_GENERATED_COLS` — các cột này không bao giờ được đưa vào câu lệnh INSERT/UPDATE (PostgreSQL tự sinh).

---

## Phần 3 — Kết nối Database (`db/connection.py`)

SQLAlchemy engine với connection pool:

```python
engine = create_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # Kiểm tra connection trước khi dùng (tránh stale connection)
    echo=False,
)
```

Cung cấp:
- `engine` — dùng trực tiếp trong các loader và job (raw SQL qua `text()`)
- `SessionLocal` — session factory cho ORM nếu cần
- `get_session()` — context manager tự commit/rollback
- `check_connection()` — health check trả về `True/False`

---

## Phần 4 — Abstract Base Classes (`etl/base/`)

Ba abstract class định nghĩa interface chung cho toàn pipeline:

### `BaseExtractor`

```python
class BaseExtractor(ABC):
    def __init__(self, source: str = "vci"):
        self.source = source

    @abstractmethod
    def extract(self, symbol: str, **kwargs) -> pd.DataFrame:
        """Gọi vnstock_data API, trả về DataFrame thô chưa làm sạch."""
```

### `BaseTransformer`

```python
class BaseTransformer(ABC):
    @abstractmethod
    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        """Đổi tên cột, ép kiểu, loại bỏ dòng null không hợp lệ."""
```

### `BaseLoader`

```python
class BaseLoader(ABC):
    @abstractmethod
    def load(self, df: pd.DataFrame, table: str, conflict_columns: list[str]) -> int:
        """Upsert DataFrame vào bảng. Trả về số dòng được insert/update."""
```

---

## Phần 5 — PostgresLoader (`etl/loaders/postgres.py`)

Concrete implementation của `BaseLoader` — upsert DataFrame vào PostgreSQL bằng `INSERT ... ON CONFLICT DO UPDATE`.

### Cơ chế hoạt động

1. **Reflect schema** từ DB (`MetaData.reflect`) — lấy danh sách cột thực tế của bảng, cache lại để không reflect mỗi lần gọi.
2. **Lọc cột** — chỉ giữ cột DataFrame nào có trong bảng (bỏ cột dư từ transformer).
3. **Xác định update_columns** — tất cả cột trong bảng, trừ `conflict_columns` và `SERVER_GENERATED_COLS`.
4. **Chunk + upsert** — chia records thành batch 500 dòng, dùng `sqlalchemy.dialects.postgresql.insert` (pg_insert).

```python
stmt = pg_insert(tbl).values(chunk_records)
stmt = stmt.on_conflict_do_update(
    index_elements=conflict_columns,
    set_={col: stmt.excluded[col] for col in update_cols},
)
```

### `load_log()` — ghi pipeline_logs

```python
# Tạo log mới → trả về id
log_id = loader.load_log(job_name="sync_listing", status="running")

# Cập nhật log đã tồn tại
loader.load_log(
    job_name="sync_listing", status="success",
    records_fetched=100, records_inserted=95,
    log_id=log_id
)
```

---

## Phần 6 — Helper Functions (`etl/loaders/helpers.py`)

| Hàm | Mục đích |
|---|---|
| `sanitize_for_postgres(df)` | Thay `NaN/NaT/inf/-inf` → `None`; chuyển numpy int/float → Python native |
| `df_to_records(df)` | Gọi `sanitize_for_postgres()` rồi `.to_dict("records")` |
| `chunk_dataframe(df, size)` | Generator chia DataFrame thành chunk |
| `build_raw_data(row)` | Serialize một dòng DataFrame → `dict` JSON-serializable (cho cột `raw_data JSONB`) |

**Vấn đề đặc biệt với nullable integers:**

pandas `Int64` (nullable) → khi qua `.apply()` có thể bị convert thành `float64` với `NaN`. `df_to_records()` có thêm "final pass" để bắt trường hợp này:

```python
for rec in records:
    for k, v in rec.items():
        if isinstance(v, float) and math.isnan(v):
            rec[k] = None
```

---

## Phần 7 — Utilities

### `utils/logger.py`

Dùng **loguru** thay vì stdlib `logging`:
- Console: màu sắc, format ngắn gọn, level INFO trở lên.
- File: `logs/pipeline_YYYY-MM-DD.log`, xoay lúc 00:00, giữ 30 ngày, nén zip.
- Fix UTF-8 cho Windows: `sys.stdout.reconfigure(encoding="utf-8")`.

```python
from utils.logger import logger

logger.info("Bắt đầu job")
logger.success("Hoàn thành")
logger.warning("Bỏ qua mã rỗng")
logger.error(f"Lỗi: {exc}")
```

### `utils/retry.py`

Decorator dựa trên **tenacity** với exponential backoff:

```python
@vnstock_retry()                              # Dùng giá trị từ settings (3 lần, 1-10s)
def extract_balance_sheet(self, symbol): ...

@vnstock_retry(attempts=5, wait_max=30)       # Override
def extract_heavy_data(self, symbol): ...
```

Log cảnh báo trước mỗi lần retry (`before_sleep_log`). Sau khi hết lần thử → `reraise=True` (không nuốt lỗi).

### `utils/date_utils.py`

Xử lý chuỗi period:

```python
to_period(2024, 1)          # → "2024Q1"
to_period(2024)             # → "2024"
parse_period("2024Q1")      # → (2024, 1)
get_period_type("2024Q1")   # → "quarter"
get_period_type("2024")     # → "year"

# Chuyển định dạng API vnstock → DB
api_report_period_to_period("Q1/2024")  # → ("2024Q1", "quarter")
api_report_period_to_period("2024")     # → ("2024", "year")
```

---

## Phần 8 — Kết quả & Quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| Config management | pydantic-settings | Tự validate type, hỗ trợ `.env`, không cần code load thủ công |
| ORM vs raw SQL | SQLAlchemy engine + `text()` cho jobs; reflect table cho loader | Upsert ON CONFLICT cần dialect PostgreSQL — ORM không hỗ trợ trực tiếp |
| Logging | loguru | API đơn giản hơn stdlib; file rotation + retention built-in |
| Retry | tenacity | Exponential backoff, configurable, không cần tự viết loop |
| Nullable int | `Int64` + final NaN pass | pandas nullable integer dễ bị coerce sang float NaN khi to_dict |
| Chunk size | 500 dòng/batch | Cân bằng giữa memory và round-trip DB |
