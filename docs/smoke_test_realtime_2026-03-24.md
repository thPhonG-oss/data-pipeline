# Smoke Test — Real-time Intraday Pipeline

> Ngày: 2026-03-24 (Thứ 2)
> Người thực hiện: Data Engineering Team
> Mục đích: Kiểm tra end-to-end pipeline DNSE MDDS → Redis Streams → PostgreSQL lần đầu tiên trong giờ giao dịch thực tế.

---

## Kết quả tổng quan

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| JWT Auth (DNSE) | ✅ PASS | investorId lấy thành công |
| MQTT Connection | ✅ PASS | Kết nối broker thành công |
| Topic Subscribe | ✅ PASS | 60 topics (30 symbols × 1m + 5m) |
| Redis Streams | ✅ PASS | Consumer groups tạo thành công |
| Stream Processor | ✅ PASS | Worker khởi động, đang chờ messages |
| Watchlist từ DB | ⚠️ WARNING | Cột `index_code` chưa tồn tại → dùng VN30 fallback (30 mã) |
| Data flow (pre-market) | ⏳ PENDING | Thị trường chưa mở (ATO 09:00) |
| Data flow (trong giờ) | ⏳ Chờ cập nhật | — |
| DB upsert `price_intraday` | ⏳ Chờ cập nhật | — |

---

## Chi tiết từng bước

### Chuẩn bị (07:21)

- `session_guard.py` đã cập nhật: `_SESSION_START = time(7, 0)` (trước: 08:45)
- Docker: `postgres` đã running, `redis` khởi động mới lúc 07:26

### Khởi động subscriber (07:26:34)

```
[auth] Lấy JWT token từ DNSE...
[auth] OK — investorId=1002161780
[subscriber] Kết nối MQTT broker (datafeed-lts-krx.dnse.com.vn:443)...
[subscriber] Kết nối MQTT thành công.
[watchlist] DB query failed: column "index_code" does not exist — using VN30 fallback.
[subscriber] Subscribed 60 topics (30 symbols × 2 timeframes).
```

**Kết quả:** Auth + MQTT connect + subscribe thành công. Warning watchlist không block hoạt động.

### Khởi động processor (07:26:34)

```
[processor] Tạo consumer group 'ohlc-processors' cho stream:ohlc:1m.
[processor] Tạo consumer group 'ohlc-processors' cho stream:ohlc:5m.
[processor] Bắt đầu — consumer: worker-MSI-10580
```

**Kết quả:** Consumer groups tạo thành công, processor đang block-wait trên Redis Streams.

### Kiểm tra Redis (07:28)

```
Redis ping: True
stream:ohlc:1m: 0 messages  (expected — market not open yet)
stream:ohlc:5m: 0 messages  (expected — market not open yet)
```

**Kết quả:** Redis hoạt động, streams rỗng vì ATO chưa bắt đầu (09:00).

---

## Vấn đề phát hiện

### [WARNING] Cột `index_code` thiếu trong bảng `companies`

**Mô tả:** `WatchlistManager._load_from_db()` query cột `index_code` nhưng bảng `companies` không có cột này.

**Impact:** Không nghiêm trọng — fallback sang VN30 hardcode (30 mã) hoạt động đúng.

**Cột hiện có trong `companies`:**
`symbol, company_name, company_name_eng, short_name, exchange, type, status, icb_code, listed_date, delisted_date, charter_capital, issue_share, company_id, isin, tax_code, created_at, updated_at`

**Fix cần làm (không urgent):**
Option A — Sửa query dùng cột thực tế (ví dụ filter theo danh sách hardcode VN30 symbols)
Option B — Thêm cột `index_code` vào bảng `companies` qua migration + sync từ vnstock

---

## Kết quả sau khi thị trường mở (cập nhật sau 09:00)

> Cập nhật lần 1: ...

| Metric | Giá trị | Thời điểm |
|---|---|---|
| `stream:ohlc:1m` length | — | — |
| `stream:ohlc:5m` length | — | — |
| `price_intraday` rows | — | — |
| Candle gần nhất | — | — |
| Latency (received_at - time) | — | — |

---

## Lệnh verify

```bash
# Kiểm tra Redis streams
python check_realtime.py

# Kiểm tra trực tiếp DB
docker compose exec postgres psql -U postgres -d stockapp -c \
  "SELECT symbol, resolution, COUNT(*) as candles, MAX(time) as last_candle
   FROM price_intraday GROUP BY symbol, resolution ORDER BY symbol, resolution;"

# Kiểm tra log subscriber
tail -f logs/realtime_subscriber_smoketest.log

# Kiểm tra log processor
tail -f logs/realtime_processor_smoketest.log
```

---

## Kết luận (tạm thời)

**Phase kết nối (pre-market): PASS**
- Auth DNSE: hoạt động
- MQTT: kết nối và subscribe thành công
- Redis + consumer groups: hoạt động
- Processor: sẵn sàng nhận data

**Chờ xác nhận sau 09:00 ATO:** data flow từ DNSE → Redis → PostgreSQL.
