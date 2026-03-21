# Giai đoạn 2 — Module Danh Mục (Listing)

**Trạng thái:** Hoàn thành
**Ngày hoàn thành:** 2026-03-18

## Tổng quan

Giai đoạn 2 xây dựng module đầu tiên thu thập dữ liệu thực từ vnstock: đồng bộ danh mục phân ngành ICB và toàn bộ mã chứng khoán đang niêm yết vào bảng `icb_industries` và `companies`.

**Kết quả:** ~1,700 mã chứng khoán và ~200 ngành ICB được load vào DB.

---

## Phần 1 — Extractor (`etl/extractors/listing.py`)

### Quyết định nguồn dữ liệu quan trọng

API `Listing(source="vci").all_symbols()` chỉ trả về **2 cột**: `symbol` và `organ_name`. Thiếu toàn bộ thông tin cần thiết (exchange, type, status, listed_date...).

→ **Giải pháp:** Dùng nguồn `vnd` cho `all_symbols()`, giữ nguyên `vci` cho `industries_icb()`.

```python
_SYMBOLS_SOURCE = "vnd"   # Hằng số nội bộ, không thay đổi theo settings.vnstock_source

class ListingExtractor(BaseExtractor):
    def extract_symbols(self) -> pd.DataFrame:
        df = Listing(source=_SYMBOLS_SOURCE).all_symbols()
        # → Trả về: symbol, organ_name, exchange, type, status, listed_date, ...

    def extract_industries(self) -> pd.DataFrame:
        df = Listing(source=self.source).industries_icb()
        # → Trả về: icb_code, icb_name, en_icb_name, level, parent_code
```

Cả hai method đều dùng `@vnstock_retry()` — tự động retry 3 lần với exponential backoff nếu API lỗi.

---

## Phần 2 — Transformer (`etl/transformers/listing.py`)

### `transform_industries(df)` — xử lý icb_industries

**Các bước:**
1. Đổi tên cột API → tên cột schema DB.
2. Ép kiểu `level` → `int`.
3. Thay `parent_code` rỗng/NaN → `None` (DB lưu NULL, không phải chuỗi rỗng).
4. Loại dòng thiếu `icb_code` hoặc `icb_name`.

**Lưu ý:** API không cung cấp `parent_code` cho hầu hết ngành → cột này để `NULL`.

### `transform_symbols(df)` — xử lý companies

**Các bước:**
1. Đổi tên cột.
2. Chuẩn hóa `exchange`: uppercase, map giá trị lạ → giá trị hợp lệ trong `VALID_EXCHANGES = ["HOSE", "HNX", "UPCOM"]`.
3. Chuẩn hóa `type`: API trả về `"IFC"` → map sang `"FUND"` (theo CHECK constraint trong DB). Map đầy đủ: `STOCK, ETF, BOND, CW, FUND`.
4. Chuẩn hóa `status`: mặc định `"listed"` nếu không có.
5. Parse `listed_date` → `date` object, để `None` nếu không parse được.
6. Để `icb_code = None` — API `all_symbols()` không trả về icb_code; sẽ được cập nhật sau ở Phase 4 (`sync_company` gọi `overview()`).

---

## Phần 3 — Job (`jobs/sync_listing.py`)

### Thứ tự chạy — FK constraint bắt buộc

```
1. icb_industries  ← phải insert TRƯỚC
2. companies       ← companies.icb_code REFERENCES icb_industries(icb_code)
```

Nếu `icb_industries` lỗi → **dừng ngay**, không chạy `companies`. Logic này được đảm bảo bằng `return results` sớm:

```python
except Exception as exc:
    results["icb_industries"]["status"] = "failed"
    logger.error(f"[sync_listing] icb_industries thất bại: {exc}")
    loader.load_log(job_name=JOB_SYNC_LISTING, status="failed", ...)
    return results   # Không chạy companies nếu ICB lỗi
```

### Luồng xử lý

```
extract_industries() → transform_industries() → load("icb_industries", conflict=["icb_code"])
    ↓ (chỉ khi thành công)
time.sleep(request_delay)
    ↓
extract_symbols() → transform_symbols() → load("companies", conflict=["symbol"])
```

Mỗi bước đều ghi `pipeline_logs` (INSERT khi bắt đầu, UPDATE khi kết thúc).

### Hàm `run()` không nhận tham số

`sync_listing` luôn chạy cho toàn bộ danh mục — không có khái niệm "chạy cho mã cụ thể". Upsert `ON CONFLICT DO UPDATE` đảm bảo chạy lại nhiều lần không sinh trùng.

```bash
python jobs/sync_listing.py
```

---

## Phần 4 — Kết quả & Bug đã gặp

### Kết quả thực tế

| Bảng | Rows upserted |
|---|---|
| `icb_industries` | ~200 |
| `companies` | ~1,700 |

### Vấn đề đã xử lý

**`icb_code` trong companies luôn là NULL sau Phase 2:**
- Đây là **thiết kế chủ ý** — `all_symbols()` không trả về icb_code.
- Sẽ được điền bằng `UPDATE companies SET icb_code = ...` trong Phase 4 (`sync_company` → `overview()`).

**Giá trị `type = "IFC"` từ API:**
- Một số mã trả về type `"IFC"` (quỹ đầu tư) — không nằm trong CHECK constraint.
- Giải pháp: map `"IFC"` → `"FUND"` trong transformer.

---

## Phần 5 — Quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| Nguồn dữ liệu `all_symbols()` | Dùng `vnd` thay vì `vci` | `vci` chỉ trả về 2 cột, thiếu exchange/type/status |
| `icb_code` trong companies | Để NULL, Phase 4 sẽ update | `all_symbols()` không trả về icb_code; tránh join phức tạp ngay Phase 2 |
| Thứ tự chạy | `icb_industries` → `companies` | FK constraint bắt buộc |
| Dừng sớm khi ICB lỗi | `return results` | Không có ý nghĩa insert companies nếu bảng ICB cha chưa có dữ liệu |
| Không có `--symbol` | N/A | Listing là global — không có khái niệm per-symbol |
