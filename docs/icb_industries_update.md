# Cập nhật nguồn dữ liệu ICB Industries

> **Ngày:** 2026-03-22
> **Phạm vi thay đổi:** `etl/extractors/listing.py`, `etl/transformers/listing.py`, `jobs/sync_listing.py`, `etl/transformers/company.py`, `db/migrations/008_icb_definition.sql`

---

## 1. Đánh giá dữ liệu `docs/icb-industries.json`

### 1.1 Cấu trúc file JSON

File `icb-industries.json` là bộ phân loại ngành chuẩn **ICB (Industry Classification Benchmark)** do FTSE Russell phát hành, gồm **4 cấp độ phân cấp lồng nhau**:

```
Level 1 — Industry (Lĩnh vực):         id 2 chữ số   (ví dụ: 10, 15, 20 ...)
Level 2 — Supersector (Siêu ngành):    id 4 chữ số   (ví dụ: 1010, 3020 ...)
Level 3 — Sector (Nhóm ngành):         id 6 chữ số   (ví dụ: 101010, 302020 ...)
Level 4 — Subsector (Ngành cụ thể):    id 8 chữ số   (ví dụ: 10101010, 30202015 ...)
```

Cấu trúc JSON lồng nhau theo thứ tự: `industries → supersectors → sectors → subsectors`.

**Thống kê dữ liệu:**

| Cấp độ | Số lượng | Ví dụ |
|---|---|---|
| Level 1 — Industry | 11 | Technology, Financials, Real Estate |
| Level 2 — Supersector | 20 | Banks, Financial Services, Insurance |
| Level 3 — Sector | 45 | Pharmaceuticals and Biotechnology, Banks |
| Level 4 — Subsector | 173 | Software, Banks, Life Insurance, Iron and Steel |
| **Tổng cộng** | **249** | |

### 1.2 Ưu điểm so với dữ liệu từ vnstock API

| Tiêu chí | vnstock API (`industries_icb()`) | File JSON |
|---|---|---|
| Tên tiếng Anh | Có (`en_icb_name`) | Có (`name`) |
| Tên tiếng Việt | Có (từ nguồn VCI) | **Thêm thủ công** (dịch đầy đủ) |
| `parent_code` | **Không có** (NULL) | **Có** (suy ra từ cấu trúc lồng nhau) |
| `definition` | **Không có** | **Có** (cho level 4, ~173 entries) |
| Quan hệ phân cấp | Phẳng, không liên kết | Đầy đủ cây thứ bậc |
| Phụ thuộc mạng | Cần kết nối internet | **Không cần** (local file) |
| Ổn định | Phụ thuộc vnstock API | **Ổn định** (file tĩnh) |

### 1.3 Kết luận đánh giá

File JSON **phù hợp cao** để thay thế nguồn vnstock cho ICB industries vì:

1. **Dữ liệu phong phú hơn:** có `parent_code` để dựng cây phân cấp, có `definition` để mô tả chi tiết
2. **Không phụ thuộc API ngoài:** giảm điểm thất bại và tăng tốc độ `sync_listing`
3. **Chuẩn quốc tế:** ICB FTSE Russell là tiêu chuẩn được dùng toàn cầu, ổn định
4. **Mã ICB tương thích:** ID 2–8 chữ số đều vừa trong `VARCHAR(10)` hiện tại

**Hạn chế duy nhất:** Khi ICB có cập nhật mới (rất hiếm, thường vài năm/lần), cần cập nhật file JSON thủ công.

---

## 2. Các thay đổi đã thực hiện

### 2.1 Migration mới — `db/migrations/008_icb_definition.sql`

Thêm cột `definition TEXT` vào bảng `icb_industries`:

```sql
ALTER TABLE icb_industries ADD COLUMN IF NOT EXISTS definition TEXT;
```

- Cột này chỉ được điền tại **level 4** (Subsector)
- Level 1–3 để `NULL`
- Lưu mô tả tiếng Anh nguyên gốc từ FTSE Russell

**Chạy migration:**
```bash
python -m db.migrate
# hoặc Docker tự chạy khi build lần đầu
```

### 2.2 Extractor — `etl/extractors/listing.py`

Thêm phương thức `load_icb_from_json()`:

```python
records = extractor.load_icb_from_json()  # Đọc docs/icb-industries.json
# Trả về list[dict] với 249 records, mỗi record gồm:
# {icb_code, en_icb_name, icb_name (tiếng Việt), level, parent_code, definition}
```

Phương thức này:
- Đọc file tại `docs/icb-industries.json` (tự động định vị theo `__file__`)
- Duyệt 4 cấp lồng nhau, tính `parent_code` từ cấu trúc JSON
- Tra dictionary dịch thuật tích hợp sẵn để điền `icb_name` tiếng Việt
- Phương thức cũ `extract_industries()` vẫn còn (dự phòng nếu cần)

**Bảng dịch thuật tích hợp trong extractor** — 4 dictionaries riêng cho từng level:

```python
_VI_LEVEL1 = {10: "Công nghệ", 15: "Viễn thông", 20: "Y tế", ...}
_VI_LEVEL2 = {1010: "Công nghệ", 3010: "Ngân hàng", 3020: "Dịch vụ tài chính", ...}
_VI_LEVEL3 = {101010: "Phần mềm và Dịch vụ máy tính", 301010: "Ngân hàng", ...}
_VI_LEVEL4 = {10101010: "Dịch vụ máy tính", 10101015: "Phần mềm", ...}
```

Nếu một ID chưa có trong dictionary dịch, hệ thống tự fallback về tên tiếng Anh (không bỏ record).

### 2.3 Transformer — `etl/transformers/listing.py`

Thêm phương thức `transform_industries_from_json()`:

```python
df = transformer.transform_industries_from_json(records)
# Output DataFrame: icb_code, icb_name, en_icb_name, level, parent_code, definition
# Đúng schema bảng icb_industries
```

### 2.4 Job — `jobs/sync_listing.py`

Thay thế bước 1 (ICB Industries) từ dùng vnstock API sang đọc JSON:

**Trước:**
```python
df_raw = extractor.extract_industries()          # Gọi vnstock API
df = transformer.transform_industries(df_raw)
```

**Sau:**
```python
records = extractor.load_icb_from_json()         # Đọc local JSON
df = transformer.transform_industries_from_json(records)
```

Bước 2 (Companies) **không thay đổi** — vẫn lấy từ vnstock API vì danh sách mã chứng khoán thay đổi thường xuyên.

### 2.5 Lookup icb_code — `etl/transformers/company.py`

Cập nhật hàm `_lookup_icb_code()` để tra cứu theo cả tên tiếng Việt lẫn tiếng Anh:

**Trước:**
```sql
WHERE level = 4 AND icb_name = :name
```

**Sau:**
```sql
WHERE level = 4 AND (icb_name = :name OR en_icb_name = :name)
```

**Lý do:** VCI API trả về `icb_name4` (tên ngành cụ thể của công ty). Tùy mã cổ phiếu, VCI có thể trả về tên tiếng Việt hoặc tiếng Anh. Tra cứu cả hai đảm bảo `icb_code` được gán đúng cho phần lớn công ty.

---

## 3. Cấu trúc bảng `icb_industries` sau cập nhật

```sql
icb_code        VARCHAR(10) PRIMARY KEY    -- "10", "1010", "101010", "10101010"
icb_name        VARCHAR(300) NOT NULL      -- Tên tiếng Việt (đã dịch)
en_icb_name     VARCHAR(300)               -- Tên tiếng Anh gốc từ JSON
level           SMALLINT (1–4)             -- 1=Lĩnh vực, 2=Siêu ngành, 3=Nhóm ngành, 4=Ngành cụ thể
parent_code     VARCHAR(10)                -- FK tự tham chiếu (NULL cho level 1)
definition      TEXT                       -- Mô tả (chỉ level 4, tiếng Anh)
created_at      TIMESTAMP
```

**Ví dụ dữ liệu sau sync:**

| icb_code | icb_name | en_icb_name | level | parent_code | definition |
|---|---|---|---|---|---|
| 10 | Công nghệ | Technology | 1 | NULL | NULL |
| 1010 | Công nghệ | Technology | 2 | 10 | NULL |
| 101010 | Phần mềm và Dịch vụ máy tính | Software and Computer Services | 3 | 1010 | NULL |
| 10101015 | Phần mềm | Software | 4 | 101010 | Publishers and distributors... |
| 30101010 | Ngân hàng | Banks | 4 | 301010 | Companies with a banking license... |

---

## 4. Luồng đồng bộ ICB sau thay đổi

```
sync_listing (chạy Chủ Nhật 01:00)
    │
    ├── [1] Bước ICB Industries
    │       ├── extractor.load_icb_from_json()
    │       │       └── Đọc docs/icb-industries.json (249 records, không cần internet)
    │       ├── transformer.transform_industries_from_json(records)
    │       └── loader.load(df, "icb_industries", ["icb_code"])
    │               └── UPSERT 249 rows (thường < 1 giây)
    │
    └── [2] Bước Companies
            ├── extractor.extract_symbols()   ← vẫn dùng vnstock API (vnd)
            ├── transformer.transform_symbols(df)
            └── loader.load(df, "companies", ["symbol"])

sync_company (chạy Thứ Hai 02:00)
    │
    └── Phase A: Cập nhật icb_code cho từng công ty
            ├── extractor.extract_overview(symbol) → icb_name4 (từ VCI)
            └── _lookup_icb_code(icb_name4)
                    └── SELECT icb_code FROM icb_industries
                        WHERE level = 4
                          AND (icb_name = :name OR en_icb_name = :name)
```

---

## 5. Lưu ý khi cập nhật ICB trong tương lai

ICB FTSE Russell định kỳ cập nhật ~2–3 năm/lần. Khi có phiên bản mới:

1. Thay thế file `docs/icb-industries.json` bằng phiên bản mới
2. Bổ sung translation trong `_VI_LEVEL1/2/3/4` tại `etl/extractors/listing.py` cho các ID mới
3. Chạy `python main.py sync_listing` để cập nhật DB
4. Chạy `python main.py sync_company` để cập nhật `icb_code` cho tất cả công ty

Nếu ICB xóa một ngành cũ, bản ghi cũ trong DB **không bị xóa** — chỉ không được cập nhật thêm. Các công ty đã gán `icb_code` cũ vẫn giữ nguyên cho đến khi `sync_company` cập nhật lại.
