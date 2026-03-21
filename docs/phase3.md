# Giai đoạn 3 — Module Tài Chính (Finance)

**Trạng thái:** Hoàn thành
**Ngày hoàn thành:** 2026-03-18/19

## Tổng quan

Giai đoạn 3 xây dựng module thu thập 4 loại báo cáo tài chính (BCTC) từ vnstock và lưu vào 4 bảng tương ứng trong PostgreSQL. Đây là module **ưu tiên cao nhất** vì chứa dữ liệu cốt lõi cho phân tích cơ bản.

**Kết quả:** ~1,500 mã × 4 loại báo cáo, hàng chục nghìn kỳ dữ liệu được load vào DB.

---

## Phần 1 — Extractor (`etl/extractors/finance.py`)

### API nguồn dữ liệu

```python
Finance(source="vci", symbol="HPG", period="year")
    .balance_sheet(lang="vi")       → balance_sheets
    .income_statement(lang="vi")    → income_statements
    .cash_flow(lang="vi")           → cash_flows
    .ratio(lang="vi")               → financial_ratios
```

**Quan trọng:** Một lần gọi API trả về **cả dữ liệu năm lẫn quý** trong cùng một DataFrame — phân biệt qua cột `report_period` (ví dụ: `"2024"`, `"Q1/2024"`). Tham số `period="year"` trong constructor **không** lọc dữ liệu — chỉ là cấu hình mặc định của SDK.

### Thiết kế `FinanceExtractor`

Dùng dispatch pattern để `extract()` có thể gọi đúng method theo `report_type`:

```python
def extract(self, symbol: str, report_type: str = "balance_sheet", **kwargs):
    dispatch = {
        "balance_sheet":    self.extract_balance_sheet,
        "income_statement": self.extract_income_statement,
        "cash_flow":        self.extract_cash_flow,
        "ratio":            self.extract_ratio,
    }
    return dispatch[report_type](symbol)
```

Mỗi method riêng đều có `@vnstock_retry()` — nếu API lỗi sẽ tự retry tối đa 3 lần.

---

## Phần 2 — Transformer (`etl/transformers/finance.py`)

### Thách thức chính: ~100+ cột tiếng Việt

API `Finance` trả về DataFrame với tên cột **tiếng Việt** (ví dụ: `"Tiền và tương đương tiền"`, `"Lợi nhuận sau thuế"`). Transformer phải map sang tên cột tiếng Anh theo schema DB.

### Các bước transform chung cho cả 4 loại báo cáo

**Bước 1 — Serialize `raw_data`:** Trước khi đổi tên cột, serialize toàn bộ dòng gốc thành JSON (gọi `build_raw_data(row)`) và lưu vào cột `raw_data JSONB`. Đây là "safety net" giữ lại tất cả ~140 cột gốc.

**Bước 2 — Parse `period`:** Chuyển `report_period` từ API (ví dụ: `"Q1/2024"`, `"2024"`) sang `(period, period_type)` bằng `api_report_period_to_period()` từ `utils/date_utils.py`.

```python
"Q1/2024" → period="2024Q1", period_type="quarter"
"2024"    → period="2024",   period_type="year"
```

**Bước 3 — Đổi tên cột:** Map dict `{tên_tiếng_Việt: tên_schema}` riêng cho từng loại báo cáo.

**Bước 4 — Ép kiểu BIGINT:** Các cột số tiền (tỷ đồng) → `pd.to_numeric(..., errors='coerce')` → `Int64` (nullable). **Không dùng `int64` thường** vì `NaN` không tồn tại trong `int64`.

**Bước 5 — Loại dòng vô nghĩa:** Bỏ dòng thiếu cả `symbol` lẫn `period`.

**Bước 6 — Thêm cột meta:** `symbol`, `source="vci"`, `fetched_at=now()`.

### Bug đã gặp và cách xử lý

#### Bug 1: pandas `Int64` → `NaN` → PostgreSQL BIGINT overflow

**Vấn đề:** Một số giá trị trong API trả về là `pd.NA` (pandas nullable Int64). Khi qua `.to_dict("records")`, pandas đôi khi convert `pd.NA` thành `float("nan")` → psycopg2 cố insert `NaN` vào cột `BIGINT` → lỗi.

**Giải pháp:** Hàm `df_to_records()` trong `helpers.py` có "final pass" sau `to_dict()`:
```python
for rec in records:
    for k, v in rec.items():
        if isinstance(v, float) and math.isnan(v):
            rec[k] = None
```

#### Bug 2: Cột trùng lặp cho công ty bảo hiểm

**Vấn đề:** API trả về DataFrame với **tên cột trùng nhau** cho một số công ty bảo hiểm (do cấu trúc BCTC đặc thù). pandas xử lý thành `Cột`, `Cột.1`, `Cột.2`... → map cột sai.

**Giải pháp:** Trong transformer, thêm bước `df.columns = pd.io.parsers.readers.ParserBase({'names': df.columns, 'usecols': None})._maybe_dedup_names(df.columns)` để dedup tên cột trước khi map. Hoặc: chỉ lấy cột đầu tiên khi trùng.

#### Bug 3: FK reflection trong parallel threads

**Vấn đề:** `PostgresLoader._reflect_table()` cache `MetaData` theo instance. Khi dùng `ThreadPoolExecutor`, nhiều thread dùng chung một instance loader → race condition khi reflect đồng thời, dẫn đến lỗi `ForeignKey 'companies.symbol' on table 'income_statements': table 'companies' has no column named 'symbol'`.

**Giải pháp:** Truyền `resolve_fks=False` vào `MetaData.reflect()`:
```python
self._metadata.reflect(bind=engine, only=[table_name], resolve_fks=False)
```
Không cần resolve FK trong loader — chỉ cần biết danh sách cột để build INSERT statement.

---

## Phần 3 — Job (`jobs/sync_financials.py`)

### Thiết kế song song

Tạo danh sách tasks: `[(symbol, report_type)]` cho tất cả tổ hợp. Chạy song song bằng `ThreadPoolExecutor`:

```python
tasks = [(sym, rt) for sym in symbols for rt in report_types]
# Với 1500 mã × 4 loại = 6000 tasks
# 5 luồng song song → ~1200 tasks/luồng
```

Mỗi task (`_run_one`) chạy độc lập: extract → transform → load → ghi pipeline_logs. Lỗi của một task không ảnh hưởng task khác.

### Hàm `run()` linh hoạt

```python
def run(
    symbols: list[str] | None = None,      # Mặc định: tất cả mã từ DB
    report_types: list[str] | None = None,  # Mặc định: 4 loại
    max_workers: int | None = None,          # Mặc định: settings.max_workers
) -> dict:
```

Cho phép gọi với tham số cụ thể — tiện cho backfill hoặc debug:

```bash
python jobs/sync_financials.py --symbols HPG VCB --report-types balance_sheet ratio
python jobs/sync_financials.py --workers 10
```

### Tổng kết mỗi lần chạy

```
[sync_financials] Xong. Success=5800 | Failed=200 | Skipped=0 | Rows=234512
```

`Failed` thường là mã không có dữ liệu (mã mới niêm yết, ETF, trái phiếu không có BCTC).

---

## Phần 4 — Bảng dữ liệu và Schema

### 4 bảng tài chính

| Bảng | Conflict key | Cột `raw_data` |
|---|---|---|
| `balance_sheets` | `(symbol, period, period_type)` | Có (JSONB) |
| `income_statements` | `(symbol, period, period_type)` | Có (JSONB) |
| `cash_flows` | `(symbol, period, period_type)` | Có (JSONB) |
| `financial_ratios` | `(symbol, period, period_type)` | Không |

### Định dạng `period`

| API trả về | `period` trong DB | `period_type` |
|---|---|---|
| `"2024"` | `"2024"` | `"year"` |
| `"Q1/2024"` | `"2024Q1"` | `"quarter"` |
| `"Q4/2023"` | `"2023Q4"` | `"quarter"` |

---

## Phần 5 — Quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| `raw_data JSONB` | Serialize toàn bộ dòng gốc vào `raw_data` | API có ~140 cột tiếng Việt — không thể map hết; JSONB giữ nguyên để drill-down sau |
| `lang="vi"` | Lấy dữ liệu tiếng Việt | Tên cột tiếng Anh từ API không nhất quán giữa các nguồn; tiếng Việt ổn định hơn |
| Một API call = cả năm + quý | Không gọi riêng năm/quý | Giảm số lần gọi API xuống một nửa |
| `resolve_fks=False` | Bỏ qua FK khi reflect | Tránh race condition trong multi-thread; loader không cần biết quan hệ FK |
| Nullable `Int64` | Dùng `pd.Int64Dtype()` thay vì `int64` | Cho phép `NULL` trong cột số tiền — nhiều công ty có cột null hợp lệ |
| `backfill.py` | Job riêng cho backfill | Cho phép chạy lại lịch sử cho mã cụ thể mà không ảnh hưởng schedule |
