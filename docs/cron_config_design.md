# Thiết kế — Cấu hình lịch chạy Cron qua `.env`

> **Trạng thái:** Đề xuất — chờ xác nhận trước khi chỉnh code
> **Phạm vi:** `config/settings.py`, `scheduler/jobs.py`, `.env.example`

---

## 1. Vấn đề hiện tại

Lịch chạy của 5 jobs đang được **hard-code** trực tiếp trong `scheduler/jobs.py`:

```python
# scheduler/jobs.py — hiện tại
CronTrigger(day_of_week="sun", hour=1, minute=0, ...)   # sync_listing
CronTrigger(day="1,15", hour=3, minute=0, ...)           # sync_financials
CronTrigger(day_of_week="mon", hour=2, minute=0, ...)    # sync_company
CronTrigger(hour=18, minute=30, ...)                     # sync_ratios
CronTrigger(minute=0, ...)                               # alert_check
```

**Hậu quả:** Muốn đổi giờ chạy (ví dụ: `sync_ratios` chạy lúc 19:00 thay vì 18:30) phải **sửa code → rebuild Docker image → restart container**. Không thể đổi lịch chỉ bằng cách chỉnh `.env`.

---

## 2. Mục tiêu

Cho phép thay đổi lịch chạy **chỉ bằng cách chỉnh `.env`**, không cần sửa code hay rebuild image:

```env
# .env
CRON_SYNC_RATIOS="30 18 * * *"   # → đổi thành 19:00 chỉ cần: CRON_SYNC_RATIOS="0 19 * * *"
```

---

## 3. Phân tích cách tiếp cận

### Cách A — Tách từng field riêng

Mỗi tham số của `CronTrigger` thành một biến env riêng:

```env
CRON_LISTING_DAY_OF_WEEK=sun
CRON_LISTING_HOUR=1
CRON_LISTING_MINUTE=0

CRON_FINANCIALS_DAY=1,15
CRON_FINANCIALS_HOUR=3
CRON_FINANCIALS_MINUTE=0
```

**Ưu điểm:** Rõ ràng từng tham số, dễ validate riêng lẻ.
**Nhược điểm:** Quá nhiều biến (~15 biến cho 5 jobs), dễ nhầm, không quen thuộc.

### Cách B — Chuỗi cron tiêu chuẩn ✓ (khuyến nghị)

Mỗi job dùng **1 biến env** chứa chuỗi cron 5 field theo chuẩn Unix:

```env
CRON_SYNC_LISTING="0 1 * * 0"       # Chủ Nhật 01:00
CRON_SYNC_FINANCIALS="0 3 1,15 * *" # Ngày 1 & 15 hàng tháng 03:00
CRON_SYNC_COMPANY="0 2 * * 1"       # Thứ Hai 02:00
CRON_SYNC_RATIOS="30 18 * * *"      # Hàng ngày 18:30
CRON_ALERT_CHECK="0 * * * *"        # Hàng giờ :00
```

**Ưu điểm:**
- 5 biến cho 5 jobs — gọn, nhất quán
- Chuỗi cron là chuẩn công nghiệp — dễ hiểu với ai đã biết Linux cron
- APScheduler hỗ trợ trực tiếp: `CronTrigger.from_crontab("30 18 * * *")` — không cần parse thủ công
- Dễ kiểm tra online (crontab.guru)

**Nhược điểm:**
- Người không biết cron syntax có thể điền sai — cần note rõ trong `.env.example`

> **Quyết định:** Dùng **Cách B** (chuỗi cron tiêu chuẩn).

---

## 4. Định dạng chuỗi cron

```
┌───────── phút       (0–59)
│ ┌─────── giờ        (0–23)
│ │ ┌───── ngày/tháng (1–31, hoặc "1,15")
│ │ │ ┌─── tháng      (1–12)
│ │ │ │ ┌─ ngày/tuần  (0=CN, 1=T2, ..., 6=T7)
│ │ │ │ │
* * * * *
```

| Lịch muốn | Chuỗi cron |
|---|---|
| Hàng ngày 18:30 | `30 18 * * *` |
| Chủ Nhật 01:00 | `0 1 * * 0` |
| Thứ Hai 02:00 | `0 2 * * 1` |
| Ngày 1 & 15, 03:00 | `0 3 1,15 * *` |
| Mỗi giờ đầu | `0 * * * *` |

Kiểm tra cú pháp tại: **crontab.guru**

---

## 5. Thay đổi cần thực hiện

### 5.1 `config/settings.py` — thêm section Scheduler

```python
# ── Scheduler (cron expressions — chuẩn Unix 5-field) ────────────
cron_sync_listing:    str = "0 1 * * 0"       # Chủ Nhật 01:00
cron_sync_financials: str = "0 3 1,15 * *"    # Ngày 1 & 15 hàng tháng 03:00
cron_sync_company:    str = "0 2 * * 1"        # Thứ Hai 02:00
cron_sync_ratios:     str = "30 18 * * *"      # Hàng ngày 18:30
cron_alert_check:     str = "0 * * * *"        # Hàng giờ :00
```

Pydantic-settings tự đọc từ `.env` theo tên biến (case-insensitive):
- `cron_sync_listing` ↔ `CRON_SYNC_LISTING=...`

### 5.2 `scheduler/jobs.py` — đọc từ settings thay vì hard-code

**Trước:**
```python
scheduler.add_job(
    _safe_run(ratios_job.run, "sync_ratios"),
    CronTrigger(hour=18, minute=30, timezone="Asia/Ho_Chi_Minh"),
    id="sync_ratios",
    misfire_grace_time=1800,
)
```

**Sau:**
```python
from config.settings import settings
from apscheduler.triggers.cron import CronTrigger

scheduler.add_job(
    _safe_run(ratios_job.run, "sync_ratios"),
    CronTrigger.from_crontab(settings.cron_sync_ratios, timezone="Asia/Ho_Chi_Minh"),
    id="sync_ratios",
    misfire_grace_time=1800,
)
```

Thay đổi tương tự cho tất cả 5 jobs.

### 5.3 `.env.example` — thêm section Scheduler

```env
# ── Scheduler (cron expressions) ──────────────────────────────────
# Format: "phút giờ ngày/tháng tháng ngày/tuần"  (chuẩn Unix 5-field)
# Kiểm tra cú pháp tại: crontab.guru
#
CRON_SYNC_LISTING="0 1 * * 0"        # Chủ Nhật 01:00
CRON_SYNC_FINANCIALS="0 3 1,15 * *"  # Ngày 1 & 15 hàng tháng 03:00
CRON_SYNC_COMPANY="0 2 * * 1"        # Thứ Hai 02:00
CRON_SYNC_RATIOS="30 18 * * *"       # Hàng ngày 18:30
CRON_ALERT_CHECK="0 * * * *"         # Hàng giờ :00
```

---

## 6. Cách dùng sau khi thay đổi

### Thay đổi giờ chạy (không cần rebuild)

```env
# .env — đổi sync_ratios từ 18:30 sang 19:00
CRON_SYNC_RATIOS="0 19 * * *"
```

```bash
# Chỉ cần restart container — không rebuild image
docker compose restart pipeline
```

### Tăng tần suất sync financials (ví dụ: mỗi tuần thay vì 2 lần/tháng)

```env
CRON_SYNC_FINANCIALS="0 3 * * 0"   # Mỗi Chủ Nhật 03:00
```

### Test ngay lập tức (chạy sau 2 phút kể từ bây giờ — dùng khi debug)

```env
# Ví dụ: hiện tại là 14:22 → đặt 14:24 để trigger ngay
CRON_SYNC_RATIOS="24 14 * * *"
# → Sau khi kiểm tra xong, đổi lại giá trị mặc định
```

---

## 7. Xử lý chuỗi cron không hợp lệ

`CronTrigger.from_crontab()` sẽ **raise `ValueError`** ngay khi `build_scheduler()` được gọi nếu chuỗi cron không hợp lệ. Pipeline sẽ không khởi động được và log báo lỗi rõ ràng — tốt hơn là chạy với lịch sai.

**Ví dụ lỗi:**
```
ValueError: The trigger "cron" does not support field "day_of_month" with value "32"
```

Cách kiểm tra trước khi deploy:

```bash
# Kiểm tra thủ công trên local
python -c "
from apscheduler.triggers.cron import CronTrigger
CronTrigger.from_crontab('30 18 * * *')
print('OK')
"
```

---

## 8. Những gì KHÔNG thay đổi

| Thứ | Lý do giữ nguyên |
|---|---|
| `misfire_grace_time` | Giá trị này phụ thuộc tính chất job (sync_ratios quan trọng theo phiên, alert_check nhẹ) — không cần tune thường xuyên |
| `timezone="Asia/Ho_Chi_Minh"` | Cố định theo yêu cầu thị trường Việt Nam — không nên thay đổi |
| Tên job ID (`sync_listing`, v.v.) | Dùng làm khoá trong `pipeline_logs` — đổi tên phá vỡ lịch sử log |

---

## 9. Tóm tắt thay đổi

| File | Loại thay đổi | Chi tiết |
|---|---|---|
| `config/settings.py` | Thêm 5 field | `cron_sync_*`, `cron_alert_check` — string, có default |
| `scheduler/jobs.py` | Sửa 5 `CronTrigger(...)` | → `CronTrigger.from_crontab(settings.cron_*)` |
| `.env.example` | Thêm section | 5 biến `CRON_SYNC_*` với giá trị mặc định và comment |

Không cần thay đổi: `main.py`, `jobs/`, `utils/`, `db/`, migrations, Dockerfile, docker-compose.yml.

---

*Xác nhận thiết kế này trước khi bắt đầu chỉnh code.*
