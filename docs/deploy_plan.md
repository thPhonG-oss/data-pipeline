# Kế hoạch Triển khai — Data Pipeline Chứng khoán Việt Nam

> **Phiên bản:** Phase 7 (TimescaleDB + Redis + Realtime Pipeline) | **Cập nhật:** 2026-03-28
> Tài liệu này mô tả toàn bộ quy trình triển khai pipeline lên môi trường sản xuất (VPS).
> Mục tiêu: pipeline tự chạy liên tục, dữ liệu luôn mới, có alert khi sự cố, realtime trong giờ giao dịch.

---

## Mục lục

1. [Kiến trúc tổng thể](#1-kiến-trúc-tổng-thể)
2. [Yêu cầu hệ thống](#2-yêu-cầu-hệ-thống)
3. [Chuẩn bị trước khi triển khai](#3-chuẩn-bị-trước-khi-triển-khai)
4. [Triển khai lên VPS](#4-triển-khai-lên-vps)
5. [Đồng bộ dữ liệu ban đầu](#5-đồng-bộ-dữ-liệu-ban-đầu)
6. [Kết nối Spring Boot Backend](#6-kết-nối-spring-boot-backend)
7. [Kiểm tra sau triển khai](#7-kiểm-tra-sau-triển-khai)
8. [Vận hành thường ngày](#8-vận-hành-thường-ngày)
9. [Cập nhật code (CI/CD thủ công)](#9-cập-nhật-code-cicd-thủ-công)
10. [Xử lý sự cố](#10-xử-lý-sự-cố)
11. [Rollback](#11-rollback)
12. [Bảo mật](#12-bảo-mật)
13. [Checklist triển khai](#13-checklist-triển-khai)

---

## 1. Kiến trúc tổng thể

```
                     VPS (Ubuntu 22.04 / 4 GB RAM)
┌──────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  Docker Compose (5 services)                                             │
│                                                                          │
│  ┌──────────────────────┐   ┌──────────────────────────────────────────┐ │
│  │  stockapp_pipeline   │   │  stockapp_db                             │ │
│  │  (python:3.12-slim)  │──►│  (timescale/timescaledb:latest-pg16)     │ │
│  │                      │   │                                          │ │
│  │  APScheduler 8 jobs: │   │  Database: stockapp (TimescaleDB)        │ │
│  │  ├── sync_listing    │   │  Hypertables: price_history,             │ │
│  │  ├── sync_financials │   │              price_intraday              │ │
│  │  ├── sync_company    │   │  Cagg: cagg_ohlc_5m/1h/1d               │ │
│  │  ├── sync_ratios     │   │  Port: 5432 (expose)                    │ │
│  │  ├── sync_prices     │   │  Volume: postgres_data                   │ │
│  │  ├── alert_check     │   └──────────────────────────────────────────┘ │
│  │  ├── rt_start(07:00) │              ▲                                 │
│  │  └── rt_stop (15:15) │              │                                 │
│  └──────────────────────┘              │                                 │
│           │                           │                                 │
│           │       ┌───────────────────┴─────────────────────────────┐   │
│           │       │  stockapp_redis                                  │   │
│           │       │  (redis:7-alpine)                                │   │
│           │       │  Redis Streams: ohlc:1m, ohlc:5m                │   │
│           │       │  Port: 6379 | maxmemory: 512mb                  │   │
│           │       └───────────────────┬─────────────────────────────┘   │
│           │                           │                                 │
│  ┌────────┴──────────────┐  ┌─────────┴────────────────────────────────┐ │
│  │  stockapp_rt_subscrib │  │  stockapp_rt_processor                   │ │
│  │  (python:3.12-slim)   │  │  (python:3.12-slim)                      │ │
│  │                       │  │                                          │ │
│  │  MQTTSubscriber       │  │  StreamProcessor                         │ │
│  │  DNSE MDDS → MQTT v5  │  │  Redis XREADGROUP → TimescaleDB upsert  │ │
│  │  WebSocket Secure     │  │  Batch 100 msg / 5s block                │ │
│  │  JWT auto-refresh 7h  │  │  XAUTOCLAIM crash recovery               │ │
│  └───────────────────────┘  └──────────────────────────────────────────┘ │
│                                                                          │
│  Volume: ./logs ──► /app/logs (log accessible từ host)                   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
         │ Port 5432
         ▼
Spring Boot Backend (cùng VPS hoặc server riêng)
kết nối user webapp_readonly — HikariCP pool
```

**Điểm quan trọng:**
- **5 services:** `postgres` (TimescaleDB), `redis`, `pipeline` (APScheduler), `realtime-subscriber` (MQTT), `realtime-processor` (Stream).
- **TimescaleDB** thay thế plain PostgreSQL — cần image `timescale/timescaledb:latest-pg16` (tương thích 100% PostgreSQL, thêm tính năng timeseries).
- **Redis Streams** làm buffer giữa subscriber và processor — dữ liệu không mất khi processor restart.
- **Realtime pipeline** tự động start lúc 07:00 và stop lúc 15:15 (Mon–Fri) qua APScheduler.
- **Spring Boot** kết nối qua user `webapp_readonly` — chỉ có quyền SELECT.
- `restart: unless-stopped` — tất cả services tự khởi động lại sau VPS reboot.

---

## 2. Yêu cầu hệ thống

### 2.1 Thông số VPS tối thiểu

| Thành phần | Tối thiểu | Khuyến nghị |
|---|---|---|
| CPU | 2 vCPU | 2–4 vCPU |
| RAM | 3 GB | 4 GB |
| Ổ cứng | 40 GB SSD | 60 GB SSD |
| Băng thông | 100 Mbps | 200 Mbps |
| HĐH | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

> **Tại sao 4 GB RAM?**
> - TimescaleDB: ~512 MB–1 GB (shared_buffers + work_mem)
> - Redis: ~256–512 MB (maxmemory 512mb)
> - Pipeline (5 luồng): ~256 MB
> - Realtime subscriber + processor: ~256 MB
> - OS + buffer: ~512 MB
> - Tổng: ~2.5–3.5 GB → 4 GB là ngưỡng thoải mái.
> VPS 4 GB RAM ở DigitalOcean/Vultr giá khoảng $24/tháng (~600,000 VND).

> **Tại sao 40 GB SSD?**
> - `price_history` (5 năm × 1,550 mã): ~500 MB sau compression
> - `price_intraday` (1m candles × giờ giao dịch): ~5 GB/năm
> - TimescaleDB compression tự động giảm ~90% với dữ liệu cũ
> - Log files: ~100–200 MB/năm

### 2.2 Phần mềm cần cài trên VPS

| Phần mềm | Phiên bản | Ghi chú |
|---|---|---|
| Docker Engine | ≥ 24.x | Không dùng Docker Desktop |
| Docker Compose plugin | ≥ 2.x | `docker compose` (không phải `docker-compose`) |
| Git | ≥ 2.x | Để clone và pull code |

### 2.3 Tài khoản và thông tin cần chuẩn bị

- [ ] Tài khoản VPS (DigitalOcean, Vultr, Linode, VPS Việt Nam)
- [ ] SSH key để đăng nhập VPS
- [ ] Tài khoản DNSE (Entrade) — username + password (cho `sync_prices` và realtime)
- [ ] Telegram Bot Token + Chat ID (cho alert)
- [ ] `VNSTOCK_API_KEY` (không bắt buộc — chỉ cần nếu dùng vnstock sponsor packages)

---

## 3. Chuẩn bị trước khi triển khai

### 3.1 Tạo file `.env` từ template

```bash
cp .env.example .env
```

Mở `.env` và điền đầy đủ:

```env
# ── Database ──────────────────────────────────────────────────────────────────
DB_HOST=localhost         # Docker sẽ override thành "postgres" tự động
DB_PORT=5432
DB_NAME=stockapp
DB_USER=postgres
DB_PASSWORD=<đặt_password_mạnh_ít_nhất_16_ký_tự>

# ── Vnstock ───────────────────────────────────────────────────────────────────
VNSTOCK_SOURCE=vci
VNSTOCK_API_KEY=          # Để trống nếu không dùng sponsor packages

# ── Pipeline ──────────────────────────────────────────────────────────────────
MAX_WORKERS=5
REQUEST_DELAY=0.3
RETRY_ATTEMPTS=3
RETRY_WAIT_MIN=1.0
RETRY_WAIT_MAX=10.0
DB_CHUNK_SIZE=500

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_DIR=logs

# ── Scheduler (cron expressions — chuẩn Unix 5-field) ────────────────────────
CRON_SYNC_LISTING="0 1 * * 0"        # Chủ Nhật 01:00
CRON_SYNC_FINANCIALS="0 3 1,15 * *"  # Ngày 1 & 15 hàng tháng 03:00
CRON_SYNC_COMPANY="0 2 * * 1"        # Thứ Hai 02:00
CRON_SYNC_RATIOS="30 18 * * *"       # Hàng ngày 18:30
CRON_SYNC_PRICES="0 19 * * 1-5"     # Thứ 2–6 lúc 19:00 (sau đóng cửa sàn)
CRON_ALERT_CHECK="0 * * * *"        # Hàng giờ :00

# ── Alert ─────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=<token_từ_BotFather>
TELEGRAM_CHAT_ID=<chat_id_của_bạn>
ALERT_FAIL_THRESHOLD=3

# ── DNSE (sync_prices lịch sử + realtime pipeline) ────────────────────────────
DNSE_USERNAME=<email_hoặc_sdt_đăng_ký_dnse>
DNSE_PASSWORD=<mật_khẩu_dnse>

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST=localhost       # Docker override thành "redis"
REDIS_PORT=6379

# ── Real-time pipeline ─────────────────────────────────────────────────────────
REALTIME_ENABLED=true
REALTIME_WATCHLIST=        # Để trống = tự động lấy VN30 từ DB
REALTIME_RESOLUTIONS=1,5   # Nến 1 phút và 5 phút
CRON_REALTIME_START=0 7 * * 1-5    # Thứ 2–6 lúc 07:00 (trước ATO)
CRON_REALTIME_STOP=15 15 * * 1-5   # Thứ 2–6 lúc 15:15 (sau ATC)
```

> **Quan trọng:** `.env` KHÔNG được commit lên git. File `.gitignore` đã loại trừ nó.

### 3.2 Thiết lập Telegram Bot (để nhận alert)

```
1. Mở Telegram → tìm @BotFather → /newbot
2. Đặt tên bot → nhận TELEGRAM_BOT_TOKEN
3. Nhắn tin cho bot (để bot nhận diện chat)
4. Gọi API lấy chat_id:
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
5. Tìm "chat": {"id": <số_này_là_CHAT_ID>}
6. Điền vào .env
```

### 3.3 Kiểm tra code trước khi push

```bash
# Test nhanh trên local
python main.py sync_listing
python main.py sync_ratios --symbol HPG VCB FPT

# Test Telegram alert
python -c "from utils.alert import send_telegram; send_telegram('Test alert từ local')"
```

---

## 4. Triển khai lên VPS

### 4.1 Lần đầu: Cài Docker trên VPS

Đăng nhập VPS qua SSH, sau đó:

```bash
# Cập nhật package list
sudo apt-get update

# Cài các gói cần thiết
sudo apt-get install -y ca-certificates curl gnupg

# Thêm Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Thêm Docker repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Cài Docker Engine + Compose plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Cho phép user hiện tại dùng docker không cần sudo
sudo usermod -aG docker $USER
newgrp docker

# Kiểm tra
docker --version
docker compose version
```

### 4.2 Clone code lên VPS

```bash
mkdir -p ~/apps && cd ~/apps
git clone <your-repo-url> data-pipeline
cd data-pipeline
```

### 4.3 Cấu hình .env trên VPS

```bash
cp .env.example .env
nano .env   # Điền đầy đủ theo hướng dẫn Mục 3.1
```

### 4.4 Khởi động lần đầu (5 services)

```bash
# Build image và khởi động toàn bộ stack
docker compose up -d --build
```

Khi chạy lần đầu, Docker sẽ:
1. Pull image `timescale/timescaledb:latest-pg16` và `redis:7-alpine`
2. Build image `python:3.12-slim` với tất cả dependencies (~3–5 phút)
3. Khởi động `stockapp_db` — TimescaleDB tự chạy toàn bộ `db/migrations/*.sql` (bao gồm tạo hypertables)
4. Khởi động `stockapp_redis` — Redis với AOF persistence + maxmemory 512mb
5. Chờ cả postgres và redis healthy
6. Khởi động `stockapp_pipeline` → `python main.py schedule`:
   - APScheduler khởi động với 8 jobs
   - Nếu `REALTIME_ENABLED=true`: StreamProcessor daemon thread khởi động ngay
   - Realtime subscriber sẽ start lúc 07:00 (Mon–Fri) theo lịch
7. Khởi động `stockapp_rt_subscriber` và `stockapp_rt_processor`

```bash
# Theo dõi quá trình khởi động
docker compose logs -f
```

**Output mong đợi:**
```
stockapp_db          | TimescaleDB loaded
stockapp_db          | database system is ready to accept connections
stockapp_redis       | Ready to accept connections
stockapp_pipeline    | PostgreSQL is ready
stockapp_pipeline    | Starting scheduler...
stockapp_pipeline    | Scheduler dang chay. Nhan Ctrl+C de dung.
stockapp_pipeline    | Jobs da dang ky (8):
stockapp_pipeline    |   - sync_listing        : Sun 01:00 ICT
stockapp_pipeline    |   - sync_financials      : ngay 1 & 15, 03:00 ICT
stockapp_pipeline    |   - sync_company         : Mon 02:00 ICT
stockapp_pipeline    |   - sync_ratios          : daily 18:30 ICT
stockapp_pipeline    |   - sync_prices          : Mon-Fri 19:00 ICT
stockapp_pipeline    |   - alert_check          : every hour :00
stockapp_pipeline    |   - realtime_start       : Mon-Fri 07:00 ICT
stockapp_pipeline    |   - realtime_stop        : Mon-Fri 15:15 ICT
stockapp_pipeline    | StreamProcessor daemon started.
stockapp_rt_subscriber | [subscriber] Connecting to DNSE MDDS...
stockapp_rt_processor  | [processor] Consumer group ready. Waiting for messages...
```

### 4.5 Kiểm tra trạng thái

```bash
# Tất cả 5 services phải running/healthy
docker compose ps

# Output mong đợi:
# stockapp_db           running (healthy)
# stockapp_redis        running (healthy)
# stockapp_pipeline     running
# stockapp_rt_subscriber running
# stockapp_rt_processor  running
```

---

## 5. Đồng bộ dữ liệu ban đầu

Scheduler **không tự sync ngay** — nó chờ đến đúng giờ. Để có dữ liệu ngay, chạy thủ công theo **đúng thứ tự** sau (có FK dependencies):

```
sync_listing  →  sync_company  →  sync_financials  →  sync_ratios  →  sync_prices
```

> **Lý do thứ tự:** `financial_reports`, `shareholders`, `ratio_summary`, `price_history` đều có FK về `companies(symbol)`. `sync_company` cũng cập nhật `icb_code` — cần có trước khi parse BCTC theo template ngành.

### Bước 1 — Sync danh mục mã và phân ngành ICB

```bash
docker compose exec pipeline python main.py sync_listing
```

**Thời gian:** ~1–2 phút
**Kết quả:** ~200 ngành ICB + ~1,550 mã chứng khoán vào bảng `companies`

### Bước 2 — Sync thông tin doanh nghiệp (cập nhật icb_code)

```bash
screen -S sync_company
docker compose exec pipeline python main.py sync_company
# Ctrl+A, D để detach
```

**Thời gian:** ~30–60 phút
**Kết quả:** ~73,000+ rows vào `shareholders`, `officers`, `subsidiaries`, `corporate_events` + cập nhật `companies.icb_code`

### Bước 3 — Sync báo cáo tài chính (bước lâu nhất)

```bash
screen -S sync_fin
docker compose exec pipeline python main.py sync_financials
# Ctrl+A, D để detach; screen -r sync_fin để xem lại
```

**Thời gian:** ~2–4 giờ (1,550 mã × 3 loại BCTC × 5 luồng + cross-validation)
**Kết quả:** ~180,000+ rows vào bảng `financial_reports` (unified table với `statement_type` ENUM: balance_sheet/income_statement/cash_flow)

> **Lưu ý:** Không còn 4 bảng riêng biệt (`balance_sheets`, `income_statements`, `cash_flows`, `financial_ratios`). Tất cả BCTC lưu trong 1 bảng `financial_reports` với cột `template` phân loại theo ngành (non_financial/banking/securities/insurance).

### Bước 4 — Sync ratio summary

```bash
docker compose exec pipeline python main.py sync_ratios
```

**Thời gian:** ~10–15 phút
**Kết quả:** ~7,600 rows vào `ratio_summary`

### Bước 5 — Sync giá lịch sử OHLCV (5 năm)

```bash
screen -S sync_prices
docker compose exec pipeline python main.py sync_prices --full-history
# Ctrl+A, D để detach
```

**Thời gian:** ~1–2 giờ (KBS primary + VNDirect fallback, incremental sau lần đầu)
**Kết quả:** ~1,900,000+ rows vào hypertable `price_history` (5 năm × ~1,550 mã)

### Bước 6 — Xác nhận dữ liệu

```bash
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT
    'icb_industries'   AS bang, COUNT(*) AS so_rows FROM icb_industries
UNION ALL SELECT 'companies',         COUNT(*) FROM companies
UNION ALL SELECT 'financial_reports', COUNT(*) FROM financial_reports
UNION ALL SELECT 'shareholders',      COUNT(*) FROM shareholders
UNION ALL SELECT 'officers',          COUNT(*) FROM officers
UNION ALL SELECT 'subsidiaries',      COUNT(*) FROM subsidiaries
UNION ALL SELECT 'corporate_events',  COUNT(*) FROM corporate_events
UNION ALL SELECT 'ratio_summary',     COUNT(*) FROM ratio_summary
UNION ALL SELECT 'price_history',     COUNT(*) FROM price_history
UNION ALL SELECT 'price_intraday',    COUNT(*) FROM price_intraday;
"
```

**Kết quả tham khảo (sau initial sync hoàn chỉnh):**

| Bảng | Số rows (~) | Ghi chú |
|---|---|---|
| `icb_industries` | ~200 | |
| `companies` | ~1,550 | |
| `financial_reports` | ~180,000 | Unified: BS + IS + CF |
| `shareholders` | ~15,000 | |
| `officers` | ~25,000 | |
| `subsidiaries` | ~15,000 | |
| `corporate_events` | ~20,000 | |
| `ratio_summary` | ~7,600 | |
| `price_history` | ~1,900,000 | 5 năm daily OHLCV |
| `price_intraday` | 0 (ban đầu) | Tích lũy trong giờ giao dịch |

---

## 6. Kết nối Spring Boot Backend

### 6.1 Tạo user database cho backend

```bash
docker compose exec postgres psql -U postgres -d stockapp
```

```sql
-- User chỉ đọc cho Spring Boot
CREATE USER webapp_readonly WITH PASSWORD '<đặt_password_mạnh_riêng>';
GRANT CONNECT ON DATABASE stockapp TO webapp_readonly;
GRANT USAGE ON SCHEMA public TO webapp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO webapp_readonly;

-- Áp dụng cho bảng mới trong tương lai
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO webapp_readonly;

-- Nếu cần truy cập TimescaleDB continuous aggregates
GRANT SELECT ON ALL MATERIALIZED VIEWS IN SCHEMA public TO webapp_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO webapp_readonly;
```

> **Tùy chọn:** Nếu backend cần ghi (ví dụ lưu watchlist người dùng), tạo schema riêng:
> ```sql
> CREATE SCHEMA app;
> GRANT ALL ON SCHEMA app TO webapp_readonly;
> -- Chỉ readonly trên schema public (pipeline data)
> -- Đọc/ghi trên schema app (app data)
> ```

### 6.2 Cấu hình `application.properties` / `application.yml`

**`application.properties`:**
```properties
# DataSource
spring.datasource.url=jdbc:postgresql://<IP_VPS>:5432/stockapp
spring.datasource.username=webapp_readonly
spring.datasource.password=<password_webapp_readonly>
spring.datasource.driver-class-name=org.postgresql.Driver

# HikariCP connection pool
spring.datasource.hikari.connection-timeout=30000
spring.datasource.hikari.idle-timeout=600000
spring.datasource.hikari.max-lifetime=1800000
spring.datasource.hikari.maximum-pool-size=10
spring.datasource.hikari.minimum-idle=2
spring.datasource.hikari.pool-name=StockappPool

# JPA / Hibernate
spring.jpa.database-platform=org.hibernate.dialect.PostgreSQLDialect
spring.jpa.hibernate.ddl-auto=none
spring.jpa.show-sql=false
spring.jpa.properties.hibernate.jdbc.time_zone=Asia/Ho_Chi_Minh
```

**`application.yml` (nếu dùng YAML):**
```yaml
spring:
  datasource:
    url: jdbc:postgresql://<IP_VPS>:5432/stockapp
    username: webapp_readonly
    password: <password_webapp_readonly>
    driver-class-name: org.postgresql.Driver
    hikari:
      connection-timeout: 30000
      idle-timeout: 600000
      max-lifetime: 1800000
      maximum-pool-size: 10
      minimum-idle: 2
      pool-name: StockappPool
  jpa:
    database-platform: org.hibernate.dialect.PostgreSQLDialect
    hibernate:
      ddl-auto: none
    show-sql: false
    properties:
      hibernate:
        jdbc:
          time_zone: Asia/Ho_Chi_Minh
```

### 6.3 Lưu ý quan trọng cho JPA với TimescaleDB

**1. Không dùng `ddl-auto=create` hoặc `ddl-auto=update`**
Schema được quản lý bởi pipeline migrations. `ddl-auto=none` là bắt buộc.

**2. Hypertable — JPA/Hibernate không hiểu TimescaleDB extensions**
- Hibernate không biết `price_history` và `price_intraday` là hypertables.
- Mapping bình thường với `@Entity @Table` — Hibernate chỉ cần truy cập qua SQL/JPQL chuẩn.
- Tránh dùng `@GeneratedValue(strategy=SEQUENCE)` trên hypertables — TimescaleDB chunk partition không tương thích tốt.

**3. Truy vấn Continuous Aggregates**
- `cagg_ohlc_5m`, `cagg_ohlc_1h`, `cagg_ohlc_1d` là materialized views — truy cập như bảng thường.
- Dùng `@Query` native SQL hoặc `JdbcTemplate` cho các truy vấn timeseries phức tạp.

**4. Entity mapping ví dụ:**

```java
// Company entity
@Entity
@Table(name = "companies")
public class Company {
    @Id
    @Column(name = "symbol", length = 10)
    private String symbol;

    @Column(name = "icb_code")
    private String icbCode;

    @Column(name = "status")
    private String status;

    // getters/setters...
}

// Price history (hypertable) — sử dụng composite PK
@Entity
@Table(name = "price_history")
@IdClass(PriceHistoryId.class)
public class PriceHistory {
    @Id
    @Column(name = "symbol")
    private String symbol;

    @Id
    @Column(name = "date")
    private LocalDate date;

    @Column(name = "open")
    private BigDecimal open;

    @Column(name = "close")
    private BigDecimal close;

    @Column(name = "volume")
    private Long volume;
    // ...
}

// Financial reports — unified table
@Entity
@Table(name = "financial_reports")
public class FinancialReport {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "symbol")
    private String symbol;

    @Column(name = "statement_type")     // balance_sheet / income_statement / cash_flow
    private String statementType;

    @Column(name = "template")           // non_financial / banking / securities / insurance
    private String template;

    @Column(name = "year")
    private Integer year;

    @Column(name = "quarter")            // 0 = annual, 1–4 = quarterly
    private Integer quarter;

    @Type(JsonBinaryType.class)          // Hibernate types for JSONB
    @Column(name = "raw_details", columnDefinition = "jsonb")
    private Map<String, Object> rawDetails;
    // ...
}
```

**5. Dependency pom.xml (PostgreSQL + JSONB support):**
```xml
<dependency>
    <groupId>org.postgresql</groupId>
    <artifactId>postgresql</artifactId>
    <scope>runtime</scope>
</dependency>

<!-- Cho JSONB column trong financial_reports -->
<dependency>
    <groupId>io.hypersistence</groupId>
    <artifactId>hypersistence-utils-hibernate-63</artifactId>
    <version>3.7.0</version>
</dependency>
```

### 6.4 Firewall cho kết nối từ backend

**Nếu Spring Boot ở cùng VPS:**
```bash
# Không cần mở port 5432 ra internet
# Backend kết nối qua localhost hoặc Docker internal network
```

**Nếu Spring Boot ở server riêng:**
```bash
# Chỉ mở port 5432 cho IP của backend server
sudo ufw allow from <IP_BACKEND_SERVER> to any port 5432
sudo ufw status
```

### 6.5 Truy vấn dữ liệu realtime từ backend

```java
// Lấy giá intraday mới nhất (từ price_intraday hypertable)
@Repository
public interface PriceIntradayRepository extends JpaRepository<PriceIntraday, ...> {

    @Query(value = """
        SELECT * FROM price_intraday
        WHERE symbol = :symbol
          AND resolution = :resolution
          AND ts >= NOW() - INTERVAL '1 day'
        ORDER BY ts DESC
        LIMIT 100
        """, nativeQuery = true)
    List<PriceIntraday> findRecent(
        @Param("symbol") String symbol,
        @Param("resolution") int resolution
    );
}

// Truy vấn từ continuous aggregate (nhanh hơn nhiều)
@Query(value = """
    SELECT * FROM cagg_ohlc_1h
    WHERE symbol = :symbol
      AND bucket >= :from
    ORDER BY bucket
    """, nativeQuery = true)
List<Object[]> findHourlyCandles(
    @Param("symbol") String symbol,
    @Param("from") LocalDateTime from
);
```

---

## 7. Kiểm tra sau triển khai

### 7.1 Checklist kỹ thuật

```bash
# 1. Tất cả 5 containers đều running
docker compose ps

# 2. Log pipeline không có lỗi nghiêm trọng
docker compose logs pipeline --tail=100 | grep -E "ERROR|CRITICAL"

# 3. Log files xuất hiện trên máy host
ls -la ./logs/

# 4. PostgreSQL accessible từ ngoài (test từ backend server)
psql postgresql://webapp_readonly:<pass>@<ip>:5432/stockapp -c "\dt"

# 5. Redis hoạt động
docker compose exec redis redis-cli ping
# PONG

# 6. Kiểm tra TimescaleDB extension
docker compose exec postgres psql -U postgres -d stockapp \
    -c "SELECT extname, extversion FROM pg_extension WHERE extname='timescaledb';"

# 7. Test Telegram alert
docker compose exec pipeline python -c \
    "from utils.alert import send_telegram; send_telegram('Pipeline deployed thanh cong!')"
```

### 7.2 Kiểm tra pipeline_logs

```bash
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT job_name, symbol, status, records_inserted, started_at
FROM pipeline_logs
ORDER BY started_at DESC
LIMIT 20;
"
```

### 7.3 Kiểm tra realtime pipeline (trong giờ giao dịch)

```bash
# Kiểm tra Redis Streams có data chưa
docker compose exec redis redis-cli XLEN ohlc:1m
docker compose exec redis redis-cli XLEN ohlc:5m

# Kiểm tra consumer group
docker compose exec redis redis-cli XINFO GROUPS ohlc:1m

# Xem price_intraday có data không
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT symbol, resolution, COUNT(*), MAX(ts) as latest
FROM price_intraday
GROUP BY symbol, resolution
ORDER BY latest DESC
LIMIT 10;
"
```

---

## 8. Vận hành thường ngày

### 8.1 Lịch chạy tự động (8 jobs + 1 daemon)

| Job | Cron | Mô tả |
|---|---|---|
| `sync_listing` | Chủ Nhật 01:00 | Refresh danh mục & ngành ICB |
| `sync_financials` | Ngày 1 & 15, 03:00 | BCTC 3 loại → financial_reports (+ cross-validate) |
| `sync_company` | Thứ Hai 02:00 | Company intelligence + cập nhật icb_code |
| `sync_ratios` | Hàng ngày 18:30 | Ratio snapshot sau đóng cửa |
| `sync_prices` | Thứ 2–6, 19:00 | Giá daily OHLCV → price_history (incremental) |
| `alert_check` | Hàng giờ :00 | Kiểm tra lỗi → Telegram |
| `realtime_subscriber_start` | Thứ 2–6, 07:00 | Bật MQTT subscriber (DNSE MDDS) |
| `realtime_subscriber_stop` | Thứ 2–6, 15:15 | Tắt MQTT subscriber |
| `stream_processor` | Luôn chạy (daemon) | Redis Streams → price_intraday (24/7) |

### 8.2 Xem log

```bash
# Log realtime của từng service
docker compose logs -f pipeline
docker compose logs -f realtime-subscriber
docker compose logs -f realtime-processor

# Log file trên host (ngày hôm nay)
tail -f ./logs/pipeline_$(date +%Y-%m-%d).log

# Tìm kiếm lỗi
grep "ERROR\|CRITICAL" ./logs/pipeline_$(date +%Y-%m-%d).log
```

### 8.3 Chạy thủ công (không chờ lịch)

```bash
# Sync toàn bộ
docker compose exec pipeline python main.py sync_ratios
docker compose exec pipeline python main.py sync_prices

# Sync một vài mã cụ thể
docker compose exec pipeline python main.py sync_financials --symbols HPG VCB FPT
docker compose exec pipeline python main.py sync_prices --symbol HPG VCB --workers 3

# Fetch lại toàn bộ lịch sử giá (5 năm)
docker compose exec pipeline python main.py sync_prices --full-history
```

### 8.4 Monitor pipeline_logs

```sql
-- Xem 20 lần chạy gần nhất
SELECT job_name, symbol, status, records_fetched, records_inserted, started_at
FROM pipeline_logs
ORDER BY started_at DESC
LIMIT 20;

-- Đếm lỗi 7 ngày qua
SELECT job_name, COUNT(*) AS fail_count
FROM pipeline_logs
WHERE status = 'failed' AND started_at >= NOW() - INTERVAL '7 days'
GROUP BY job_name
ORDER BY fail_count DESC;

-- Thời gian chạy trung bình
SELECT job_name, ROUND(AVG(EXTRACT(EPOCH FROM (finished_at - started_at))), 1) AS avg_giay
FROM pipeline_logs
WHERE status = 'success' AND finished_at IS NOT NULL
GROUP BY job_name;
```

### 8.5 Monitor TimescaleDB

```sql
-- Kích thước các hypertable (sau compression)
SELECT hypertable_name,
       pg_size_pretty(hypertable_size(format('%I', hypertable_name)::regclass)) AS kich_thuoc
FROM timescaledb_information.hypertables;

-- Số chunks của price_history
SELECT count(*) AS so_chunks
FROM timescaledb_information.chunks
WHERE hypertable_name = 'price_history';

-- Trạng thái continuous aggregates
SELECT view_name, last_run_status, last_run_duration
FROM timescaledb_information.continuous_aggregate_stats;
```

---

## 9. Cập nhật code (CI/CD thủ công)

### 9.1 Cập nhật code không thay đổi schema

```bash
cd ~/apps/data-pipeline
git pull origin main

# Rebuild chỉ pipeline service (không đụng DB và Redis)
docker compose up -d --build pipeline

# Nếu cần rebuild cả realtime services
docker compose up -d --build realtime-subscriber realtime-processor

docker compose ps
docker compose logs pipeline --tail=30
```

### 9.2 Cập nhật có migration mới

```bash
cd ~/apps/data-pipeline
git pull origin main

# Chạy migration thủ công (TimescaleDB đang chạy)
docker compose exec pipeline python -m db.migrate

# Rebuild pipeline
docker compose up -d --build pipeline
```

> **Lưu ý:** Volume mount `./db/migrations:/docker-entrypoint-initdb.d` chỉ tự chạy khi **khởi tạo PostgreSQL lần đầu** (volume trống). Migration sau phải chạy thủ công qua `db.migrate`.

### 9.3 Cập nhật dependencies

```bash
git pull origin main
# Rebuild hoàn toàn (xóa cache layer cũ)
docker compose build --no-cache pipeline realtime-subscriber realtime-processor
docker compose up -d pipeline realtime-subscriber realtime-processor
```

---

## 10. Xử lý sự cố

### 10.1 Container pipeline bị restart liên tục

```bash
docker compose logs pipeline --tail=100
docker inspect stockapp_pipeline | grep ExitCode
```

**Nguyên nhân thường gặp:**
- `.env` thiếu `DB_PASSWORD` hoặc `DNSE_USERNAME/PASSWORD` → check `.env`
- PostgreSQL hoặc Redis chưa healthy → chờ, sẽ tự hết sau vài lần retry
- Import error từ module mới → xem log stack trace, sửa code

### 10.2 Realtime subscriber không nhận được dữ liệu

```bash
# Kiểm tra subscriber log
docker compose logs realtime-subscriber --tail=50

# Kiểm tra Redis Streams
docker compose exec redis redis-cli XLEN ohlc:1m

# Kiểm tra DNSE credentials hợp lệ
docker compose exec realtime-subscriber python -c "
from realtime.subscriber import MQTTSubscriber
s = MQTTSubscriber()
print('Auth OK')
"
```

**Nguyên nhân thường gặp:**
- `DNSE_USERNAME`/`DNSE_PASSWORD` sai → kiểm tra `.env`
- Ngoài giờ giao dịch → subscriber connect nhưng DNSE không push data (bình thường)
- JWT expired → subscriber tự refresh mỗi 7 giờ, log sẽ thấy "Token refreshed"

### 10.3 Redis Streams tồn đọng (processor không xử lý kịp)

```bash
# Kiểm tra pending messages
docker compose exec redis redis-cli XPENDING ohlc:1m ohlc-processors - + 10

# Restart processor để claim lại pending messages
docker compose restart realtime-processor

# Hoặc reset offset về 0 để reprocess tất cả
docker compose exec redis redis-cli XGROUP SETID ohlc:1m ohlc-processors 0
```

### 10.4 PostgreSQL không khởi động hoặc corrupt

```bash
docker compose logs postgres

# Nếu cần reset toàn bộ (mất data — chỉ dùng khi không còn cách nào)
docker compose down
docker volume rm data-pipeline_postgres_data
docker compose up -d --build
# Chạy lại initial sync (Mục 5)
```

### 10.5 Job bị miss (scheduler restart sau reboot)

Nếu VPS reboot trong giờ chạy job, APScheduler bỏ qua job nếu quá `misfire_grace_time`. Chạy thủ công:

```bash
docker compose exec pipeline python main.py sync_ratios
docker compose exec pipeline python main.py sync_prices
```

### 10.6 Disk đầy

```bash
df -h

# Xóa log cũ (giữ 30 ngày)
find ./logs/ -name "*.log" -mtime +30 -delete

# Xóa Docker images không dùng
docker image prune -f

# TimescaleDB compression thủ công (nếu auto-compression chưa chạy)
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT compress_chunk(c) FROM show_chunks('price_history', older_than => INTERVAL '7 days') c;
"
```

---

## 11. Rollback

### 11.1 Rollback code

```bash
cd ~/apps/data-pipeline
git log --oneline -10
git checkout <commit_hash>
docker compose up -d --build pipeline realtime-subscriber realtime-processor
```

### 11.2 Rollback schema

```bash
docker compose exec postgres psql -U postgres -d stockapp
-- Chạy SQL rollback thủ công tương ứng với migration đã chạy
```

> Backup DB trước khi chạy migration rủi ro cao.

### 11.3 Backup và restore

```bash
# Backup (dùng pg_dump chuẩn — hoạt động với TimescaleDB)
docker compose exec postgres pg_dump -U postgres stockapp \
    --exclude-table-data='price_intraday' \
    > backup_$(date +%Y%m%d_%H%M).sql

# Backup đầy đủ (bao gồm intraday — lớn hơn)
docker compose exec postgres pg_dump -U postgres stockapp \
    > backup_full_$(date +%Y%m%d_%H%M).sql

# Restore
cat backup_YYYYMMDD_HHMM.sql | \
    docker compose exec -T postgres psql -U postgres stockapp
```

> **Lưu ý:** `price_history` và `price_intraday` là hypertables. `pg_dump` hoạt động bình thường với chúng, nhưng restore vào một DB chưa có TimescaleDB extension sẽ lỗi. Đảm bảo restore vào DB đã có `CREATE EXTENSION timescaledb`.

---

## 12. Bảo mật

### 12.1 Firewall (UFW)

```bash
# SSH + port 5432 (chỉ mở nếu Spring Boot ở server khác)
sudo ufw allow OpenSSH
sudo ufw allow from <IP_SPRING_BOOT_SERVER> to any port 5432
# KHÔNG mở port 5432 cho toàn internet
sudo ufw enable
sudo ufw status
```

### 12.2 Password mạnh

- `DB_PASSWORD`: Tối thiểu 16 ký tự, chữ hoa/thường/số/ký tự đặc biệt.
- `webapp_readonly` password: Khác hoàn toàn `DB_PASSWORD`.
- `DNSE_PASSWORD`: Mật khẩu tài khoản DNSE thật — bảo vệ cẩn thận.

### 12.3 Không commit .env

```bash
git status | grep .env
# Không được có output — nếu có, xóa khỏi git:
git rm --cached .env
```

### 12.4 SSH hardening

```bash
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no
sudo systemctl restart ssh
```

### 12.5 Giới hạn quyền DB

- User `postgres`: Chỉ dùng trong container — KHÔNG để Spring Boot kết nối bằng user này.
- User `webapp_readonly`: Chỉ SELECT — Spring Boot backend dùng user này.
- Redis không có password mặc định — cân nhắc thêm `requirepass` trong `redis.conf` cho môi trường production.

```bash
# Thêm Redis password (nếu cần)
# Trong docker-compose.yml, thêm vào command:
#   --requirepass <redis_password>
# Và trong .env:
#   REDIS_PASSWORD=<redis_password>
```

---

## 13. Checklist triển khai

### Trước khi deploy

- [ ] `.env` đã điền đầy đủ: `DB_PASSWORD`, `DNSE_USERNAME`, `DNSE_PASSWORD`, `TELEGRAM_*`
- [ ] Test DNSE credentials: `python main.py sync_prices --symbol HPG --workers 1`
- [ ] Test Telegram bot nhận tin nhắn thử
- [ ] Code đã push lên git (branch `main`)

### Deploy lên VPS

- [ ] VPS đã cài Docker + Docker Compose plugin
- [ ] Code đã clone lên VPS
- [ ] `.env` đã copy và điền trên VPS
- [ ] `docker compose up -d --build` chạy thành công
- [ ] Tất cả 5 containers đều `running (healthy)`
- [ ] Log pipeline hiển thị "8 jobs registered" không có lỗi
- [ ] `docker compose exec redis redis-cli ping` trả về `PONG`
- [ ] `docker compose exec postgres psql -U postgres -d stockapp -c "SELECT extname FROM pg_extension WHERE extname='timescaledb';"` trả về row

### Initial sync

- [ ] `sync_listing` hoàn thành (~200 ngành, ~1,550 mã)
- [ ] `sync_company` hoàn thành (~73,000+ rows, icb_code đã cập nhật)
- [ ] `sync_financials` hoàn thành (~180,000+ rows trong `financial_reports`)
- [ ] `sync_ratios` hoàn thành (~7,600 rows)
- [ ] `sync_prices --full-history` hoàn thành (~1,900,000+ rows trong `price_history`)
- [ ] `pipeline_logs` có records với `status='success'` cho tất cả jobs

### Kết nối Spring Boot

- [ ] User `webapp_readonly` đã tạo với password mạnh
- [ ] Firewall đã cấu hình đúng (chỉ mở port 5432 cho IP backend nếu cần)
- [ ] Spring Boot kết nối thành công (`spring.datasource.url` trỏ đúng VPS)
- [ ] `ddl-auto=none` được set — không để Hibernate tự sửa schema
- [ ] Backend query thành công `companies`, `financial_reports`, `price_history`

### Kiểm tra vận hành tự động

- [ ] `sync_ratios` tự chạy lúc 18:30 (xác nhận ngày đầu tiên)
- [ ] `sync_prices` tự chạy lúc 19:00 Thứ 2–6 (xác nhận ngày Thứ 2 đầu tiên)
- [ ] `alert_check` chạy mỗi giờ không báo lỗi giả
- [ ] Telegram nhận alert test thành công
- [ ] Trong giờ giao dịch (Mon–Fri 07:00–15:15): `price_intraday` tích lũy data

---

*Tài liệu này áp dụng cho Phase 7 — TimescaleDB + Redis + Realtime Pipeline. Cập nhật: 2026-03-28.*
