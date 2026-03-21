# Kế hoạch Giai đoạn 6 — Đóng gói & Triển khai

**Trạng thái:** Đã lên kế hoạch

## Bối cảnh

Pipeline này là thành phần **cung cấp dữ liệu** trong đồ án tốt nghiệp *"Ứng dụng hỗ trợ đầu tư chứng khoán theo phương pháp phân tích cơ bản cho thị trường Việt Nam (ứng dụng web)"*.

```
┌─────────────────────────────┐        ┌──────────────────────────────┐
│      data-pipeline          │        │       web application        │
│                             │        │                              │
│  vnstock API → ETL → PostgreSQL ───► │  Backend API → Frontend UI  │
│  (scheduler chạy tự động)   │        │  (phân tích cơ bản, screener)│
└─────────────────────────────┘        └──────────────────────────────┘
```

Vai trò của pipeline trong giai đoạn này:
- **Không** xây dựng giao diện — đó là trách nhiệm của web application.
- **Chỉ cần** đóng gói, triển khai, và đảm bảo dữ liệu được cập nhật liên tục và ổn định.

Giai đoạn 6 gồm 2 hạng mục:

| Hạng mục | Mục tiêu |
|---|---|
| **Docker** | Đóng gói pipeline, chạy được trên bất kỳ máy chủ nào với 1 lệnh |
| **Alert** | Thông báo Telegram khi job thất bại — đảm bảo dữ liệu cho web app không bị stale |

---

## Phần 1 — Docker

### 1.1 Cấu trúc file

```
data-pipeline/
├── Dockerfile              # Image cho pipeline service
├── docker-compose.yml      # PostgreSQL + pipeline service
├── .env                    # Biến môi trường thực (không commit)
└── .env.example            # Template — commit vào repo
```

### 1.2 `Dockerfile` — Pipeline Service

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Cài dependencies trước — tận dụng Docker layer cache khi chỉ thay code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Mặc định khởi động scheduler — chạy tất cả jobs theo lịch tự động
CMD ["python", "main.py", "schedule"]
```

**Lưu ý:**
- `python:3.12-slim` giữ image nhỏ (~150 MB so với ~900 MB của `python:3.12`).
- `CMD` có thể override để chạy thủ công:
  ```bash
  docker compose exec pipeline python main.py sync_ratios --symbol HPG
  ```

### 1.3 `docker-compose.yml` — 2 services

Pipeline này chỉ cần 2 services. Web application sẽ kết nối vào PostgreSQL từ dự án riêng.

```yaml
services:

  # ── PostgreSQL ──────────────────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: stockapp_db
    restart: unless-stopped
    environment:
      POSTGRES_DB:       ${DB_NAME:-stockapp}
      POSTGRES_USER:     ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/migrations:/docker-entrypoint-initdb.d   # Tự chạy migrations khi init lần đầu
    ports:
      - "5432:5432"   # Expose để web application kết nối từ ngoài
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Pipeline Service ────────────────────────────────────────────────────────
  pipeline:
    build: .
    container_name: stockapp_pipeline
    restart: unless-stopped
    env_file: .env
    environment:
      DB_HOST: postgres   # Kết nối nội bộ qua tên service, không qua localhost
    volumes:
      - ./logs:/app/logs  # Log ghi ra máy host — xem được mà không cần vào container
    depends_on:
      postgres:
        condition: service_healthy

volumes:
  postgres_data:
```

**Điểm thiết kế quan trọng:**

| Quyết định | Lý do |
|---|---|
| `initdb.d` volume mount | PostgreSQL tự chạy tất cả `.sql` khi khởi tạo lần đầu — không cần `python -m db.migrate` thủ công |
| `DB_HOST: postgres` | Pipeline kết nối qua Docker internal network, không phải `localhost` |
| Port `5432` expose | Web application kết nối từ ngoài Docker network vào cùng PostgreSQL instance |
| `restart: unless-stopped` | Tự khởi động lại sau reboot VPS, không cần systemd |
| `./logs:/app/logs` | Log accessible trực tiếp trên máy host |

### 1.4 `.env.example`

```env
# ── Database ──────────────────────────────────────────────────────────────────
DB_HOST=localhost
DB_PORT=5432
DB_NAME=stockapp
DB_USER=postgres
DB_PASSWORD=your_strong_password_here

# ── Vnstock ───────────────────────────────────────────────────────────────────
VNSTOCK_SOURCE=vci
VNSTOCK_API_KEY=your_api_key_here

# ── Pipeline ──────────────────────────────────────────────────────────────────
MAX_WORKERS=5
REQUEST_DELAY=0.3
RETRY_ATTEMPTS=3
DB_CHUNK_SIZE=500

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL=INFO
LOG_DIR=logs

# ── Alert ─────────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
ALERT_FAIL_THRESHOLD=3
```

### 1.5 Lệnh vận hành thường dùng

```bash
# Khởi động lần đầu (build image + chạy 2 services)
docker compose up -d --build

# Xem log pipeline theo thời gian thực
docker compose logs -f pipeline

# Chạy thủ công một job (sync dữ liệu ngay, không đợi lịch)
docker compose exec pipeline python main.py sync_ratios
docker compose exec pipeline python main.py sync_financials --symbol HPG VCB

# Rebuild sau khi thay đổi code (chỉ rebuild pipeline, không đụng DB)
docker compose up -d --build pipeline

# Dừng tất cả (giữ nguyên dữ liệu trong volume)
docker compose down

# Reset hoàn toàn — xóa cả dữ liệu PostgreSQL
docker compose down -v
```

### 1.6 Kết nối từ Web Application

Web application kết nối vào cùng PostgreSQL instance theo connection string:

```
postgresql://postgres:<password>@<server_ip>:5432/stockapp
```

**Khuyến nghị:** Tạo user PostgreSQL riêng chỉ có quyền `SELECT` cho web application — tách biệt với user pipeline có quyền ghi:

```sql
-- Chạy trên PostgreSQL sau khi deploy
CREATE USER webapp_readonly WITH PASSWORD 'webapp_password';
GRANT CONNECT ON DATABASE stockapp TO webapp_readonly;
GRANT USAGE ON SCHEMA public TO webapp_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO webapp_readonly;

-- Áp dụng cho bảng tạo mới trong tương lai
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO webapp_readonly;
```

Web application dùng connection string:
```
postgresql://webapp_readonly:<webapp_password>@<server_ip>:5432/stockapp
```

---

## Phần 2 — Alert (Telegram Bot)

Pipeline là data backbone của web app. Nếu pipeline ngừng hoạt động, dữ liệu trên web app sẽ cũ và không đáng tin cậy. Alert giúp phát hiện sự cố sớm mà không cần theo dõi log thủ công.

### 2.1 Thiết lập Telegram Bot

```
1. Mở Telegram → tìm @BotFather → gõ /newbot
2. Đặt tên bot → nhận TELEGRAM_BOT_TOKEN
3. Nhắn tin cho bot → lấy TELEGRAM_CHAT_ID:
   curl https://api.telegram.org/bot<TOKEN>/getUpdates
4. Điền TOKEN và CHAT_ID vào .env
```

### 2.2 `utils/alert.py`

```python
"""Gửi cảnh báo qua Telegram khi pipeline gặp sự cố."""
import requests
from utils.logger import logger


def send_telegram(message: str) -> bool:
    """Gửi tin nhắn đến Telegram. Trả về True nếu thành công."""
    from config.settings import settings

    token = getattr(settings, "telegram_bot_token", None)
    chat_id = getattr(settings, "telegram_chat_id", None)

    if not token or not chat_id:
        logger.debug("[alert] Telegram chưa cấu hình, bỏ qua.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning(f"[alert] Gửi Telegram thất bại: {exc}")
        return False
```

### 2.3 `utils/alert_checker.py`

Kiểm tra `pipeline_logs` — gửi alert nếu job nào thất bại nhiều lần trong 24 giờ qua:

```python
"""Kiểm tra pipeline_logs và gửi alert khi job thất bại liên tiếp."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from db.connection import engine
from utils.alert import send_telegram
from utils.logger import logger


def check_and_alert(threshold: int = 3, window_hours: int = 24) -> None:
    """
    Gửi alert nếu bất kỳ job nào thất bại >= threshold lần trong window_hours giờ gần nhất.
    Không alert nếu Telegram chưa được cấu hình.
    """
    since = datetime.now(tz=timezone.utc) - timedelta(hours=window_hours)

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT job_name, COUNT(*) AS fail_count
                FROM pipeline_logs
                WHERE status = 'failed' AND started_at >= :since
                GROUP BY job_name
                HAVING COUNT(*) >= :threshold
                ORDER BY fail_count DESC
            """),
            {"since": since, "threshold": threshold},
        ).fetchall()

    if not rows:
        return

    lines = [f"*⚠️ Pipeline Alert* — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    lines.append(f"Job thất bại ≥ {threshold} lần trong {window_hours}h qua:\n")
    for row in rows:
        lines.append(f"  • `{row.job_name}`: *{row.fail_count} lần*")
    lines.append("\nDữ liệu trên web app có thể không được cập nhật.")

    message = "\n".join(lines)
    logger.warning(f"[alert] Phát hiện job thất bại liên tiếp: {dict(rows)}")
    send_telegram(message)
```

### 2.4 Tích hợp vào Scheduler

Thêm vào `scheduler/jobs.py` — kiểm tra mỗi giờ:

```python
from utils.alert_checker import check_and_alert

scheduler.add_job(
    _safe_run(check_and_alert, "alert_check"),
    CronTrigger(minute=0, timezone="Asia/Ho_Chi_Minh"),
    id="alert_check",
    name="Kiểm tra pipeline_logs, gửi alert Telegram nếu có sự cố",
    misfire_grace_time=300,
)
```

### 2.5 Mẫu tin nhắn

```
⚠️ Pipeline Alert — 2026-03-20 19:00
Job thất bại ≥ 3 lần trong 24h qua:

  • sync_ratios: 5 lần
  • sync_company: 3 lần

Dữ liệu trên web app có thể không được cập nhật.
```

---

## Phần 3 — Thứ tự triển khai

### Bước 1 — Docker
1. Viết `Dockerfile` — build thành công, image chạy được.
2. Viết `docker-compose.yml` với 2 services.
3. Test `docker compose up -d` — pipeline kết nối được PostgreSQL, migrations chạy tự động.
4. Test `docker compose exec pipeline python main.py sync_ratios --symbol HPG VCB FPT` — 3 mã insert thành công.
5. Kiểm tra file log xuất hiện trong `./logs/` trên máy host.
6. Tạo user `webapp_readonly` trong PostgreSQL.

### Bước 2 — Alert
1. Tạo Telegram bot, lấy token và chat_id.
2. Thêm 3 field vào `config/settings.py` (`telegram_bot_token`, `telegram_chat_id`, `alert_fail_threshold`).
3. Viết `utils/alert.py` và `utils/alert_checker.py`.
4. Test thủ công: `python -c "from utils.alert import send_telegram; send_telegram('test pipeline alert')"`.
5. Tích hợp alert_check vào `scheduler/jobs.py`.
6. Deploy lại: `docker compose up -d --build pipeline`.

---

## Phần 4 — Yêu cầu hệ thống

### Dependencies cần thêm

```txt
# Alert (thêm vào requirements.txt nếu chưa có)
requests>=2.31
```

### Cấu hình cần thêm vào `config/settings.py`

```python
# Alert
telegram_bot_token:   str = ""
telegram_chat_id:     str = ""
alert_fail_threshold: int = 3
```

### Yêu cầu VPS tối thiểu

| Thành phần | RAM | Ghi chú |
|---|---|---|
| PostgreSQL | 512 MB | Với ~10 bảng, vài triệu rows |
| Pipeline service | 256 MB | 5 luồng song song |
| **Tổng** | **~1 GB** | VPS 2 GB RAM là đủ |

> **Lưu ý:** Không có Metabase nên yêu cầu RAM thấp hơn đáng kể so với phương án ban đầu. VPS 2 GB RAM (~100,000–150,000 VND/tháng) là đủ cho cả pipeline lẫn web application backend.

---

## Phần 5 — Quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| Không có dashboard | Web app đảm nhiệm toàn bộ UI | Pipeline chỉ là data provider — không nên trùng lặp chức năng |
| Expose port 5432 | Cho web app kết nối từ ngoài | Web app là dự án riêng, không chung Docker network |
| User readonly cho web app | `webapp_readonly` chỉ có quyền SELECT | Tách biệt quyền ghi (pipeline) và đọc (web app) — nguyên tắc least privilege |
| Alert qua Telegram | Đơn giản, không cần server thêm | Đảm bảo phát hiện sự cố ảnh hưởng đến chất lượng dữ liệu web app |
| 2 services thay vì 3 | Bỏ Metabase | VPS nhỏ hơn, đơn giản hơn, phù hợp phạm vi đồ án |
