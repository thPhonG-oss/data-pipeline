# Kế hoạch Triển khai — Data Pipeline Chứng khoán Việt Nam

> **Phiên bản:** Phase 6 | **Cập nhật:** 2026-03-20
> Tài liệu này mô tả toàn bộ quy trình triển khai pipeline lên môi trường sản xuất (VPS).
> Mục tiêu: pipeline tự chạy liên tục, dữ liệu luôn mới, có alert khi sự cố.

---

## Mục lục

1. [Kiến trúc tổng thể](#1-kiến-trúc-tổng-thể)
2. [Yêu cầu hệ thống](#2-yêu-cầu-hệ-thống)
3. [Chuẩn bị trước khi triển khai](#3-chuẩn-bị-trước-khi-triển-khai)
4. [Triển khai lên VPS](#4-triển-khai-lên-vps)
5. [Đồng bộ dữ liệu ban đầu](#5-đồng-bộ-dữ-liệu-ban-đầu)
6. [Kết nối Web Application](#6-kết-nối-web-application)
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
                          VPS (Ubuntu 22.04 / 2GB RAM)
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Docker Compose                                                 │
│  ┌────────────────────────┐   ┌──────────────────────────────┐  │
│  │  stockapp_pipeline     │   │  stockapp_db                 │  │
│  │  (python:3.12-slim)    │──►│  (postgres:16-alpine)        │  │
│  │                        │   │                              │  │
│  │  APScheduler           │   │  Database: stockapp          │  │
│  │  ├── sync_listing      │   │  Port: 5432 (expose)         │  │
│  │  ├── sync_financials   │   │  Volume: postgres_data       │  │
│  │  ├── sync_company      │   │                              │  │
│  │  ├── sync_ratios       │   └──────────────────────────────┘  │
│  │  └── alert_check       │                  │                  │
│  │                        │                  │ Port 5432        │
│  └────────────────────────┘                  ▼                  │
│                                                                 │
│  Volume: ./logs ──► /app/logs (log accessible từ host)          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                 │
                 │ Port 5432 (từ ngoài VPS)
                 ▼
       Web Application (dự án riêng)
       kết nối user webapp_readonly
```

**Điểm quan trọng:**
- Pipeline và PostgreSQL chạy trong cùng một Docker Compose stack.
- Web application kết nối vào PostgreSQL qua IP/port của VPS (user riêng, chỉ có quyền SELECT).
- Log ghi ra thư mục `./logs/` trên máy host — xem trực tiếp không cần vào container.
- `restart: unless-stopped` — tự khởi động lại sau khi VPS reboot.

---

## 2. Yêu cầu hệ thống

### 2.1 Thông số VPS tối thiểu

| Thành phần | Tối thiểu | Khuyến nghị |
|---|---|---|
| CPU | 1 vCPU | 2 vCPU |
| RAM | 2 GB | 4 GB |
| Ổ cứng | 20 GB SSD | 40 GB SSD |
| Băng thông | 100 Mbps | 200 Mbps |
| HĐH | Ubuntu 22.04 LTS | Ubuntu 22.04 LTS |

> **Tại sao 2 GB RAM?** PostgreSQL ~512 MB + pipeline (5 luồng) ~256 MB + OS + buffer = ~1.2–1.5 GB. 2 GB RAM là ngưỡng an toàn. VPS giá ~100,000–150,000 VND/tháng là đủ.

### 2.2 Phần mềm cần cài trên VPS

| Phần mềm | Phiên bản | Ghi chú |
|---|---|---|
| Docker Engine | ≥ 24.x | Không dùng Docker Desktop |
| Docker Compose plugin | ≥ 2.x | `docker compose` (không phải `docker-compose`) |
| Git | ≥ 2.x | Để clone và pull code |

### 2.3 Thứ gì cần chuẩn bị trước

- [ ] Tài khoản VPS (DigitalOcean, Vultr, Linode, hoặc VPS Việt Nam)
- [ ] SSH key để đăng nhập VPS
- [ ] `VNSTOCK_API_KEY` (nếu dùng sponsor packages — lấy từ vnstock.com)
- [ ] Telegram Bot Token + Chat ID (cho alert)
- [ ] Domain hoặc IP tĩnh của VPS

---

## 3. Chuẩn bị trước khi triển khai

### 3.1 Tạo file `.env` từ template

```bash
cp .env.example .env
```

Mở `.env` và điền đầy đủ:

```env
# ── Database ──────────────────────────────────────────────────────────────────
DB_HOST=localhost         # Giữ nguyên (pipeline trong Docker sẽ override thành "postgres")
DB_PORT=5432
DB_NAME=stockapp
DB_USER=postgres
DB_PASSWORD=<đặt_password_mạnh_ít_nhất_16_ký_tự>

# ── Vnstock ───────────────────────────────────────────────────────────────────
VNSTOCK_SOURCE=vci
VNSTOCK_API_KEY=<api_key_lấy_từ_vnstock.com>

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

# ── Alert ─────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=<token_từ_BotFather>
TELEGRAM_CHAT_ID=<chat_id_của_bạn>
ALERT_FAIL_THRESHOLD=3
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

### 3.3 Kiểm tra code trước khi push lên VPS

```bash
# Trên máy local — test nhanh với 3 mã
python main.py sync_listing
python main.py sync_ratios --symbol HPG VCB FPT

# Test Telegram alert
python -c "from utils.alert import send_telegram; send_telegram('✅ Test alert từ local')"
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
# Tạo thư mục làm việc
mkdir -p ~/apps && cd ~/apps

# Clone repo
git clone <your-repo-url> data-pipeline
cd data-pipeline
```

### 4.3 Cấu hình .env trên VPS

```bash
cp .env.example .env
nano .env   # Hoặc vim .env
# Điền đầy đủ theo hướng dẫn Mục 3.1
```

### 4.4 Khởi động lần đầu

```bash
# Build image và khởi động 2 services
docker compose up -d --build
```

Khi chạy lần đầu, Docker sẽ:
1. Build image pipeline (~3–5 phút — tải vnstock dependencies)
2. Khởi động `stockapp_db` (PostgreSQL tự chạy toàn bộ file `db/migrations/*.sql`)
3. Chờ PostgreSQL healthy (healthcheck mỗi 10 giây)
4. Khởi động `stockapp_pipeline` → `entrypoint.sh`:
   - Nếu có `VNSTOCK_API_KEY` → cài sponsor packages (`vnstock_data`)
   - Chờ PostgreSQL sẵn sàng (retry mỗi 3 giây)
   - Khởi động APScheduler

```bash
# Theo dõi quá trình khởi động
docker compose logs -f
```

**Output mong đợi:**
```
stockapp_db       | database system is ready to accept connections
stockapp_pipeline | ✓ Installing vnstock sponsor packages...
stockapp_pipeline | ✓ Sponsor packages installed
stockapp_pipeline | ✅ PostgreSQL is ready
stockapp_pipeline | 🚀 Starting scheduler...
stockapp_pipeline | Scheduler đang chạy. Nhấn Ctrl+C để dừng.
stockapp_pipeline | - sync_listing: 2026-03-23 01:00:00+07:00
stockapp_pipeline | - sync_financials: 2026-04-01 03:00:00+07:00
stockapp_pipeline | - sync_company: 2026-03-23 02:00:00+07:00
stockapp_pipeline | - sync_ratios: 2026-03-20 18:30:00+07:00
stockapp_pipeline | - alert_check: 2026-03-20 20:00:00+07:00
```

### 4.5 Kiểm tra trạng thái containers

```bash
docker compose ps
# Cả 2 service phải ở trạng thái "running" (healthy)

docker compose logs pipeline --tail=50
# Xem 50 dòng log gần nhất của pipeline
```

---

## 5. Đồng bộ dữ liệu ban đầu

Sau khi scheduler chạy, pipeline **không tự động sync ngay** — nó chờ đến đúng giờ trong lịch. Để có dữ liệu ngay lập tức, phải chạy thủ công theo **đúng thứ tự sau**:

```
sync_listing  →  sync_financials  →  sync_company  →  sync_ratios
```

> **Lý do thứ tự:** `balance_sheets`, `shareholders`, `ratio_summary` đều có FK trỏ về `companies(symbol)`. Nếu chạy sai thứ tự → `ForeignKeyViolation`.

### Bước 1 — Sync danh mục mã và phân ngành

```bash
docker compose exec pipeline python main.py sync_listing
```

**Thời gian:** ~1–2 phút
**Kết quả:** ~200 ngành ICB + ~1,550 mã chứng khoán trong bảng `companies`

### Bước 2 — Sync báo cáo tài chính (bước này lâu nhất)

```bash
docker compose exec pipeline python main.py sync_financials
```

**Thời gian:** ~2–4 giờ (1,550 mã × 4 loại báo cáo × 5 luồng)
**Kết quả:** ~6,200 tập dữ liệu vào `balance_sheets`, `income_statements`, `cash_flows`, `financial_ratios`

> **Tip:** Chạy trong `screen` hoặc `tmux` để không bị ngắt khi SSH timeout:
> ```bash
> screen -S sync_fin
> docker compose exec pipeline python main.py sync_financials
> # Ctrl+A, D để thoát khỏi screen (process vẫn chạy)
> screen -r sync_fin  # Gắn lại để xem tiến độ
> ```

### Bước 3 — Sync thông tin doanh nghiệp

```bash
docker compose exec pipeline python main.py sync_company
```

**Thời gian:** ~30–60 phút
**Kết quả:** ~73,000+ rows vào `shareholders`, `officers`, `subsidiaries`, `corporate_events` + cập nhật `companies.icb_code`

### Bước 4 — Sync ratio summary (snapshot hàng ngày)

```bash
docker compose exec pipeline python main.py sync_ratios
```

**Thời gian:** ~10–15 phút
**Kết quả:** ~7,600 rows vào `ratio_summary` (~1,525 mã, ~22 mã bị skip do không có dữ liệu)

### Bước 5 — Xác nhận dữ liệu

```bash
# Kết nối vào PostgreSQL và đếm records
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT
    'icb_industries'   AS bảng, COUNT(*) AS số_rows FROM icb_industries
UNION ALL SELECT 'companies',         COUNT(*) FROM companies
UNION ALL SELECT 'balance_sheets',    COUNT(*) FROM balance_sheets
UNION ALL SELECT 'income_statements', COUNT(*) FROM income_statements
UNION ALL SELECT 'cash_flows',        COUNT(*) FROM cash_flows
UNION ALL SELECT 'financial_ratios',  COUNT(*) FROM financial_ratios
UNION ALL SELECT 'shareholders',      COUNT(*) FROM shareholders
UNION ALL SELECT 'officers',          COUNT(*) FROM officers
UNION ALL SELECT 'subsidiaries',      COUNT(*) FROM subsidiaries
UNION ALL SELECT 'corporate_events',  COUNT(*) FROM corporate_events
UNION ALL SELECT 'ratio_summary',     COUNT(*) FROM ratio_summary;
"
```

**Kết quả tham khảo (sau initial sync hoàn chỉnh):**

| Bảng | Số rows (~) |
|---|---|
| `icb_industries` | ~200 |
| `companies` | ~1,550 |
| `balance_sheets` | ~60,000 |
| `income_statements` | ~60,000 |
| `cash_flows` | ~60,000 |
| `financial_ratios` | ~60,000 |
| `shareholders` | ~15,000 |
| `officers` | ~25,000 |
| `subsidiaries` | ~15,000 |
| `corporate_events` | ~20,000 |
| `ratio_summary` | ~7,600 |

---

## 6. Kết nối Web Application

### 6.1 Tạo user readonly cho web app

```bash
docker compose exec postgres psql -U postgres -d stockapp
```

```sql
-- Tạo user chỉ có quyền đọc
CREATE USER webapp_readonly WITH PASSWORD '<đặt_password_riêng>';
GRANT CONNECT ON DATABASE stockapp TO webapp_readonly;
GRANT USAGE ON SCHEMA public TO webapp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO webapp_readonly;

-- Áp dụng cho các bảng tạo mới trong tương lai
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO webapp_readonly;
```

### 6.2 Connection string cho web app

```
postgresql://webapp_readonly:<password>@<IP_VPS>:5432/stockapp
```

> **Lưu ý bảo mật:**
> - Port 5432 đang expose ra ngoài VPS. Nếu web app chạy trên cùng VPS, nên dùng IP nội bộ.
> - Nếu web app chạy trên server khác, cân nhắc mở firewall chỉ cho IP đó.

### 6.3 Kiểm tra kết nối từ web app

```bash
# Test từ máy khác
psql postgresql://webapp_readonly:<password>@<IP_VPS>:5432/stockapp \
    -c "SELECT COUNT(*) FROM companies;"
```

---

## 7. Kiểm tra sau triển khai

### 7.1 Checklist kỹ thuật

```bash
# 1. Cả 2 containers đều running và healthy
docker compose ps

# 2. Log pipeline không có lỗi nghiêm trọng
docker compose logs pipeline --tail=100 | grep -E "ERROR|CRITICAL"

# 3. Log file xuất hiện trên máy host
ls -la ./logs/
# Phải có: pipeline_YYYY-MM-DD.log và .vnstock_installed

# 4. PostgreSQL accessible từ ngoài
psql postgresql://webapp_readonly:<pass>@<ip>:5432/stockapp -c "\dt"

# 5. Test gửi Telegram alert
docker compose exec pipeline python -c \
    "from utils.alert import send_telegram; send_telegram('✅ Pipeline deployed thành công!')"
```

### 7.2 Kiểm tra pipeline_logs

```bash
docker compose exec postgres psql -U postgres -d stockapp -c "
SELECT job_name, status, records_success, duration_ms, started_at
FROM pipeline_logs
ORDER BY started_at DESC
LIMIT 20;
"
```

### 7.3 Chờ scheduler tự kích hoạt

Vào buổi tối ngày triển khai (18:30), `sync_ratios` sẽ tự chạy. Kiểm tra:

```bash
docker compose logs -f pipeline
# Theo dõi lúc 18:30
```

---

## 8. Vận hành thường ngày

### 8.1 Lịch chạy tự động

| Job | Cron | Mô tả |
|---|---|---|
| `sync_listing` | Chủ Nhật 01:00 | Refresh danh mục & ngành |
| `sync_financials` | Ngày 1 & 15, 03:00 | BCTC 4 loại |
| `sync_company` | Thứ Hai 02:00 | Company intelligence |
| `sync_ratios` | Hàng ngày 18:30 | Ratio snapshot sau đóng cửa |
| `alert_check` | Hàng giờ :00 | Kiểm tra lỗi → Telegram |

### 8.2 Xem log

```bash
# Log realtime
docker compose logs -f pipeline

# Log file trên host (ngày hôm nay)
tail -f ./logs/pipeline_$(date +%Y-%m-%d).log

# Tìm kiếm lỗi
grep "ERROR\|CRITICAL" ./logs/pipeline_$(date +%Y-%m-%d).log
```

### 8.3 Chạy thủ công (không chờ lịch)

```bash
# Sync toàn bộ
docker compose exec pipeline python main.py sync_ratios

# Sync một vài mã cụ thể
docker compose exec pipeline python main.py sync_financials --symbol HPG VCB FPT

# Sync với số luồng tùy chỉnh
docker compose exec pipeline python main.py sync_company --workers 3
```

### 8.4 Monitor pipeline_logs

```sql
-- Xem 20 lần chạy gần nhất
SELECT job_name, status, records_success, records_failed, duration_ms, started_at
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
SELECT job_name, ROUND(AVG(duration_ms)/1000.0, 1) AS avg_giây
FROM pipeline_logs
WHERE status = 'success'
GROUP BY job_name;
```

---

## 9. Cập nhật code (CI/CD thủ công)

### 9.1 Cập nhật code không thay đổi schema DB

```bash
# Trên VPS
cd ~/apps/data-pipeline
git pull origin main

# Rebuild chỉ pipeline service (không đụng DB)
docker compose up -d --build pipeline

# Kiểm tra container đã restart
docker compose ps
docker compose logs pipeline --tail=30
```

### 9.2 Cập nhật có thay đổi schema DB (thêm migration)

```bash
cd ~/apps/data-pipeline
git pull origin main

# Rebuild pipeline
docker compose up -d --build pipeline

# Chạy migration thủ công (PostgreSQL đang chạy)
docker compose exec pipeline python -m db.migrate

# Hoặc nếu migration nhỏ, chạy SQL trực tiếp
docker compose exec postgres psql -U postgres -d stockapp \
    -f /docker-entrypoint-initdb.d/005_new_migration.sql
```

> **Lưu ý:** Volume mount `./db/migrations:/docker-entrypoint-initdb.d` chỉ tự chạy khi **khởi tạo PostgreSQL lần đầu** (khi volume trống). Các migration sau phải chạy thủ công.

### 9.3 Cập nhật dependencies (requirements.txt thay đổi)

```bash
git pull origin main
# Rebuild hoàn toàn (xóa cache layer cũ)
docker compose build --no-cache pipeline
docker compose up -d pipeline
```

---

## 10. Xử lý sự cố

### 10.1 Container pipeline bị restart liên tục

```bash
# Xem lý do crash
docker compose logs pipeline --tail=100

# Kiểm tra exit code
docker inspect stockapp_pipeline | grep ExitCode
```

**Nguyên nhân thường gặp:**
- `.env` thiếu `DB_PASSWORD` → pipeline không kết nối được DB → crash
- `vnstock_data` chưa cài → `ModuleNotFoundError` → xem mục 10.3
- PostgreSQL chưa sẵn sàng → pipeline restart (normal, sẽ tự hết sau vài lần)

### 10.2 PostgreSQL không khởi động

```bash
docker compose logs postgres

# Kiểm tra volume có bị corrupt không
docker volume inspect data-pipeline_postgres_data
```

Nếu cần reset PostgreSQL (mất toàn bộ dữ liệu):

```bash
docker compose down
docker volume rm data-pipeline_postgres_data
docker compose up -d --build
# Sau đó chạy lại initial sync (Mục 5)
```

### 10.3 Lỗi `ModuleNotFoundError: No module named 'vnstock_data'`

```bash
# Kiểm tra flag file đã tồn tại chưa
ls -la ./logs/.vnstock_installed

# Nếu chưa có → entrypoint sẽ tự cài khi restart
# Nếu có nhưng package vẫn lỗi → force reinstall
rm ./logs/.vnstock_installed
docker compose restart pipeline

# Theo dõi quá trình cài
docker compose logs -f pipeline
```

### 10.4 Job bị miss (scheduler restart)

Nếu server bị reboot và scheduler bị dừng > `misfire_grace_time`, job sẽ bị bỏ qua. Chạy thủ công:

```bash
docker compose exec pipeline python main.py sync_ratios
docker compose exec pipeline python main.py sync_listing
```

### 10.5 Disk đầy

```bash
df -h  # Kiểm tra dung lượng

# Xóa log cũ (giữ 30 ngày gần nhất)
find ./logs/ -name "*.zip" -mtime +30 -delete
find ./logs/ -name "*.log" -mtime +30 -delete

# Xóa Docker images không dùng
docker image prune -f
docker system prune -f  # Cẩn thận: xóa cả containers đã stop
```

---

## 11. Rollback

### 11.1 Rollback code (không đụng DB)

```bash
cd ~/apps/data-pipeline

# Xem các commit gần nhất
git log --oneline -10

# Rollback về commit cũ
git checkout <commit_hash>

# Rebuild và deploy lại
docker compose up -d --build pipeline
```

### 11.2 Rollback schema DB (migration đã chạy)

```bash
# Kết nối vào DB
docker compose exec postgres psql -U postgres -d stockapp

# Chạy SQL rollback thủ công (đã viết sẵn trong file migration)
-- Ví dụ: ALTER TABLE balance_sheets DROP COLUMN IF EXISTS working_capital;
```

> **Khuyến nghị:** Backup DB trước khi chạy migration có rủi ro cao.

### 11.3 Backup và restore PostgreSQL

```bash
# Backup
docker compose exec postgres pg_dump -U postgres stockapp \
    > backup_$(date +%Y%m%d_%H%M).sql

# Restore từ backup
cat backup_YYYYMMDD_HHMM.sql | \
    docker compose exec -T postgres psql -U postgres stockapp
```

---

## 12. Bảo mật

### 12.1 Firewall (UFW)

```bash
# Chỉ cho phép SSH và port 5432 (nếu web app ở server khác)
sudo ufw allow OpenSSH
sudo ufw allow 5432/tcp  # Chỉ mở nếu web app ở server khác
sudo ufw enable
sudo ufw status
```

> **Nếu web app ở cùng VPS:** KHÔNG cần mở port 5432 ra internet. Web app kết nối qua `localhost:5432`.

### 12.2 Password mạnh

- `DB_PASSWORD`: Tối thiểu 16 ký tự, bao gồm chữ hoa, thường, số, ký tự đặc biệt.
- `webapp_readonly` password: Khác hoàn toàn với `DB_PASSWORD`.
- Không dùng password mặc định (`postgres`, `admin`, `123456`).

### 12.3 Không commit .env

```bash
# Kiểm tra .env không bị track
git status | grep .env
# Không được có output — nếu có, xóa khỏi git:
git rm --cached .env
```

### 12.4 SSH hardening

```bash
# Tắt đăng nhập bằng password (chỉ dùng SSH key)
sudo nano /etc/ssh/sshd_config
# PasswordAuthentication no
sudo systemctl restart ssh
```

### 12.5 Giới hạn quyền DB

- User `postgres`: Chỉ dùng trong container — KHÔNG expose ra ngoài.
- User `webapp_readonly`: Chỉ có quyền SELECT — pipeline không thể dùng nhầm.
- Cân nhắc tạo user `pipeline_writer` riêng thay vì dùng `postgres` superuser.

---

## 13. Checklist triển khai

### Trước khi deploy

- [ ] `.env` đã điền đầy đủ (DB_PASSWORD, VNSTOCK_API_KEY, TELEGRAM_*)
- [ ] Test Telegram bot nhận được tin nhắn thử
- [ ] Test local: `sync_listing` + `sync_ratios --symbol HPG VCB FPT` thành công
- [ ] Code đã được push lên git

### Deploy lên VPS

- [ ] VPS đã cài Docker + Docker Compose plugin
- [ ] Code đã clone lên VPS
- [ ] `.env` đã copy và điền trên VPS
- [ ] `docker compose up -d --build` chạy thành công
- [ ] Cả 2 containers đều `running (healthy)`
- [ ] Log pipeline không có lỗi

### Initial sync

- [ ] `sync_listing` hoàn thành (~200 ngành, ~1,550 mã)
- [ ] `sync_financials` hoàn thành (~240,000 rows trong 4 bảng BCTC)
- [ ] `sync_company` hoàn thành (~73,000+ rows)
- [ ] `sync_ratios` hoàn thành (~7,600 rows)
- [ ] `pipeline_logs` có records với status=`success`

### Kết nối web app

- [ ] User `webapp_readonly` đã tạo với password mạnh
- [ ] Web app kết nối thành công với connection string readonly
- [ ] Web app đọc được dữ liệu từ `companies`, `ratio_summary`, v.v.

### Kiểm tra vận hành tự động

- [ ] `sync_ratios` tự chạy lúc 18:30 (chờ và xác nhận)
- [ ] `alert_check` chạy mỗi giờ không báo lỗi giả
- [ ] Telegram nhận alert test thành công

---

*Kế hoạch triển khai này áp dụng cho Phase 6 — pipeline đã hoàn chỉnh. Cập nhật khi có thay đổi kiến trúc hoặc yêu cầu hệ thống.*
