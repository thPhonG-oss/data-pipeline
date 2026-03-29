# Real-time Pipeline — Tài liệu kỹ thuật

> Cập nhật: 2026-03-28
> Trạng thái: **✅ Hoàn thành (RT-1 đến RT-4)**
> Tác giả: Data Engineering Team

---

## 1. Tổng quan

Pipeline real-time thu thập nến OHLC (1 phút, 5 phút) từ **DNSE MDDS** trong giờ giao dịch và lưu vào PostgreSQL bảng `price_intraday`, phục vụ Java Backend API và React Frontend dashboard.

### So sánh với batch pipeline

| | Batch Pipeline | Real-time Pipeline |
|---|---|---|
| Trigger | APScheduler cron | Liên tục (streaming) |
| Dữ liệu | EOD OHLCV (1 nến/ngày) | Intraday 1m & 5m |
| Nguồn | KBS REST (via vnstock) | DNSE MDDS (MQTT/WSS) |
| Bảng đích | `price_history` | `price_intraday` |
| Active | 24/7 (cron) | T2–T6, 07:00–15:15 |
| Xung đột | Không | Không (bảng tách biệt) |

---

## 2. Kiến trúc tổng thể

```
DNSE KRX Exchange (sàn giao dịch)
         │
         │ Raw market feed (KRX protocol)
         ▼
DNSE MDDS Broker
  datafeed-lts-krx.dnse.com.vn:443
         │
         │ MQTT v5 over WebSocket Secure (WSS)
         │ Auth: JWT token + investorId
         ▼
┌─────────────────────────────────┐
│        MQTTSubscriber            │   realtime/subscriber.py
│                                  │   • JWT auto-refresh mỗi 7h
│  • Auth DNSE → JWT + investorId  │   • Subscribe OHLC 1m & 5m
│  • Subscribe watchlist symbols   │   • Reconnect với backoff
│  • Deserialize JSON payload      │   • Active T2–T6, 07:00–15:15
└────────────────┬────────────────┘
                 │ XADD (Redis Streams)
                 │ stream:ohlc:1m
                 │ stream:ohlc:5m
                 ▼
┌─────────────────────────────────┐
│          Redis Streams           │   stockapp_redis (Docker)
│                                  │   • Retention: maxlen 500,000
│  stream:ohlc:1m                  │   • AOF persistent
│  stream:ohlc:5m                  │   • Consumer groups
└────────────────┬────────────────┘
                 │ XREADGROUP (Consumer Group: ohlc-processors)
                 │ Batch 100 messages, block 5s
                 ▼
┌─────────────────────────────────┐
│       StreamProcessor            │   realtime/processor.py
│                                  │   • Daemon thread (24/7)
│  • _validate_message()           │   • ACK sau upsert thành công
│  • _transform_message()          │   • XAUTOCLAIM pending > 30m
│  • Batch upsert PostgreSQL       │
└────────────────┬────────────────┘
                 │ INSERT ... ON CONFLICT DO UPDATE
                 ▼
┌─────────────────────────────────┐
│          PostgreSQL              │   stockapp_db (TimescaleDB)
│                                  │
│  price_intraday (hypertable)    │   ← Java SpringBoot Backend đọc
│  price_history  (batch EOD)     │   ← Giữ nguyên, không thay đổi
└─────────────────────────────────┘
```

---

## 3. Các thành phần đã implement

### 3.1 `realtime/auth.py` — `DNSEAuthManager`

Quản lý JWT token và investorId để xác thực MQTT.

**Auth flow (2 bước):**
```
POST https://api.dnse.com.vn/user-service/api/auth
  body: { username, password }
  → { token: "<JWT>" }           # Hết hạn sau 8h

GET https://api.dnse.com.vn/user-service/api/me
  header: Authorization: Bearer <token>
  → { investorId: 1002161780 }  # Dùng làm MQTT username
```

**API:**
```python
auth = DNSEAuthManager(username=..., password=...)
token       = auth.get_token()       # str JWT, tự refresh khi < 1h còn lại
investor_id = auth.get_investor_id() # str, dùng làm MQTT username
auth.invalidate()                    # Buộc refresh (gọi sau MQTT auth fail)
```

**Token lifecycle:** TTL 8h, refresh khi còn < 1h (tức là mỗi 7h).

---

### 3.2 `realtime/watchlist.py` — `WatchlistManager`

Quản lý danh sách symbol cần subscribe. Ưu tiên giảm dần:

1. `REALTIME_WATCHLIST=HPG,VCB,FPT,...` trong `.env`
2. Query DB: `SELECT symbol FROM companies WHERE status='listed' AND index_code LIKE '%VN30%'`
3. Hardcode fallback: 30 mã VN30 hiện tại

```python
wm = WatchlistManager(watchlist_str=settings.realtime_watchlist)
symbols = wm.get_symbols()  # list[str], sorted, unique, uppercase
```

---

### 3.3 `realtime/session_guard.py` — `is_trading_hours()`

```python
def is_trading_hours(now: datetime | None = None) -> bool:
    """
    True nếu:
      - Thứ 2 → Thứ 6 (weekday 0–4)
      - 07:00 ≤ now ≤ 15:10 (Asia/Ho_Chi_Minh)
    """
```

Dùng để kiểm tra trước khi khởi động subscriber trong `__main__`.

---

### 3.4 `realtime/subscriber.py` — `MQTTSubscriber`

Kết nối DNSE MDDS, nhận OHLC candle, push vào Redis Streams.

**MQTT connection:**
```
Broker:    datafeed-lts-krx.dnse.com.vn:443
Protocol:  MQTT v5 over WebSocket Secure
Path:      /wss
SSL:       tls_insecure_set(True)  # self-signed cert
Username:  investorId (str)
Password:  JWT token
ClientID:  dnse-ohlc-sub-{uuid4()[:8]}
Keepalive: 1200s (20 phút)
```

**Topics subscribe (2 timeframes × N symbols):**
```
plaintext/quotes/krx/mdds/v2/ohlc/stock/1/{symbol}   # nến 1 phút
plaintext/quotes/krx/mdds/v2/ohlc/stock/5/{symbol}   # nến 5 phút
```

**Message → Redis:**
```python
redis.xadd(
    "stream:ohlc:1m",   # hoặc stream:ohlc:5m
    {
        "symbol":      "HPG",
        "time":        "2026-03-28T09:01:00+07:00",
        "open":        "25000",      # VND nguyên, stringified
        "high":        "25500",
        "low":         "24800",
        "close":       "25200",
        "volume":      "150000",
        "resolution":  "1",
        "received_at": "<unix_ms>",  # latency monitoring
    },
    maxlen=500_000,   # ~48h data
)
```

**Reconnect backoff:** 1s → 5s → 30s → 300s

**JWT auto-refresh:** Thread riêng, chạy mỗi 7h, reconnect MQTT sau khi lấy token mới.

---

### 3.5 `realtime/processor.py` — `StreamProcessor`

Đọc Redis Streams, validate, transform, upsert vào `price_intraday`.

**Consumer group:**
```
Group:    ohlc-processors
Consumer: worker-{hostname}-{pid}   # unique per worker
Streams:  stream:ohlc:1m, stream:ohlc:5m
Batch:    100 messages
Block:    5000ms
```

**Xử lý một batch:**
1. `XREADGROUP ... COUNT 100 BLOCK 5000` → nhận tối đa 100 messages
2. `_validate_message()` — kiểm tra required fields + resolution hợp lệ (1 hoặc 5)
3. `_transform_message()` — cast string → int/datetime, thêm `source="dnse_mdds"`
4. `PostgresLoader.load()` → upsert `price_intraday`
5. `XACK` → chỉ ACK sau khi upsert thành công (nếu DB lỗi → không ACK → retry)

**Pending messages (crash recovery):**
- Messages không ACK sau 30 phút → `XAUTOCLAIM` → worker hiện tại claim lại và retry

**Pure functions (testable):**
```python
_validate_message(msg: dict) -> bool
_transform_message(msg: dict) -> dict  # Input: all strings; Output: DB row dict
```

---

## 4. Schema bảng `price_intraday`

```sql
CREATE TABLE price_intraday (
    symbol      VARCHAR(10)   NOT NULL REFERENCES companies(symbol),
    time        TIMESTAMPTZ   NOT NULL,   -- Thời điểm bắt đầu nến (Asia/Ho_Chi_Minh)
    resolution  SMALLINT      NOT NULL,   -- 1 = nến 1 phút, 5 = nến 5 phút
    open        INTEGER       NOT NULL,   -- VND nguyên
    high        INTEGER       NOT NULL,
    low         INTEGER       NOT NULL,
    close       INTEGER       NOT NULL,
    volume      BIGINT,
    source      VARCHAR(20)   DEFAULT 'dnse_mdds',
    fetched_at  TIMESTAMPTZ   DEFAULT NOW(),

    PRIMARY KEY (time, symbol, resolution)
);
```

**Indexes:**
```sql
idx_pi_sym_res_time  ON price_intraday(symbol, resolution, time DESC)
idx_pi_time          ON price_intraday(time DESC)
```

**TimescaleDB hypertable:**
- Partition by `time`, chunk interval 1 tuần
- Retention: 180 ngày (tự động xóa data cũ)
- Compression: sau 7 ngày (lossless, columnar)

**Lưu ý thiết kế:**
- `time` lưu `TIMESTAMPTZ` — luôn insert với timezone `Asia/Ho_Chi_Minh`
- Giá là `INTEGER` VND nguyên (DNSE MDDS trả về VND nguyên — khác KBS REST trả về nghìn VND)
- Tách hoàn toàn khỏi `price_history` (EOD)

---

## 5. Tích hợp với `python main.py schedule`

Từ 2026-03-28, real-time pipeline được tích hợp hoàn toàn vào `python main.py schedule`. Không cần chạy tay nữa.

```
python main.py schedule
       │
       ├─ [Boot ngay] StreamProcessor khởi động (daemon thread, 24/7)
       │   └─ Liên tục đọc Redis → upsert price_intraday
       │
       ├─ [07:00 T2–T6] APScheduler → _start_realtime_subscriber()
       │   └─ MQTTSubscriber chạy trong thread riêng
       │      → Kết nối MQTT, subscribe VN30 × 2 timeframes
       │
       └─ [15:15 T2–T6] APScheduler → _stop_realtime_subscriber()
           └─ Ngắt kết nối MQTT, subscriber dừng
```

**Feature flag:** Set `REALTIME_ENABLED=false` trong `.env` để tắt hoàn toàn realtime pipeline (ví dụ: môi trường dev không có DNSE credentials).

---

## 6. Cách chạy

### Tích hợp (khuyến nghị)
```bash
python main.py schedule   # Batch + realtime pipeline cùng lúc
```

### Standalone (debug / test)
```bash
# Terminal 1
python -m realtime.processor

# Terminal 2 (chỉ active trong giờ giao dịch nếu dùng __main__)
python -m realtime.subscriber

# Windows batch scripts
run_realtime_processor.bat
run_realtime_subscriber.bat
```

### Docker Compose
```bash
docker compose up -d                    # Toàn bộ stack
docker compose up -d realtime-subscriber realtime-processor  # Chỉ realtime
docker compose logs -f realtime-subscriber
docker compose logs -f realtime-processor
```

---

## 7. Config `.env`

```env
# DNSE credentials (bắt buộc cho realtime)
DNSE_USERNAME=your_email@example.com
DNSE_PASSWORD=your_password

# Redis
REDIS_HOST=localhost          # Hoặc "redis" trong Docker
REDIS_PORT=6379

# Realtime settings
REALTIME_ENABLED=true         # false = tắt hoàn toàn
REALTIME_WATCHLIST=           # Để trống = VN30 từ DB; hoặc "HPG,VCB,FPT"
REALTIME_RESOLUTIONS=1,5      # Timeframes: 1m và 5m

# Cron schedule (optional override)
CRON_REALTIME_START=0 7 * * 1-5    # Khởi động subscriber T2–T6 07:00
CRON_REALTIME_STOP=15 15 * * 1-5   # Dừng subscriber T2–T6 15:15
```

---

## 8. Docker Compose — Các services liên quan

```yaml
redis:
  image: redis:7-alpine
  restart: always
  ports:
    - "6379:6379"
  volumes:
    - redis_data:/data
  command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]

realtime-subscriber:
  build: .
  restart: always
  command: python -m realtime.subscriber
  environment:
    - DNSE_USERNAME=${DNSE_USERNAME}
    - DNSE_PASSWORD=${DNSE_PASSWORD}
    - REDIS_HOST=redis
    - REALTIME_WATCHLIST=${REALTIME_WATCHLIST}
    - REALTIME_RESOLUTIONS=${REALTIME_RESOLUTIONS}
  depends_on:
    redis:     { condition: service_healthy }
    postgres:  { condition: service_healthy }

realtime-processor:
  build: .
  restart: always
  command: python -m realtime.processor
  environment:
    - REDIS_HOST=redis
  depends_on:
    redis:     { condition: service_healthy }
    postgres:  { condition: service_healthy }
  deploy:
    replicas: 1   # Tăng lên 2-3 khi cần scale
```

**Lưu ý Redis config:**
- `--appendonly yes`: Persist messages xuống disk — không mất data khi restart
- `--maxmemory 512mb`: Đủ cho ~50 symbols × 2 timeframes × 6h giao dịch (~100MB thực tế)
- `--maxmemory-policy allkeys-lru`: Khi đầy → xóa message cũ nhất

---

## 9. Error Handling & Reliability

### Subscriber

| Tình huống | Xử lý |
|---|---|
| Mất kết nối MQTT | `on_disconnect` → backoff reconnect (1s→5s→30s→300s) |
| JWT hết hạn | Thread riêng refresh mỗi 7h, reconnect MQTT với token mới |
| Redis không kết nối | Retry với backoff, log error — không crash process |
| DNSE broker down | Retry không giới hạn, log cảnh báo |
| Message JSON lỗi | Log warning, bỏ qua — không crash |

### Processor

| Tình huống | Xử lý |
|---|---|
| PostgreSQL down | Retry upsert với backoff — **không ACK** Redis → messages pending |
| Message thiếu field | Bỏ qua (log warning), ACK để xóa |
| Processor crash | Messages pending trong Redis, worker mới claim lại qua `XAUTOCLAIM` |
| Duplicate message | `ON CONFLICT DO UPDATE` — idempotent, an toàn |

---

## 10. Monitoring

### Kiểm tra Redis Stream

```bash
# Số messages đang chờ xử lý
docker exec stockapp_redis redis-cli XLEN stream:ohlc:1m
docker exec stockapp_redis redis-cli XLEN stream:ohlc:5m

# Xem messages gần nhất
docker exec stockapp_redis redis-cli XRANGE stream:ohlc:1m - + COUNT 5

# Pending messages (chưa được ACK)
docker exec stockapp_redis redis-cli XPENDING stream:ohlc:1m ohlc-processors - + 10
```

### Kiểm tra data trong DB

```sql
-- Số nến theo ngày và timeframe
SELECT DATE(time AT TIME ZONE 'Asia/Ho_Chi_Minh') AS date,
       resolution,
       COUNT(*) AS candles,
       COUNT(DISTINCT symbol) AS symbols
FROM price_intraday
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Nến mới nhất của HPG
SELECT time AT TIME ZONE 'Asia/Ho_Chi_Minh' AS time_ict,
       resolution, open, high, low, close, volume
FROM price_intraday
WHERE symbol = 'HPG'
ORDER BY time DESC
LIMIT 10;

-- Latency: thời gian từ khi nến kết thúc đến khi vào DB
SELECT symbol, resolution,
       EXTRACT(EPOCH FROM (fetched_at - time)) AS lag_seconds
FROM price_intraday
WHERE time > NOW() - INTERVAL '1 hour'
ORDER BY lag_seconds DESC
LIMIT 10;
```

### Ngưỡng cảnh báo

| Metric | Cách đo | Ngưỡng |
|---|---|---|
| Redis stream length | `XLEN stream:ohlc:1m` | > 100,000 |
| Pending messages | `XPENDING ...` | > 1,000 |
| Message latency | `fetched_at - time` | > 30s |
| MQTT disconnect | Log `on_disconnect` | > 2 lần/giờ |
| DB insert rate | COUNT trong 1 phút | < 10/phút (giờ giao dịch) |

---

## 11. Query cho Backend Java

```sql
-- Lấy nến 5m của HPG trong ngày hôm nay
SELECT time AT TIME ZONE 'Asia/Ho_Chi_Minh' AS time_ict,
       open, high, low, close, volume
FROM price_intraday
WHERE symbol = 'HPG'
  AND resolution = 5
  AND time >= CURRENT_DATE AT TIME ZONE 'Asia/Ho_Chi_Minh'
ORDER BY time ASC;

-- Lấy snapshot intraday mới nhất (tất cả VN30)
SELECT DISTINCT ON (symbol)
       symbol, time AT TIME ZONE 'Asia/Ho_Chi_Minh' AS last_time,
       close, volume
FROM price_intraday
WHERE resolution = 1
  AND time > NOW() - INTERVAL '30 minutes'
ORDER BY symbol, time DESC;

-- Ghép intraday với EOD (chart có historical + intraday hôm nay)
SELECT date::timestamptz AS time, close, volume, 'eod' AS type
FROM price_history
WHERE symbol = 'HPG' AND date >= CURRENT_DATE - 30
UNION ALL
SELECT time, close, volume, 'intraday' AS type
FROM price_intraday
WHERE symbol = 'HPG' AND resolution = 5 AND time >= CURRENT_DATE AT TIME ZONE 'Asia/Ho_Chi_Minh'
ORDER BY time ASC;
```

---

## 12. Continuous Aggregates (TimescaleDB)

Sau khi data vào `price_intraday`, TimescaleDB tự động tính toán:

| View | Từ | Dùng cho |
|---|---|---|
| `cagg_ohlc_5m` | `price_intraday` 1m | Nến 5m (tính từ 1m) |
| `cagg_ohlc_1h` | `cagg_ohlc_5m` | Nến 1h |
| `cagg_ohlc_1d` | `cagg_ohlc_1h` | Nến 1 ngày (từ intraday) |

Query trực tiếp từ continuous aggregates để tối ưu hiệu năng:
```sql
SELECT time_bucket('5 minutes', bucket) AS time, symbol,
       first(open, bucket) AS open,
       max(high) AS high,
       min(low) AS low,
       last(close, bucket) AS close,
       sum(volume) AS volume
FROM cagg_ohlc_5m
WHERE symbol = 'HPG'
  AND bucket >= NOW() - INTERVAL '1 day'
GROUP BY 1, 2
ORDER BY 1;
```

---

## 13. Câu hỏi thường gặp

**Q: Real-time pipeline có ảnh hưởng đến batch pipeline không?**
A: Không. Chạy trên daemon thread riêng, bảng DB riêng (`price_intraday`). Batch pipeline hoàn toàn độc lập.

**Q: Khi thị trường đóng cửa (15:15), subscriber làm gì?**
A: APScheduler gọi `_stop_realtime_subscriber()` → set `_running=False` + `client.disconnect()`. Processor tiếp tục chạy và drain hết messages còn lại trong Redis. Sáng T2–T6 07:00 subscriber tự khởi động lại.

**Q: Nếu chạy `python main.py schedule` sau 07:00 trong ngày giao dịch thì sao?**
A: Processor khởi động ngay. Subscriber sẽ đợi đến 07:00 ngày tiếp theo. Nếu cần subscribe ngay lập tức, chạy thêm `python -m realtime.subscriber` riêng.

**Q: Dữ liệu DNSE MDDS có delay không?**
A: Feed trực tiếp từ KRX — latency < 1s. Là nguồn data real-time chất lượng cao nhất hiện tại.

**Q: Cần bao nhiêu RAM cho Redis?**
A: 30 symbols × 2 timeframes × 375 nến/ngày × ~300 bytes/message ≈ 6.75 MB/ngày. `maxlen=500,000` ≈ ~100 MB. Config 512 MB là đủ dư dả.

**Q: Nếu DNSE MDDS ngừng dịch vụ?**
A: Subscriber reconnect vô hạn với backoff (max 5 phút/lần). Batch pipeline (`sync_prices` EOD) không bị ảnh hưởng. Intraday data gián đoạn cho đến khi kết nối lại.

**Q: Làm sao scale processor khi khối lượng tăng?**
A: Chạy thêm `python -m realtime.processor` hoặc tăng `replicas` trong Docker Compose. Redis consumer group tự phân phối messages giữa các workers.

---

## 14. Trạng thái

| Phase | Trạng thái | Hoàn thành |
|---|---|---|
| RT-1 — Nền tảng (Redis, DB, Auth, Watchlist) | ✅ Hoàn thành | 2026-03-21 |
| RT-2 — MQTT Subscriber | ✅ Hoàn thành | 2026-03-21 |
| RT-3 — Stream Processor | ✅ Hoàn thành | 2026-03-21 |
| RT-4 — Session Guard & Scheduler Integration | ✅ Hoàn thành | 2026-03-28 |
| RT-5 — Scale & Mở rộng (15m, 30m, 1H, full market) | 🔲 Tùy chọn | — |

**Verified:** End-to-end test ngày 2026-03-28 — Auth OK (investorId=1002161780), MQTT connect OK, inject test messages → processor upsert 5 rows vào `price_intraday` thành công.
