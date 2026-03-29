# Đánh giá chuyển đổi sang TimescaleDB

> **Ngày:** 2026-03-22
> **Phạm vi:** `price_history` (giá lịch sử EOD) và `price_intraday` (OHLC real-time 1m/5m)
> **Kết luận nhanh:** Nên chuyển — đặc biệt `price_intraday` là ứng viên mạnh nhất

---

## 1. Bối cảnh hiện tại

### 1.1 Schema hai bảng giá

| Bảng | Loại dữ liệu | Granularity | Symbols | Ước tính rows |
|---|---|---|---|---|
| `price_history` | EOD batch (KBS/VNDirect) | 1 ngày/nến | ~1981 | ~2.5M (5 năm) |
| `price_intraday` | Real-time (DNSE MDDS) | 1m và 5m | VN30 (30) | ~450K/tháng |

**Tốc độ tăng trưởng `price_intraday` (VN30):**
- 1m: 30 symbols × 225 nến/ngày × 21 ngày/tháng ≈ **142,000 rows/tháng**
- 5m: 30 symbols × 45 nến/ngày × 21 ngày/tháng ≈ **28,000 rows/tháng**
- Tổng cộng: **~170,000 rows/tháng** (chỉ VN30)

Nếu mở rộng watchlist lên toàn bộ ~700 mã niêm yết HoSE/HNX:
- 1m: **~3.3 triệu rows/tháng** → ~40M rows/năm

### 1.2 Vấn đề với PostgreSQL thuần

| Vấn đề | Biểu hiện |
|---|---|
| **Partition thủ công** | Khi `price_intraday` vượt vài chục triệu rows, query `WHERE time >= X` chậm dần nếu không partition |
| **Retention thủ công** | Phải viết cron job riêng để `DELETE WHERE time < NOW() - INTERVAL '30 days'` — tốn I/O, ảnh hưởng write |
| **Không có continuous aggregates** | Muốn rollup 1m → 5m → 1H → 1D phải tự viết, tự maintain |
| **Compression** | PostgreSQL không nén time-series theo dạng columnar — lãng phí disk |

---

## 2. TimescaleDB là gì?

**TimescaleDB** là extension cho PostgreSQL, thêm khái niệm **Hypertable** — bảng được tự động phân vùng (partition) theo chiều thời gian thành các **chunks** nhỏ.

```
Hypertable: price_intraday
 ├── chunk_001: time [2026-01-01, 2026-01-08)   ← 1 tuần/chunk (cấu hình được)
 ├── chunk_002: time [2026-01-08, 2026-01-15)
 ├── chunk_003: time [2026-01-15, 2026-01-22)
 └── chunk_004: time [2026-01-22, ...]           ← chunk hiện tại
```

**Điểm quan trọng:** TimescaleDB là **extension của PostgreSQL** — vẫn dùng cùng driver (`psycopg2`), cùng SQL, cùng SQLAlchemy. Không cần thay đổi application code.

---

## 3. Lợi ích cụ thể cho dự án này

### 3.1 Automatic Partitioning — Không cần làm gì thêm

TimescaleDB tự chia `price_intraday` thành chunks theo thời gian. Query `WHERE time >= NOW() - INTERVAL '1 day'` chỉ scan đúng 1–2 chunks thay vì toàn bộ bảng. Hiệu suất ổn định kể cả khi bảng lên đến hàng trăm triệu rows.

### 3.2 Data Retention Policy — Tự động xóa dữ liệu cũ

Thay vì viết cron job DELETE thủ công:

```sql
-- Thay thế hoàn toàn cron job DELETE
SELECT add_retention_policy('price_intraday', INTERVAL '30 days');
```

TimescaleDB xóa theo chunk (drop cả file) thay vì DELETE từng row — nhanh hơn 100–1000x, không gây I/O spike.

### 3.3 Continuous Aggregates — Rollup tự động

Tính năng mạnh nhất cho dữ liệu giá: tự động tổng hợp nến 1m → nến 5m → nến 1H → nến 1D và giữ cập nhật real-time.

```
price_intraday (1m)    ──→  cagg_ohlc_5m    ──→  cagg_ohlc_1h    ──→  cagg_ohlc_1d
(raw, từ DNSE MDDS)         (tự động)             (tự động)             (tự động)
```

Lợi ích:
- Dashboard/API query nến 5m, 1H, 1D mà **không cần đọc bảng 1m** — truy vấn nhanh hơn nhiều bậc
- Khi có nến 1m mới, TimescaleDB cập nhật các aggregate ở trên theo cơ chế incremental (không recompute toàn bộ)
- Loại bỏ hoàn toàn bảng `price_history` về dài hạn — thay bằng continuous aggregate từ dữ liệu 1m

### 3.4 Compression — Giảm 90% dung lượng

TimescaleDB compress các chunks cũ theo dạng columnar. Với OHLCV time-series (giá trị thay đổi nhỏ, nhiều cột giống nhau):

| Loại | Ước tính dung lượng |
|---|---|
| PostgreSQL thuần (1 năm VN30 1m) | ~2–3 GB |
| TimescaleDB + compression | ~200–400 MB |

### 3.5 Tương thích hoàn toàn với code hiện tại

Do TimescaleDB là extension của PostgreSQL:
- Docker image: `timescale/timescaledb:latest-pg16` (thay `postgres:16-alpine`)
- `psycopg2`, SQLAlchemy, `INSERT ... ON CONFLICT DO UPDATE` — **không thay đổi**
- `processor.py`, `sync_prices.py` — **không cần sửa**

---

## 4. Thách thức và rủi ro

### 4.1 Ràng buộc UNIQUE trên Hypertable

**Vấn đề:** TimescaleDB yêu cầu **tất cả UNIQUE constraint phải bao gồm cột partition (time)**. Schema hiện tại đã thỏa điều này:

```sql
-- price_history: OK ✓
CONSTRAINT uq_price_history UNIQUE (symbol, date, source)
-- date = cột partition → hợp lệ

-- price_intraday: OK ✓
CONSTRAINT uq_price_intraday UNIQUE (symbol, time, resolution)
-- time = cột partition → hợp lệ
```

Cả hai bảng đều **sẵn sàng** để convert thành hypertable.

### 4.2 Không có SERIAL PRIMARY KEY trên Hypertable

**Vấn đề:** `BIGSERIAL PRIMARY KEY` trên hypertable không được khuyến khích — TimescaleDB không thể đảm bảo tính duy nhất của sequence khi có nhiều chunks. Thực tế với dự án này, cột `id` trong `price_intraday` và `price_history` được dùng làm surrogate key nhưng **không có query nào dùng WHERE id = ?**.

**Giải pháp:** Bỏ cột `id`, dùng `(symbol, time, resolution)` làm natural key — đây là cách đúng đắn cho time-series data.

### 4.3 Migration dữ liệu hiện có

Nếu đã có dữ liệu trong bảng PostgreSQL cũ, cần:
1. Export data
2. Convert bảng thành hypertable
3. Import lại

Nếu chạy từ đầu (fresh install với image mới), không cần bước này.

### 4.4 Docker image khác biệt

```yaml
# Hiện tại
image: postgres:16-alpine          # 85 MB

# TimescaleDB
image: timescale/timescaledb:latest-pg16   # ~200 MB
```

Size image lớn hơn, nhưng không ảnh hưởng đến performance.

---

## 5. So sánh tổng quan

| Tiêu chí | PostgreSQL 16 (hiện tại) | TimescaleDB |
|---|---|---|
| **Setup phức tạp** | Thấp | Thấp (chỉ đổi Docker image) |
| **Hiệu suất query time-range** | Trung bình (full scan khi >10M rows) | Cao (chỉ scan chunk cần thiết) |
| **Data retention** | Thủ công (cron DELETE) | Tự động (drop chunk) |
| **Rollup (5m, 1H, 1D)** | Tự viết | Built-in continuous aggregates |
| **Compression** | Không | Có (up to 90%) |
| **Tương thích code** | N/A | 100% (cùng SQL, cùng driver) |
| **Tương thích migration** | N/A | Cần bỏ `id BIGSERIAL` |
| **Community/Support** | Rất lớn | Lớn (Timescale Inc. + OSS) |
| **License** | PostgreSQL | TimescaleDB License (free cho single-node) |

---

## 6. Đề xuất

### Ưu tiên cao — `price_intraday`

`price_intraday` là ứng viên **lý tưởng** cho TimescaleDB vì:
- Tốc độ ghi cao (real-time, liên tục trong giờ giao dịch)
- Cần retention tự động (1m=30 ngày, 5m=180 ngày)
- Sẽ có rollup 5m, 1H, 1D phục vụ dashboard/API
- Volume tăng tuyến tính theo số symbols trong watchlist

### Ưu tiên trung bình — `price_history`

`price_history` (EOD daily) ít cấp thiết hơn vì:
- Ghi 1 lần/ngày (batch), không có áp lực write
- ~2.5M rows/5 năm — PostgreSQL vẫn xử lý tốt
- Về dài hạn, có thể thay thế bằng continuous aggregate từ `price_intraday` 1m

**Khuyến nghị:** Khi đã có continuous aggregate `cagg_ohlc_1d` từ `price_intraday`, bảng `price_history` có thể deprecated và chỉ giữ để lưu `close_adj` (adjusted close) từ VNDirect — dữ liệu mà DNSE MDDS không cung cấp.

### Không cần TimescaleDB — các bảng khác

Các bảng `balance_sheets`, `income_statements`, `companies`, `icb_industries`, v.v. **không phải time-series thuần** — không có lợi ích đáng kể khi dùng TimescaleDB.

---

## 7. Kế hoạch chuyển đổi (4 bước)

### Bước 1 — Đổi Docker image

```
postgres:16-alpine  →  timescale/timescaledb:latest-pg16
```

Thêm bước `CREATE EXTENSION IF NOT EXISTS timescaledb;` vào migration đầu tiên.

**Lưu ý:** Nếu volume `postgres_data` đã có dữ liệu từ `postgres:16-alpine`, cần export trước khi đổi image.

### Bước 2 — Migration mới: convert hypertables

Tạo `db/migrations/009_timescaledb_hypertables.sql`:

1. Bỏ cột `id` khỏi `price_intraday` và `price_history`
2. Gọi `SELECT create_hypertable('price_intraday', 'time', chunk_time_interval => INTERVAL '1 week')`
3. Gọi `SELECT create_hypertable('price_history', 'date', chunk_time_interval => INTERVAL '3 months')`
4. Thêm retention policy cho `price_intraday`
5. Bật compression cho chunks cũ hơn 7 ngày

### Bước 3 — Continuous Aggregates

Tạo `db/migrations/010_continuous_aggregates.sql`:

1. `cagg_ohlc_5m` — từ `price_intraday` (resolution=1), group by 5m
2. `cagg_ohlc_1h` — từ `cagg_ohlc_5m`, group by 1H
3. `cagg_ohlc_1d` — từ `cagg_ohlc_1h`, group by 1D
4. Thêm refresh policy cho các aggregate trên

### Bước 4 — Cập nhật `processor.py` (tối giản)

Chỉ cần bỏ cột `id` khỏi dict trong `_transform_message()`. Không thay đổi logic khác.

---

## 8. Ước tính lợi ích sau khi chuyển đổi

| Chỉ số | Trước (PostgreSQL) | Sau (TimescaleDB) |
|---|---|---|
| Query 1 ngày gần nhất (30 symbols, 1m) | ~50–200ms (full scan nếu >10M rows) | ~2–5ms (1 chunk) |
| Disk `price_intraday` sau 1 năm (VN30) | ~2 GB | ~200 MB |
| Retention cleanup | Cron job DELETE, I/O spike | Drop chunk, < 1ms |
| Rollup 5m/1H/1D | Không có / tự code | Automatic, real-time |
| Mở rộng watchlist (700 mã) | Cần partition thủ công | Transparent |

---

## 9. Kết luận

**Nên chuyển sang TimescaleDB.** Chi phí chuyển đổi thấp (chủ yếu là đổi Docker image và viết thêm 2 migration files), trong khi lợi ích dài hạn cao — đặc biệt khi mở rộng watchlist vượt VN30 hoặc khi cần xây dashboard real-time.

**Thứ tự ưu tiên thực hiện:**
1. `price_intraday` → hypertable + retention policy (Phase tiếp theo)
2. Continuous aggregates cho 5m/1H/1D (sau khi có dữ liệu 1m ổn định)
3. `price_history` → hypertable (tùy chọn, ít cấp thiết)
