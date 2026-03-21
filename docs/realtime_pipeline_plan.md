# Kế hoạch nâng cấp Real-time Pipeline

> Cập nhật: 2026-03-21
> Trạng thái: Đang thiết kế — chưa implement
> Tác giả: Data Engineering Team

---

## 1. Bối cảnh và mục tiêu

### Hiện trạng

Pipeline hiện tại là **batch pipeline thuần túy**:

| Job | Lịch chạy | Dữ liệu |
|---|---|---|
| sync_listing | CN 01:00 | Danh mục mã, ngành ICB |
| sync_financials | 1 & 15 hàng tháng 03:00 | BCTC (balance sheet, income, cash flow, ratio) |
| sync_company | T2 02:00 | Cổ đông, ban lãnh đạo, công ty con, sự kiện |
| sync_ratios | Hàng ngày 18:30 | Ratio summary sau đóng cửa |
| sync_prices | T2–T6 19:00 | Giá OHLCV ngày (EOD) |

Dữ liệu giá chỉ có **1 nến/ngày**, không có intraday. Backend/Frontend không thể phục vụ các use case cần dữ liệu trong giờ giao dịch.

### Mục tiêu sau nâng cấp

1. **Lưu intraday OHLC** (nến 1 phút, 5 phút) vào PostgreSQL trong giờ giao dịch.
2. **Dữ liệu sẵn sàng real-time** cho Java SpringBoot Backend API → React Frontend dashboard.
3. **Scalable**: pipeline có thể mở rộng số symbol và timeframe mà không cần redesign.
4. **Batch pipeline không bị ảnh hưởng**: Các jobs hiện tại tiếp tục chạy bình thường.

### Scope rõ ràng

```
Pipeline (Python)         Backend (Java)         Frontend (React)
─────────────────         ──────────────         ────────────────
Thu thập dữ liệu          REST API               Dashboard
Xử lý / Transform         Query PostgreSQL        Charts
Lưu vào PostgreSQL        Serve data             Alerts / UI
```

Pipeline **không** build dashboard, **không** gửi alert trực tiếp đến user — đó là trách nhiệm của Backend/Frontend.

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
         │ Auth: JWT + investorId
         ▼
┌─────────────────────────────────┐
│        MQTT Subscriber           │   realtime/subscriber.py
│                                  │   • 1 process duy nhất
│  • Auth flow + JWT auto-refresh  │   • Subscribe OHLC 1m & 5m
│  • Subscribe watchlist symbols   │   • Reconnect tự động khi mất kết nối
│  • Deserialize JSON payload      │   • Chỉ chạy trong giờ giao dịch
└────────────────┬────────────────┘
                 │ XADD (Redis Streams)
                 │ stream:ohlc:1m
                 │ stream:ohlc:5m
                 ▼
┌─────────────────────────────────┐
│          Redis Streams           │   Infrastructure mới
│                                  │   • Retention: 48h
│  stream:ohlc:1m                  │   • Consumer groups
│  stream:ohlc:5m                  │   • Pending messages list
└────────────────┬────────────────┘
                 │ XREADGROUP (Consumer Group)
                 │ Batch đọc mỗi 5 giây
                 ▼
┌─────────────────────────────────┐
│       Stream Processor           │   realtime/processor.py
│                                  │   • 1-N worker processes
│  • Validate & transform          │   • Scale ngang độc lập
│  • Deduplicate                   │   • ACK sau khi upsert thành công
│  • Batch upsert PostgreSQL       │
└────────────────┬────────────────┘
                 │ Upsert (INSERT ... ON CONFLICT DO UPDATE)
                 ▼
┌─────────────────────────────────┐
│          PostgreSQL              │   DB hiện tại (stockapp)
│                                  │
│  price_intraday (bảng mới)      │   ← Java SpringBoot đọc
│  price_history  (batch EOD)     │   ← Giữ nguyên
└─────────────────────────────────┘
```

### Tại sao Redis Streams?

| Tiêu chí | In-process Queue | Redis Streams (chọn) |
|---|---|---|
| Bền vững khi crash | ❌ Mất hết | ✅ Persist trên disk |
| Scale workers | ❌ Không | ✅ Consumer groups |
| Monitor lag | ❌ Không | ✅ XPENDING, XLEN |
| Replay messages | ❌ Không | ✅ Đọc lại từ ID bất kỳ |
| Cần thêm service | Không | Redis (lightweight) |

---

## 3. Các thành phần mới

### 3.1 MQTT Subscriber (`realtime/subscriber.py`)

**Trách nhiệm duy nhất:** Kết nối DNSE MDDS → nhận OHLC messages → push vào Redis Streams.

**Auth flow (2 bước):**
```
POST https://api.dnse.com.vn/user-service/api/auth
  body: { username, password }
  → { token: "<JWT>" }           # Hết hạn sau 8h

GET https://api.dnse.com.vn/user-service/api/me
  header: Authorization: Bearer <token>
  → { investorId: 123456, ... }  # Dùng làm MQTT username
```

**MQTT connection:**
```
Broker:    datafeed-lts-krx.dnse.com.vn:443
Protocol:  MQTT v5 over WebSocket Secure
Path:      /wss
SSL:       tls_insecure_set(True)  # self-signed cert
Username:  investorId (số nguyên)
Password:  JWT token
ClientID:  uuid4()  # unique, tránh conflict
Keepalive: 1200s (20 phút)
```

**Topics subscribe (2 timeframes × N symbols):**
```
plaintext/quotes/krx/mdds/v2/ohlc/stock/1/{symbol}   # nến 1 phút
plaintext/quotes/krx/mdds/v2/ohlc/stock/5/{symbol}   # nến 5 phút
```

**JWT auto-refresh:**
- Token hết hạn sau 8h — subscriber phải tự refresh
- Lịch refresh: mỗi 7h (buffer 1h)
- Sau khi lấy token mới: cập nhật MQTT credentials + reconnect

**Xử lý reconnect:**
- `on_disconnect` callback: log + trigger reconnect với backoff (1s, 5s, 30s, 5m)
- Sau reconnect: re-subscribe tất cả topics

**Push vào Redis:**
```python
redis.xadd(
    f"stream:ohlc:{resolution}m",   # stream:ohlc:1m hoặc stream:ohlc:5m
    {
        "symbol":     "HPG",
        "time":       "2026-03-21T09:01:00+07:00",
        "open":       20780,          # VND nguyên
        "high":       20900,
        "low":        20750,
        "close":      20850,
        "volume":     1234567,
        "resolution": "1",
        "received_at": "<unix_ms>",  # để monitor latency
    },
    maxlen=500000,   # giới hạn kích thước stream (~48h data)
)
```

---

### 3.2 Stream Processor (`realtime/processor.py`)

**Trách nhiệm:** Đọc từ Redis Streams → validate/transform → batch upsert PostgreSQL.

**Consumer group pattern:**
```
Group name:   ohlc-processors
Consumer:     worker-{hostname}-{pid}   # unique per worker
Read count:   100 messages mỗi lần
Block timeout: 5000ms (5s)
```

**Xử lý một batch:**
1. `XREADGROUP GROUP ohlc-processors worker-X COUNT 100 BLOCK 5000 STREAMS stream:ohlc:1m >`
2. Validate: kiểm tra required fields, kiểu dữ liệu
3. Deduplicate: theo `(symbol, time, resolution)` trước khi upsert
4. Batch upsert vào `price_intraday`
5. `XACK stream:ohlc:1m ohlc-processors <message_ids>` sau khi upsert thành công

**Pending messages (không bị mất khi crash):**
- Khi worker crash giữa chừng: messages ở trạng thái "pending" trong Redis
- Worker mới khởi động: claim pending messages cũ qua `XAUTOCLAIM`

**Scale:** Chạy thêm worker process là đủ — Redis phân phối tự động qua consumer group.

---

### 3.3 JWT Token Manager (`realtime/auth.py`)

Module riêng xử lý auth flow, tách khỏi MQTT logic:

```python
class DNSEAuthManager:
    def get_token(self) -> str       # Lấy/refresh JWT
    def get_investor_id(self) -> str # Lấy investorId
    def is_token_valid(self) -> bool # Còn hơn 1h mới hết hạn?
```

---

### 3.4 Watchlist Manager (`realtime/watchlist.py`)

Quản lý danh sách symbol cần subscribe. Mặc định: VN30 + symbols tuỳ chỉnh.

**Nguồn watchlist (ưu tiên giảm dần):**
1. Environment variable `REALTIME_WATCHLIST=HPG,VCB,FPT,...`
2. Query DB: `SELECT symbol FROM companies WHERE index_membership = 'VN30'`
3. Fallback hardcode: 30 mã VN30 hiện tại

**Dynamic reload:** Hỗ trợ reload watchlist không cần restart subscriber (SIGHUP).

---

### 3.5 Session Guard (`realtime/session_guard.py`)

Subscriber chỉ cần hoạt động trong giờ giao dịch. Session guard quản lý vòng đời:

```
07:00  → Khởi động subscriber, kết nối MQTT
08:45  → Subscribe topics (trước ATO 15 phút)
09:00  → ATO bắt đầu, nhận data
11:30  → Nghỉ trưa HNX (optional: unsubscribe bớt nếu cần)
13:00  → Tiếp tục
14:45  → ATC
15:05  → Unsubscribe topics
15:10  → Đóng MQTT connection
```

Subscriber **không chạy 24/7** — chỉ active trong giờ giao dịch T2–T6.
Ngoài giờ: process idle hoặc tắt hẳn (cron start/stop).

---

## 4. Data Model — Bảng mới

### 4.1 `price_intraday`

```sql
CREATE TABLE IF NOT EXISTS price_intraday (
    id          BIGSERIAL    PRIMARY KEY,
    symbol      VARCHAR(10)  NOT NULL
                CONSTRAINT fk_pi_symbol REFERENCES companies(symbol),
    time        TIMESTAMPTZ  NOT NULL,              -- Thời điểm bắt đầu nến (có timezone)
    resolution  SMALLINT     NOT NULL,              -- Timeframe: 1 hoặc 5 (phút)
    open        INTEGER      NOT NULL,              -- VND nguyên
    high        INTEGER      NOT NULL,
    low         INTEGER      NOT NULL,
    close       INTEGER      NOT NULL,
    volume      BIGINT,
    source      VARCHAR(20)  DEFAULT 'dnse_mdds',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT uq_price_intraday UNIQUE (symbol, time, resolution)
);

-- Index cho query pattern phổ biến nhất: symbol + resolution + time range
CREATE INDEX idx_pi_sym_res_time
    ON price_intraday(symbol, resolution, time DESC);

-- Partial index cho query intraday hôm nay
CREATE INDEX idx_pi_today
    ON price_intraday(symbol, resolution, time DESC)
    WHERE time >= CURRENT_DATE;
```

**Lưu ý thiết kế:**
- `time` lưu `TIMESTAMPTZ` (có timezone) — luôn dùng `Asia/Ho_Chi_Minh` khi insert
- `resolution` là số nguyên (1, 5) thay vì string cho dễ sort/filter
- Tách hoàn toàn khỏi `price_history` (EOD) để không ảnh hưởng batch pipeline
- Giá lưu dưới dạng `INTEGER` VND nguyên (DNSE MDDS trả về VND nguyên — khác KBS REST trả về nghìn VND)

### 4.2 Retention policy

| Bảng | Giữ bao lâu | Lý do |
|---|---|---|
| `price_intraday` (1m) | 30 ngày | Data lớn, ít dùng sau 1 tháng |
| `price_intraday` (5m) | 180 ngày | Vừa đủ cho phân tích kỹ thuật |
| `price_history` (EOD) | Vĩnh viễn | Không đổi |

Cleanup job chạy hàng tuần:
```sql
DELETE FROM price_intraday
WHERE resolution = 1 AND time < NOW() - INTERVAL '30 days';

DELETE FROM price_intraday
WHERE resolution = 5 AND time < NOW() - INTERVAL '180 days';
```

### 4.3 Migration file

```
db/migrations/007_price_intraday.sql   ← tạo bảng + indexes
```

---

## 5. Tích hợp với pipeline hiện tại

### Batch pipeline — không thay đổi

```
sync_listing     (CN 01:00)    → companies, icb_industries
sync_financials  (1&15 03:00)  → balance_sheets, income_statements, cash_flows, financial_ratios
sync_company     (T2 02:00)    → shareholders, officers, subsidiaries, corporate_events
sync_ratios      (hàng ngày 18:30) → ratio_summary
sync_prices      (T2–T6 19:00) → price_history (EOD, 1 nến/ngày)
```

### Real-time pipeline — chạy song song

```
realtime/subscriber.py  → chạy độc lập (process riêng, không phải APScheduler)
realtime/processor.py   → chạy độc lập (1-N processes)
```

**Không có xung đột dữ liệu:** `price_history` (EOD) và `price_intraday` (intraday) là 2 bảng tách biệt hoàn toàn.

### Quan hệ giữa EOD và Intraday

Nến EOD (từ `sync_prices`) và nến intraday (từ real-time) **độc lập nhau**:
- EOD lấy từ KBS REST sau 19:00 — giá chính thức sau đóng cửa
- Intraday từ DNSE MDDS live — giá real-time trong ngày
- Backend có thể merge 2 nguồn khi cần (e.g., historical chart + intraday overlay)

---

## 6. Cấu trúc thư mục mới

```
data-pipeline/
├── realtime/                       ← Module mới hoàn toàn
│   ├── __init__.py
│   ├── auth.py                     # DNSEAuthManager — JWT flow
│   ├── subscriber.py               # MQTT subscriber → Redis XADD
│   ├── processor.py                # Redis XREADGROUP → PostgreSQL upsert
│   ├── watchlist.py                # Quản lý danh sách symbol
│   └── session_guard.py            # Kiểm soát giờ giao dịch
│
├── db/migrations/
│   └── 007_price_intraday.sql      ← Migration mới
│
├── config/
│   ├── settings.py                 ← Thêm redis_url, realtime_watchlist
│   └── constants.py                ← Thêm CONFLICT_KEYS["price_intraday"]
│
└── docker-compose.yml              ← Thêm redis service
```

---

## 7. Config mới (settings.py & .env)

```python
# config/settings.py — thêm vào BaseSettings
redis_url: str = "redis://localhost:6379/0"
realtime_watchlist: str = ""        # CSV: "HPG,VCB,FPT" — rỗng = dùng VN30 từ DB
realtime_resolutions: str = "1,5"  # Timeframes: "1,5" = 1m và 5m
```

```env
# .env
REDIS_URL=redis://redis:6379/0
REALTIME_WATCHLIST=                 # Để trống = VN30 từ DB
REALTIME_RESOLUTIONS=1,5
```

---

## 8. Docker Compose — thay đổi

```yaml
# docker-compose.yml — thêm services

services:
  # --- Existing ---
  postgres:
    image: postgres:16-alpine
    # ... (không đổi)

  pipeline:
    build: .
    command: python main.py schedule
    # ... (không đổi)

  # --- New ---
  redis:
    image: redis:7-alpine
    restart: always
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru

  realtime-subscriber:
    build: .
    restart: always
    command: python -m realtime.subscriber
    environment:
      - DNSE_USERNAME=${DNSE_USERNAME}
      - DNSE_PASSWORD=${DNSE_PASSWORD}
      - REDIS_URL=redis://redis:6379/0
      - REALTIME_WATCHLIST=${REALTIME_WATCHLIST}
      - REALTIME_RESOLUTIONS=${REALTIME_RESOLUTIONS}
    depends_on:
      - redis
      - postgres

  realtime-processor:
    build: .
    restart: always
    command: python -m realtime.processor
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis
      - postgres
    deploy:
      replicas: 1          # Tăng lên 2-3 khi cần scale

volumes:
  redis_data:
```

**Redis config giải thích:**
- `--appendonly yes`: Persist Redis data xuống disk — tránh mất messages khi restart
- `--maxmemory 512mb`: Giới hạn RAM — đủ cho ~50 symbols × 2 timeframes × 6h giao dịch
- `--maxmemory-policy allkeys-lru`: Khi đầy RAM → xóa message cũ nhất

---

## 9. Dependencies mới

```
paho-mqtt>=2.0     # MQTT client (DNSE đã dùng, đã có)
redis>=5.0         # Redis Python client + Streams support
```

---

## 10. Error Handling & Reliability

### 10.1 Subscriber

| Tình huống | Xử lý |
|---|---|
| Mất kết nối MQTT | `on_disconnect` → backoff reconnect (1s→5s→30s→5m) |
| JWT hết hạn | Refresh tự động sau 7h, reconnect MQTT với token mới |
| Redis không kết nối được | Retry với backoff, log error — **không crash** |
| DNSE broker down | Retry không giới hạn, log cảnh báo mỗi 5 phút |
| Message JSON lỗi | Log và bỏ qua — không crash toàn process |

### 10.2 Processor

| Tình huống | Xử lý |
|---|---|
| PostgreSQL down | Retry batch upsert với backoff — **không ACK** cho Redis |
| Message thiếu field | Bỏ qua message, log warning |
| Processor crash | Messages ở trạng thái "pending" — worker mới claim lại qua XAUTOCLAIM |
| Duplicate message | Upsert với `ON CONFLICT DO UPDATE` — safe |

### 10.3 Message không được xử lý (Dead Letter)

Nếu message pending quá 30 phút → claim lại tối đa 3 lần → nếu vẫn lỗi → log vào file `realtime_errors.log` và ACK để xóa khỏi pending list.

---

## 11. Monitoring

### Metrics cần theo dõi

| Metric | Cách đo | Ngưỡng cảnh báo |
|---|---|---|
| Redis stream length | `XLEN stream:ohlc:1m` | > 100,000 messages |
| Pending messages | `XPENDING stream:ohlc:1m ohlc-processors` | > 1,000 pending |
| Message latency | `received_at - time` | > 30s |
| MQTT connection status | Log on_connect/on_disconnect | Disconnect > 2 lần/giờ |
| DB insert rate | Count records mỗi phút | < 10 records/phút (giờ giao dịch) |

### Logging

```
logs/
├── realtime_subscriber.log   # MQTT connection, subscribe events
├── realtime_processor.log    # Batch upsert, error messages
└── realtime_errors.log       # Dead letter messages
```

---

## 12. Lộ trình implement

### Phase RT-1 — Nền tảng (tuần 1)

**Mục tiêu:** Redis + DB schema + auth module hoạt động.

- [ ] Thêm Redis vào `docker-compose.yml`
- [ ] Tạo `db/migrations/007_price_intraday.sql` và chạy migration
- [ ] Thêm `redis_url`, `realtime_watchlist` vào `config/settings.py`
- [ ] Viết `realtime/auth.py` — JWT flow + investorId
- [ ] Viết `realtime/watchlist.py` — load từ env/DB

**Kiểm tra:** Auth flow trả về token và investorId hợp lệ.

---

### Phase RT-2 — MQTT Subscriber (tuần 2)

**Mục tiêu:** Subscribe OHLC và push vào Redis Streams.

- [ ] Viết `realtime/subscriber.py` — MQTT connect + subscribe + XADD
- [ ] Test với 5 symbol (HPG, VCB, FPT, VNM, MWG)
- [ ] Verify data trong Redis: `XLEN stream:ohlc:1m`, `XRANGE stream:ohlc:1m - +`
- [ ] Implement JWT auto-refresh (timer mỗi 7h)
- [ ] Implement reconnect với backoff

**Kiểm tra:** 5 symbols × 2 timeframes push đủ messages vào Redis trong 1h test.

---

### Phase RT-3 — Stream Processor (tuần 3)

**Mục tiêu:** Đọc Redis → upsert PostgreSQL.

- [ ] Viết `realtime/processor.py` — XREADGROUP + validate + upsert
- [ ] Tạo consumer group: `XGROUP CREATE stream:ohlc:1m ohlc-processors $ MKSTREAM`
- [ ] Implement XAUTOCLAIM cho pending messages
- [ ] Test end-to-end: MQTT → Redis → PostgreSQL
- [ ] Verify data trong `price_intraday` table

**Kiểm tra:** Dữ liệu nến 1m và 5m xuất hiện trong DB với lag < 30s so với thị trường.

---

### Phase RT-4 — Session Guard & Production (tuần 4)

**Mục tiêu:** Vận hành production-ready.

- [ ] Viết `realtime/session_guard.py` — chỉ active trong giờ giao dịch
- [ ] Thêm Docker services `realtime-subscriber` và `realtime-processor`
- [ ] Thêm monitoring metrics (log Redis lag, pending count)
- [ ] Implement retention cleanup job
- [ ] Test full watchlist (~50 symbols) trong 1 ngày giao dịch
- [ ] Document API schema cho Backend team

**Kiểm tra:** 50 symbols × 2 timeframes chạy ổn định 1 tuần không crash, data đầy đủ.

---

### Phase RT-5 — Scale & Mở rộng (tùy chọn)

Sau khi RT-1 đến RT-4 ổn định:

- [ ] Thêm timeframe 15m, 30m, 1H nếu cần
- [ ] Mở rộng watchlist ra toàn thị trường (cần đánh giá Redis memory)
- [ ] Thêm index data (VNINDEX, VN30) vào separate stream
- [ ] Horizontal scale processor (replicas: 2-3)

---

## 13. Câu hỏi thường gặp

**Q: Real-time pipeline có ảnh hưởng đến batch pipeline không?**
A: Không. Chạy trên process riêng, bảng DB riêng (`price_intraday`). Batch pipeline giữ nguyên.

**Q: Khi thị trường đóng cửa, subscriber làm gì?**
A: Session guard tắt MQTT connection sau 15:05. Processor tiếp tục drain Redis cho đến khi hết messages. Restart vào sáng hôm sau.

**Q: Dữ liệu DNSE MDDS có delay không?**
A: Feed trực tiếp từ KRX — latency rất thấp (< 1s). Là nguồn data real-time chất lượng cao nhất hiện tại.

**Q: Cần bao nhiêu RAM cho Redis?**
A: 50 symbols × 2 timeframes × 375 nến/ngày (6h × 60m + 6h × 12 nến 5m) × ~200 bytes/message ≈ 7.5 MB/ngày. Với maxlen 500,000 messages ≈ 100 MB. 512 MB là đủ dư dả.

**Q: Backend Java đọc dữ liệu như thế nào?**
A: Đọc trực tiếp từ PostgreSQL bảng `price_intraday`. Query gợi ý:
```sql
SELECT time, open, high, low, close, volume
FROM price_intraday
WHERE symbol = 'HPG'
  AND resolution = 5
  AND time >= NOW() - INTERVAL '1 day'
ORDER BY time ASC;
```

**Q: Nếu DNSE MDDS ngừng dịch vụ thì sao?**
A: Subscriber sẽ reconnect vô hạn và log cảnh báo. Batch pipeline (sync_prices EOD) không bị ảnh hưởng. Intraday data sẽ bị gián đoạn cho đến khi kết nối lại.

---

## 14. Trạng thái tracking

| Phase | Trạng thái | Bắt đầu | Hoàn thành |
|---|---|---|---|
| RT-1 — Nền tảng (Redis, DB, Auth) | 🔲 Chưa bắt đầu | — | — |
| RT-2 — MQTT Subscriber | 🔲 Chưa bắt đầu | — | — |
| RT-3 — Stream Processor | 🔲 Chưa bắt đầu | — | — |
| RT-4 — Session Guard & Production | 🔲 Chưa bắt đầu | — | — |
| RT-5 — Scale & Mở rộng | 🔲 Tùy chọn | — | — |
