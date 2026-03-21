# Kế hoạch Giai đoạn 5 — Trading Module, Scheduler & CLI

## Tổng quan

Giai đoạn 5 hoàn thiện pipeline bằng cách bổ sung 3 thành phần còn thiếu:

| Thành phần | Mục tiêu |
|---|---|
| **Trading Module** | Lấy và lưu `ratio_summary` — snapshot tài chính mới nhất mỗi ngày |
| **APScheduler** | Tự động hóa toàn bộ 4 jobs theo lịch định kỳ |
| **CLI `main.py`** | Entry point để chạy từng job thủ công, debug, backfill |

Sau giai đoạn này, pipeline chạy hoàn toàn tự động mà không cần can thiệp thủ công.

---

## Phần 1 — Trading Module (`ratio_summary`)

### 1.1 API nguồn dữ liệu

`ratio_summary` lấy từ `vnstock_data.Company.ratio_summary()` — trả về DataFrame với các chỉ số tài chính và định giá mới nhất, được tính theo giá đóng cửa ngày gần nhất.

```python
from vnstock_data import Company

df = Company(source="vci", symbol="HPG").ratio_summary()
# Trả về: year_report, quarter_report, revenue, revenue_growth,
#          net_profit, roe, roa, pe, pb, eps, bvps, ...
```

**Lưu ý quan trọng:**
- Đây là snapshot "mới nhất" — mỗi lần gọi API trả về dữ liệu tại thời điểm hiện tại.
- Conflict key trong DB: `(symbol, year_report, quarter_report)` — khác với bảng tài chính dùng `(symbol, period, period_type)`.
- `quarter_report` có thể là `NULL` nếu là dữ liệu năm.

### 1.2 `etl/extractors/trading.py`

Kế thừa `BaseExtractor`, gọi `Company.ratio_summary()` với retry tự động.

**Trách nhiệm:**
- Gọi API và trả về DataFrame thô.
- Log số kỳ nhận được.
- Trả về `None` nếu response rỗng (giống pattern của `CompanyExtractor`).

```
TradingExtractor
    └── extract_ratio_summary(symbol) → DataFrame | None
```

### 1.3 `etl/transformers/trading.py`

Map cột từ DataFrame thô của API sang schema bảng `ratio_summary`.

**Các bước transform:**

1. **Đổi tên cột** — API có thể trả về tên cột tiếng Việt hoặc snake_case khác với schema.
2. **Thêm cột `symbol`** — API không trả về symbol, cần inject từ tham số.
3. **Ép kiểu**:
   - `year_report` → `int` (SMALLINT trong DB)
   - `quarter_report` → `int` hoặc `None` (nullable)
   - Các cột `BIGINT` (revenue, net_profit, ev, ebitda...): dùng `pd.to_numeric(..., errors='coerce')`, sau đó `fillna(pd.NA)` rồi chuyển sang `Int64` để tránh overflow như đã gặp ở Phase 3.
   - Các cột `NUMERIC` (roe, roa, pe, pb...): `float64`, để `NaN` là `None` khi insert.
4. **Xử lý `extra_metrics`**: Các cột đặc thù ngành ngân hàng (nim, npl_ratio, car, ldr) nếu có trong API response → serialize thành JSON, đưa vào cột `extra_metrics JSONB`.
5. **Loại dòng vô nghĩa**: bỏ dòng thiếu cả `year_report` lẫn `quarter_report`.
6. **`drop_duplicates`** trên `(symbol, year_report, quarter_report)` trước khi load — tránh lỗi `CardinalityViolation` ON CONFLICT đã gặp ở Phase 4.

### 1.4 `jobs/sync_ratios.py`

Chạy song song cho toàn bộ mã `STOCK` đang niêm yết, giống pattern của `sync_company.py`.

**Luồng xử lý:**

```
1. Lấy danh sách symbol từ companies WHERE status='listed' AND type='STOCK'
2. ThreadPoolExecutor(max_workers=5):
   ├── TradingExtractor.extract_ratio_summary(symbol)
   ├── TradingTransformer.transform_ratio_summary(df, symbol)
   └── PostgresLoader.load(df, 'ratio_summary', ['symbol','year_report','quarter_report'])
3. Tổng kết: Success / Failed / Skipped / Rows
```

**Xử lý lỗi:**
- Symbol không có dữ liệu (response rỗng) → `Skipped`, không ghi log error.
- Lỗi API → log warning, tiếp tục batch (không dừng toàn bộ job).

**Tham số CLI:**
```bash
python main.py sync_ratios                        # Toàn bộ mã
python main.py sync_ratios --symbol HPG VCB FPT  # Chạy cho mã cụ thể
```

---

## Phần 2 — APScheduler (`scheduler/jobs.py`)

### 2.1 Thư viện sử dụng

Dùng **APScheduler 3.x** với `BackgroundScheduler` và `CronTrigger`.

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
```

Dùng `BlockingScheduler` khi chạy như một service độc lập (process không thoát). Dùng `BackgroundScheduler` khi nhúng vào ứng dụng khác.

### 2.2 Lịch chạy 4 jobs

| Job | Trigger | Ghi chú |
|---|---|---|
| `sync_listing` | Mỗi Chủ Nhật 01:00 | Cập nhật mã mới niêm yết / hủy niêm yết |
| `sync_financials` | Mỗi 2 tuần, Thứ Hai 03:00 | Ngày 1 và 15 hàng tháng |
| `sync_company` | Mỗi Thứ Hai 02:00 | Theo dõi biến động cổ đông, lãnh đạo |
| `sync_ratios` | Hàng ngày 18:30 | Sau khi thị trường đóng cửa (HOSE đóng 15:00) |

### 2.3 Cấu trúc `scheduler/jobs.py`

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import jobs.sync_listing    as listing_job
import jobs.sync_financials as financials_job
import jobs.sync_company    as company_job
import jobs.sync_ratios     as ratios_job

def build_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")

    scheduler.add_job(listing_job.run,    CronTrigger(day_of_week="sun", hour=1,  minute=0))
    scheduler.add_job(financials_job.run, CronTrigger(day="1,15",        hour=3,  minute=0))
    scheduler.add_job(company_job.run,    CronTrigger(day_of_week="mon", hour=2,  minute=0))
    scheduler.add_job(ratios_job.run,     CronTrigger(hour=18, minute=30))

    return scheduler
```

**Lưu ý thiết kế:**
- `timezone="Asia/Ho_Chi_Minh"` — đảm bảo lịch chạy đúng giờ Việt Nam, không phụ thuộc vào timezone máy chủ.
- Mỗi job được định nghĩa trong module riêng (`jobs/`), scheduler chỉ đăng ký và kích hoạt — không chứa business logic.
- Nếu một job đang chạy mà lịch kích hoạt lần tiếp theo, APScheduler sẽ bỏ qua lần đó (`misfire_grace_time`).

### 2.4 Xử lý lỗi trong scheduler

- Wrap mỗi job trong `try/except` để lỗi của 1 job không làm crash scheduler.
- Log `ERROR` khi job thất bại để có thể alert sau (Phase 6).
- APScheduler tự động ghi log `apscheduler.executors.default` — tích hợp với logger của dự án.

---

## Phần 3 — CLI `main.py`

### 3.1 Mục đích

`main.py` là entry point duy nhất để:
- Chạy từng job thủ công (debug, kiểm tra)
- Khởi động scheduler chạy liên tục
- Backfill dữ liệu cho mã cụ thể

### 3.2 Thiết kế lệnh

Dùng thư viện `argparse` (có sẵn trong stdlib, không cần cài thêm).

```
python main.py <command> [options]
```

| Lệnh | Mô tả | Ví dụ |
|---|---|---|
| `sync_listing` | Đồng bộ danh mục mã và ngành ICB | `python main.py sync_listing` |
| `sync_financials` | Đồng bộ báo cáo tài chính | `python main.py sync_financials --symbol HPG VCB` |
| `sync_company` | Đồng bộ thông tin doanh nghiệp | `python main.py sync_company --symbol FPT` |
| `sync_ratios` | Đồng bộ ratio_summary | `python main.py sync_ratios` |
| `schedule` | Khởi động APScheduler, chạy liên tục | `python main.py schedule` |

**Tùy chọn chung:**
- `--symbol SYM1 SYM2 ...` — giới hạn chạy cho các mã cụ thể (hỗ trợ ở tất cả sync jobs).
- `--workers N` — override số luồng song song (mặc định lấy từ `settings.max_workers`).

### 3.3 Cấu trúc `main.py`

```python
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(
        description="Data Pipeline — Chứng khoán Việt Nam"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # sync_listing
    subparsers.add_parser("sync_listing")

    # sync_financials
    p_fin = subparsers.add_parser("sync_financials")
    p_fin.add_argument("--symbol", nargs="+")
    p_fin.add_argument("--workers", type=int)

    # sync_company
    p_co = subparsers.add_parser("sync_company")
    p_co.add_argument("--symbol", nargs="+")
    p_co.add_argument("--workers", type=int)

    # sync_ratios
    p_rat = subparsers.add_parser("sync_ratios")
    p_rat.add_argument("--symbol", nargs="+")
    p_rat.add_argument("--workers", type=int)

    # schedule
    subparsers.add_parser("schedule")

    args = parser.parse_args()

    if args.command == "sync_listing":
        from jobs.sync_listing import run
        run()
    elif args.command == "sync_financials":
        from jobs.sync_financials import run
        run(symbols=args.symbol, max_workers=args.workers)
    elif args.command == "sync_company":
        from jobs.sync_company import run
        run(symbols=args.symbol, max_workers=args.workers)
    elif args.command == "sync_ratios":
        from jobs.sync_ratios import run
        run(symbols=args.symbol, max_workers=args.workers)
    elif args.command == "schedule":
        from scheduler.jobs import build_scheduler
        scheduler = build_scheduler()
        print("Scheduler đang chạy. Nhấn Ctrl+C để dừng.")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            scheduler.shutdown()
            print("Scheduler đã dừng.")

if __name__ == "__main__":
    main()
```

---

## Phần 4 — Thứ tự triển khai

### Bước 1 — Trading Module (prerequisite cho scheduler)
1. Viết `etl/extractors/trading.py` — test thủ công với HPG.
2. Khám phá cột thực tế của API `ratio_summary()` để viết đúng column map.
3. Viết `etl/transformers/trading.py` — xử lý nullable, duplicate, extra_metrics.
4. Viết `jobs/sync_ratios.py` — test với 10 mã trước khi chạy toàn bộ.

### Bước 2 — Cập nhật các jobs cũ (refactor nhỏ)
Các job hiện tại (`sync_listing`, `sync_financials`, `sync_company`) cần hàm `run()` nhận tham số tùy chọn `symbols` và `max_workers` để CLI có thể gọi được:
```python
def run(symbols: list[str] | None = None, max_workers: int | None = None): ...
```

### Bước 3 — Scheduler
1. Viết `scheduler/__init__.py` (rỗng).
2. Viết `scheduler/jobs.py` với `build_scheduler()`.
3. Test bằng cách set trigger chạy sau 1 phút để kiểm tra.

### Bước 4 — CLI
1. Viết `main.py` với argparse.
2. Test từng lệnh thủ công.
3. Test `python main.py schedule` với trigger ngắn.

---

## Phần 5 — Kiểm thử

### Trading Module

| Test case | Kỳ vọng |
|---|---|
| HPG (thép, ngành thường) | Load được, không lỗi |
| VCB (ngân hàng) | Có extra_metrics (nim, npl...) hoặc None nếu API không trả |
| Mã mới niêm yết ít lịch sử | Không crash, trả về ít dòng hoặc skipped |
| Mã hủy niêm yết | Bị lọc bởi `WHERE status='listed'`, không được gọi |
| Chạy lần 2 cùng ngày | Upsert không tạo dupliate, `fetched_at` được cập nhật |

### Scheduler

| Test case | Kỳ vọng |
|---|---|
| Trigger tất cả 4 jobs | Mỗi job chạy đúng, log output rõ ràng |
| Lỗi trong 1 job | Scheduler tiếp tục, không crash |
| Ctrl+C | Shutdown graceful, không treo |

### CLI

```bash
# Kiểm tra từng lệnh
python main.py sync_listing
python main.py sync_ratios --symbol HPG VCB FPT
python main.py sync_company --symbol HPG --workers 3
python main.py --help
python main.py sync_ratios --help
```

---

## Phần 6 — Quyết định thiết kế

| Vấn đề | Quyết định | Lý do |
|---|---|---|
| `ratio_summary` lấy từ `Company` hay `Trading`? | Đặt trong `TradingExtractor` | Theo plan.md ban đầu; về mặt logic đây là chỉ số "giao dịch/định giá" cập nhật hàng ngày, không phải báo cáo định kỳ |
| Scheduler timezone | `Asia/Ho_Chi_Minh` | Tránh sai lệch khi deploy trên server cloud (UTC) |
| CLI framework | `argparse` (stdlib) | Không phát sinh dependency mới; `click` là overkill cho số lệnh hiện tại |
| `run()` signature thống nhất | `run(symbols=None, max_workers=None)` | Cho phép CLI và scheduler gọi cùng interface; `None` = dùng giá trị mặc định trong settings |
| `extra_metrics JSONB` | Serialize các cột ngân hàng vào đây | Tránh thay đổi schema chính; dễ query bằng `->` operator |
