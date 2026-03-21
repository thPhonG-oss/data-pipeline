# CLAUDE.md — Data Pipeline Project Context

> Tài liệu này dùng để cung cấp context cho Claude Code trong các session tiếp theo.
> Cập nhật: 2026-03-21

---

## Tổng quan dự án

**Pipeline dữ liệu chứng khoán Việt Nam** — Lấy dữ liệu từ vnstock/vnstock_data → PostgreSQL (`stockapp`, localhost:5432).

Ngôn ngữ: Python 3.11+. Framework: pydantic-settings, SQLAlchemy, APScheduler, pandas.

---

## Cấu trúc thư mục

```
data-pipeline/
├── config/
│   ├── settings.py        # Pydantic BaseSettings — đọc từ .env
│   └── constants.py       # JOB_* constants, CONFLICT_KEYS dict
├── db/
│   ├── connection.py      # SQLAlchemy engine
│   └── migrations/        # 001–004 SQL files (đã chạy)
├── etl/
│   ├── base/              # BaseExtractor, BaseTransformer
│   ├── extractors/        # listing, finance, company, trading (+ dnse_price, vndirect_price sắp thêm)
│   ├── transformers/      # tương ứng
│   ├── loaders/
│   │   └── postgres.py    # PostgresLoader — upsert via INSERT ... ON CONFLICT DO UPDATE
│   └── validators/        # (sắp thêm) cross_source.py cho Phase 7B
├── jobs/                  # sync_listing, sync_financials, sync_company, sync_ratios (+ sync_prices sắp thêm)
├── scheduler/
│   └── jobs.py            # APScheduler BlockingScheduler — 5 jobs (sắp thêm sync_prices)
├── utils/
│   ├── logger.py          # loguru
│   ├── retry.py           # vnstock_retry decorator (tenacity)
│   ├── alert.py           # Telegram alert
│   └── alert_checker.py   # Kiểm tra pipeline_logs, gửi alert
├── main.py                # CLI argparse entry point
├── .env                   # Credentials thật (không commit)
└── .env.example           # Template
```

---

## Trạng thái các Phase

| Phase | Trạng thái | Mô tả |
|---|---|---|
| **Phase 1** | ✅ Hoàn thành | DB migrations (001–004), config, ETL base, PostgresLoader, utils |
| **Phase 2** | ✅ Hoàn thành | Listing module — icb_industries + companies |
| **Phase 3** | ✅ Hoàn thành | Finance module — balance_sheets, income_statements, cash_flows, financial_ratios |
| **Phase 4** | ✅ Hoàn thành | Company module — shareholders, officers, subsidiaries, corporate_events |
| **Phase 5** | ✅ Hoàn thành | Trading module (ratio_summary) + APScheduler + CLI |
| **Phase 6** | ✅ Hoàn thành | Docker, .env config, deploy docs, alert system, cron via .env |
| **Phase 7** | 🔄 Thiết kế xong, chưa implement | Mở rộng nguồn dữ liệu (xem chi tiết bên dưới) |

---

## Kế hoạch Phase 7 — Mở rộng nguồn dữ liệu

Tài liệu đầy đủ: `docs/phase7_tcbs_implementation.md`

### Phase 7A — Giá lịch sử OHLCV

**Nguồn chính: DNSE LightSpeed API** (người dùng đã có tài khoản DNSE)
- Dùng qua vnstock: `Quote(symbol='HPG', source='DNSE').history(start=..., end=..., interval='1D')`
- vnstock xử lý JWT auth nội bộ
- Feed trực tiếp từ sàn, lịch sử daily 10 năm, intraday 1m/1H/1D/W

**Fallback: VNDirect finfo-api** (public, không cần auth)
- `GET https://finfo-api.vndirect.com.vn/v4/stock_prices/?q=code:HPG~date:gte:...`
- Có `adClose` (adjusted close) — DNSE không có
- Fallback tự động trong `jobs/sync_prices.py` khi DNSE lỗi

**Lưu ý quan trọng khi implement:**
- Kiểm tra đơn vị giá vnstock DNSE: VND nguyên hay nghìn VND? Set `_NEEDS_SCALE` trong transformer
- `close_adj` = NULL cho source='dnse' (DNSE không cung cấp adjusted close)
- DNSE credentials: `DNSE_USERNAME`, `DNSE_PASSWORD` trong `.env`

**Files cần tạo (Phase 7A):**
- `etl/extractors/dnse_price.py` — DNSEPriceExtractor
- `etl/extractors/vndirect_price.py` — VNDirectPriceExtractor (fallback)
- `etl/transformers/dnse_price.py` — DNSEPriceTransformer
- `etl/transformers/vndirect_price.py` — VNDirectPriceTransformer (fallback)
- `jobs/sync_prices.py` — DNSE primary + auto-fallback VNDirect
- `db/migrations/005_price_history.sql`

**Files cần sửa (Phase 7A):**
- `config/constants.py` — thêm `JOB_SYNC_PRICES`, `CONFLICT_KEYS["price_history"]`
- `config/settings.py` — thêm `dnse_username`, `dnse_password`, `cron_sync_prices`
- `scheduler/jobs.py` — thêm job `sync_prices` (cron: `0 19 * * 1-5`)
- `main.py` — thêm CLI subcommand `sync_prices`
- `.env.example` — thêm `DNSE_USERNAME`, `DNSE_PASSWORD`, `CRON_SYNC_PRICES`

### Phase 7B — Cross-Validation BCTC

**Mục tiêu:** So sánh VCI (đang trong DB) với KBS (fetch qua vnstock) để phát hiện dữ liệu BCTC bất thường.

**Files cần tạo (Phase 7B):**
- `etl/validators/__init__.py` — file rỗng
- `etl/validators/cross_source.py` — FinanceCrossValidator (ngưỡng 2%)
- `db/migrations/006_data_quality.sql` — bảng `data_quality_flags`

**Files cần sửa (Phase 7B):**
- `jobs/sync_financials.py` — gọi validator sau khi load BCTC xong

---

## Các quyết định thiết kế quan trọng

### Settings & Config
- Tất cả config đọc từ `.env` qua `pydantic-settings BaseSettings`
- Cron expressions dạng Unix 5-field, đọc từ `.env` (e.g. `CRON_SYNC_RATIOS="30 18 * * *"`)
- `CronTrigger.from_crontab(settings.cron_sync_*)` trong scheduler/jobs.py

### PostgresLoader
- Dùng `INSERT ... ON CONFLICT DO UPDATE` (upsert) cho tất cả bảng
- `conflict_columns` xác định unique key per table
- Batch insert theo `db_chunk_size` (mặc định 500)

### Incremental sync (Phase 7A)
- Mỗi run query `MAX(date)` per symbol từ DB
- Chỉ fetch từ ngày cuối + 1 ngày
- Lần đầu (NULL): fetch 5 năm lịch sử

### TCBS — ĐÃ BỊ XÓA
- TCBS bị xóa khỏi vnstock v3.5.0 (tháng 3/2026) — yêu cầu JWT từ TCInvest app
- **Không dùng TCBS** cho bất kỳ mục đích nào

### Ctrl+C khi chạy scheduler
- `BlockingScheduler.shutdown(wait=True)` mặc định — chờ threads xong
- Phải Ctrl+C hai lần hoặc dùng `shutdown(wait=False)` để thoát ngay

### APScheduler timezone
- Tất cả jobs dùng `timezone="Asia/Ho_Chi_Minh"`

---

## Nguồn dữ liệu hiện tại

| Nguồn | Dùng cho | Auth | Ghi chú |
|---|---|---|---|
| **VCI (Vietcap)** | Listing, Finance, Company, Trading (hiện tại) | Không (browser headers) | Qua vnstock_data |
| **DNSE** | Giá OHLCV (Phase 7A primary) | JWT — cần account | Qua vnstock Quote |
| **VNDirect** | Giá OHLCV (Phase 7A fallback) | Không | REST public |
| **KBS** | BCTC cross-validation (Phase 7B) | Không | Qua vnstock Finance |

---

## Docs quan trọng

| File | Nội dung |
|---|---|
| `docs/pipeline_guide.md` | Hướng dẫn đầy đủ pipeline, settings, cấu trúc bảng |
| `docs/deploy_plan.md` | Kế hoạch deploy lên VPS/Docker (Vietnamese) |
| `docs/phase7_tcbs_implementation.md` | Thiết kế chi tiết Phase 7 (DNSE + VNDirect + KBS cross-val) |
| `docs/data_source_strategy.md` | Phân tích chiến lược nguồn dữ liệu |
| `docs/cron_config_design.md` | Thiết kế cron expressions qua .env |

---

## Lệnh hay dùng

```bash
# Chạy từng job thủ công
python main.py sync_listing
python main.py sync_financials
python main.py sync_company
python main.py sync_ratios

# Chạy scheduler (blocking)
python main.py schedule

# Phase 7A (sau khi implement)
python main.py sync_prices --symbol HPG VCB FPT   # test 3 mã
python main.py sync_prices --full-history           # initial load ~1h

# Docker
docker compose up -d
docker compose exec postgres psql -U postgres -d stockapp
```
