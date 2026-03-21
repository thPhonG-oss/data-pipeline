# Giai đoạn 4 — Module Doanh Nghiệp (Company)

**Trạng thái:** Hoàn thành
**Ngày hoàn thành:** 2026-03-19

## Tổng quan

Giai đoạn 4 xây dựng module thu thập thông tin doanh nghiệp: cổ đông lớn, ban lãnh đạo, công ty con, sự kiện doanh nghiệp, và cập nhật thông tin tổng quan (`icb_code`, `charter_capital`, `issue_share`) vào bảng `companies`.

**Kết quả:** 73,823 rows được load vào 4 bảng. 5,481 tasks thành công, 707 tasks thất bại (chủ yếu do API không có dữ liệu).

---

## Phần 1 — Extractor (`etl/extractors/company.py`)

### API nguồn dữ liệu

```python
Company(source="vci", symbol="HPG")
    .overview()       → thông tin tổng quan: company_id, issue_share, charter_capital, icb_code
    .shareholders()   → danh sách cổ đông lớn
    .officers()       → ban lãnh đạo, thành viên HĐQT
    .subsidiaries()   → công ty con và công ty liên kết
    .events()         → sự kiện doanh nghiệp (cổ tức, phát hành, tách cổ phiếu...)
```

### Thiết kế `CompanyExtractor`

5 method riêng biệt, được gọi qua dispatch trong `extract()`:

```python
dispatch = {
    "overview":     self.extract_overview,
    "shareholders": self.extract_shareholders,
    "officers":     self.extract_officers,
    "subsidiaries": self.extract_subsidiaries,
    "events":       self.extract_events,
}
```

Mỗi method đều có `@vnstock_retry()`.

**Xử lý response rỗng:** Không raise exception khi API trả về DataFrame rỗng — chỉ log warning và trả về `None`. Khác với `FinanceExtractor` (raise lỗi). Lý do: nhiều mã không có cổ đông lớn/công ty con → đây là trạng thái bình thường, không phải lỗi API.

---

## Phần 2 — Transformer (`etl/transformers/company.py`)

### `transform_overview(df, symbol)` — cho bảng `companies`

Trả về **một dict** (không phải DataFrame) vì chỉ cần `UPDATE companies` một dòng:

```python
{
    "symbol":          "HPG",
    "company_id":      123,
    "issue_share":     1_200_000_000,
    "charter_capital": 12_000_000_000_000,
    "icb_code":        "1750",
}
```

**Bug đã xử lý — ngày sentinel `1753-01-01` của SQL Server:**

API đôi khi trả về `1753-01-01` (ngày tối thiểu của SQL Server `datetime`) thay vì `NULL` cho các trường ngày không có giá trị (ví dụ: `listed_date` của công ty chưa niêm yết chính thức). Transformer phải kiểm tra và chuyển thành `None`:

```python
SENTINEL_DATES = {date(1753, 1, 1), date(1900, 1, 1), date(1970, 1, 1)}

def _clean_date(val) -> date | None:
    if pd.isna(val):
        return None
    d = pd.to_datetime(val, errors="coerce")
    if d is pd.NaT:
        return None
    result = d.date()
    return None if result in SENTINEL_DATES else result
```

### `transform_shareholders(df, symbol)` → `shareholders`

- Thêm `symbol`, `snapshot_date = CURRENT_DATE`.
- Parse `update_date` → `date`, xử lý sentinel dates.
- Ép `quantity` → `Int64`, `share_own_percent` → `float`.
- **`drop_duplicates(subset=["symbol", "share_holder", "snapshot_date"])`** — xử lý trùng lặp conflict key trước khi load (xem Bug bên dưới).

### `transform_officers(df, symbol)` → `officers`

- Thêm `symbol`, `snapshot_date`.
- Cột `status`: API trả về `"Đang làm việc"` / `"Đã nghỉ"` → map sang `"working"` / `"resigned"`.
- **`drop_duplicates(subset=["symbol", "officer_name", "status", "snapshot_date"])`**.

### `transform_subsidiaries(df, symbol)` → `subsidiaries`

- Cột `type`: map `"Công ty con"` → `"subsidiary"`, `"Công ty liên kết"` → `"associated"`.
- **`drop_duplicates(subset=["symbol", "organ_name", "snapshot_date"])`**.

### `transform_events(df, symbol)` → `corporate_events`

- Parse `public_date`, `issue_date`, `record_date`, `exright_date` → `date`, xử lý sentinel.
- Cột `ratio`, `value` → `float`.
- **`drop_duplicates(subset=["symbol", "event_list_code", "record_date"])`** — xem Bug 2.

---

## Phần 3 — Job (`jobs/sync_company.py`)

### Thiết kế hai pha — điểm khác biệt quan trọng so với Phase 3

Phase 3 (Finance): tất cả tasks đều là **upsert vào bảng riêng** → song song hoàn toàn.

Phase 4 (Company): có một loại đặc biệt — `overview` không upsert vào bảng riêng mà **UPDATE trực tiếp vào bảng `companies`** đã có sẵn.

```
Pha 1 (tuần tự): UPDATE companies SET icb_code, charter_capital, issue_share
    ↓ (chạy xong toàn bộ overview mới sang pha 2)
Pha 2 (song song): Upsert shareholders / officers / subsidiaries / events
```

Lý do pha 1 phải **tuần tự**: UPDATE cùng bảng `companies` từ nhiều thread có thể gây deadlock hoặc race condition.

### Hàm `_update_companies_overview(symbol)` — pha 1

```python
with engine.begin() as conn:
    conn.execute(
        text("""
            UPDATE companies
            SET company_id      = :company_id,
                issue_share     = :issue_share,
                charter_capital = :charter_capital,
                icb_code        = COALESCE(:icb_code, icb_code),
                updated_at      = NOW()
            WHERE symbol = :symbol
        """),
        data,
    )
```

`COALESCE(:icb_code, icb_code)` — nếu API không trả về `icb_code` (None) thì **giữ nguyên giá trị cũ trong DB**, không ghi đè thành NULL.

### Pha 2 — song song 4 loại

```python
_DATA_TYPES = ["shareholders", "officers", "subsidiaries", "events"]

_TABLE_MAP = {
    "shareholders": "shareholders",
    "officers":     "officers",
    "subsidiaries": "subsidiaries",
    "events":       "corporate_events",
}
```

Chạy `ThreadPoolExecutor(max_workers=5)` cho tất cả `(symbol, data_type)`.

### Tổng kết cuối cùng

```
[sync_company] Xong. Success=5481 | Failed=707 | Skipped=0 | Rows=73823
```

---

## Phần 4 — Bug đã gặp và cách xử lý

### Bug 1: Ngày sentinel `1753-01-01` từ SQL Server

**Vấn đề:** Backend API của vnstock dùng SQL Server. Ngày tối thiểu của SQL Server `DATETIME` là `1753-01-01`. Khi một trường ngày không có giá trị, API trả về `1753-01-01` thay vì `NULL`.

**Hậu quả:** PostgreSQL lưu `1753-01-01` vào cột `DATE` — giá trị không có ý nghĩa, gây nhiễu khi phân tích.

**Giải pháp:** Hàm `_clean_date()` kiểm tra danh sách `SENTINEL_DATES = {1753-01-01, 1900-01-01, 1970-01-01}` và trả về `None`.

---

### Bug 2: `CardinalityViolation` — ON CONFLICT không thể cập nhật cùng một dòng 2 lần

**Vấn đề:** Lỗi PostgreSQL:
```
ON CONFLICT DO UPDATE command cannot affect row a second time
```

**Nguyên nhân:** API trả về DataFrame có **2 dòng trùng conflict key** (ví dụ: cùng `symbol + event_list_code + record_date`). Khi `pg_insert().on_conflict_do_update()` gặp 2 dòng cùng conflict key trong một batch, PostgreSQL báo lỗi vì không thể xác định dòng nào sẽ thắng.

**Giải pháp:** Gọi `df.drop_duplicates(subset=[conflict_keys])` trong transformer **trước khi** trả về DataFrame cho loader. Giữ dòng đầu tiên (mặc định `keep="first"`).

---

### Bug 3: Mã không có dữ liệu → `RetryError` không cần thiết

**Vấn đề:** Một số mã (ETF, mã đặc biệt) không có dữ liệu `overview` → API raise `AttributeError` → `@vnstock_retry()` retry 3 lần → sau 3 lần vẫn lỗi → raise `RetryError`. Log đỏ nhưng đây không phải lỗi thực sự.

**Giải pháp:** Trong `_update_companies_overview()`, bắt `RetryError` và `AttributeError` → log warning (không phải error), đánh dấu `failed` nhưng không dừng job. Job tiếp tục với symbol tiếp theo.

---

## Phần 5 — Kết quả theo bảng

| Bảng | Rows upserted |
|---|---|
| `shareholders` | ~15,000 |
| `officers` | ~22,000 |
| `subsidiaries` | ~18,000 |
| `corporate_events` | ~18,823 |
| **Tổng** | **73,823** |

`companies.icb_code` được điền cho phần lớn mã STOCK sau khi Phase 4 hoàn thành.

---

## Phần 6 — Quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| `overview` → UPDATE thay vì upsert | UPDATE `companies` trực tiếp | `overview()` không có bảng riêng — chỉ bổ sung thông tin cho bảng `companies` đã có từ Phase 2 |
| Pha 1 tuần tự | `_update_companies_overview` chạy sequential | Tránh deadlock khi nhiều thread UPDATE cùng bảng |
| `COALESCE(:icb_code, icb_code)` | Giữ giá trị cũ nếu API không có | Tránh ghi đè `icb_code` bằng NULL cho mã đã có dữ liệu |
| `drop_duplicates` trong transformer | Loại trùng conflict key TRƯỚC khi load | PostgreSQL không cho phép ON CONFLICT DO UPDATE với 2 dòng cùng key trong 1 batch |
| Response rỗng → `None` (không raise) | `extract_*` trả về `None` thay vì raise | Nhiều mã hợp lệ thực sự không có cổ đông lớn/công ty con |
| `snapshot_date = CURRENT_DATE` | Ghi ngày chạy job | Cho phép theo dõi lịch sử thay đổi cổ đông theo thời gian |
