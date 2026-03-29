# Task 8 — Kế hoạch Deprecation: financial_reports → Approach C

> **Ngày tạo:** 2026-03-28
> **Trạng thái:** Chờ xác nhận sau Task 6 (pilot) và Task 7 (full backfill)

---

## Bối cảnh

Hiện tại có 2 schema song song:

| Schema | Tables | Migration | Trạng thái |
|---|---|---|---|
| **Approach A** | `financial_reports` (1 bảng wide) | `005_financial_reports.sql` | Active (legacy) |
| **Approach C** | `fin_balance_sheet`, `fin_income_statement`, `fin_cash_flow`, `fin_financial_ratios` | `008_approach_c_schema.sql` | Active (mới) |

Approach C ưu việt hơn vì:
- Schema rõ ràng hơn, query nhanh hơn (không quét nhiều cột NULL)
- Có `fin_financial_ratios` — dữ liệu ratio lịch sử (Approach A không có)
- Bug #1 đã được fix: `_apply_mapping()` trả `None` thay vì `0.0`

---

## Điều kiện tiên quyết trước khi deprecate

Trước khi xóa `financial_reports`, cần xác nhận:

- [x] Task 6 PASS: Pilot 10 symbols đạt 11/11 quality checks ✅ 2026-03-29
- [x] Task 7 DONE: Full backfill 1,535/1,557 symbols (22 còn lại là ETF/fund — không có BCTC) ✅ 2026-03-29
- [ ] Backend Spring Boot đã migrate sang đọc từ 4 bảng mới
- [ ] Không còn query nào đọc từ `financial_reports` trong production

---

## Các bước deprecation

### Bước 1 — Dừng Approach A job (không xóa data)

Trong `scheduler/jobs.py`, comment out job `sync_financials`:

```python
# Tạm thời disable — chờ xác nhận backend đã migrate
# scheduler.add_job(
#     _safe_run(financials_job.run, "sync_financials"),
#     ...
# )
```

Cron `CRON_SYNC_FINANCIALS` trong `.env` cũng có thể set thành giá trị không chạy:
```
CRON_SYNC_FINANCIALS=0 3 31 2 *    # 31 tháng 2 — không bao giờ chạy
```

### Bước 2 — Thông báo cho Backend team

Các bảng Spring Boot cần cập nhật:

| Entity cũ (Approach A) | Entity mới (Approach C) |
|---|---|
| `FinancialReport` → `financial_reports` | `FinBalanceSheet` → `fin_balance_sheet` |
| | `FinIncomeStatement` → `fin_income_statement` |
| | `FinCashFlow` → `fin_cash_flow` |
| | `FinancialRatio` (mới) → `fin_financial_ratios` |

Conflict key thay đổi:
- Approach A: `(symbol, period, period_type, statement_type)`
- Approach C: `(symbol, period, period_type)` — mỗi bảng đã chứa 1 statement type

### Bước 3 — Tạo migration drop

✅ **Đã tạo:** `db/migrations/010_drop_financial_reports.sql`

File đã được tạo sẵn ngày 2026-03-29. **CHƯA APPLY** — chờ backend xác nhận.

Khi backend sẵn sàng, chạy: `python -m db.migrate`

### Bước 4 — Dọn dẹp code

Các file có thể xóa sau khi deprecate:

```
jobs/sync_financials.py          → DELETE (Approach A job)
etl/validators/cross_source.py   → REVIEW (chỉ dùng cho sync_financials)
```

Xóa khỏi `config/constants.py`:
```python
# "financial_reports": ["symbol", "period", "period_type", "statement_type"],
```

Xóa khỏi `scheduler/jobs.py`:
```python
# import jobs.sync_financials as financials_job
# scheduler.add_job(sync_financials ...)
```

---

## Timeline gợi ý

| Giai đoạn | Mốc | Điều kiện |
|---|---|---|
| **Hiện tại** | 2026-03-28 | Approach C tables mới, chạy song song |
| **Pilot verify** | +1 ngày | Task 6 chạy và pass 8 checks |
| **Full backfill** | +1 tuần | Task 7 backfill ~1,800 symbols xong |
| **Backend migrate** | +2 tuần | Spring Boot đọc từ 4 bảng mới |
| **Disable Approach A** | +3 tuần | Dừng sync_financials.py |
| **Drop table** | +1 tháng | Xác nhận production OK 1 tuần sau khi disable |

---

## Rollback plan

Nếu phát hiện vấn đề sau khi drop:
1. Approach C data vẫn còn nguyên (không bị ảnh hưởng)
2. Restore từ DB backup (Docker volume): `docker cp postgres:/var/lib/postgresql/data backup/`
3. Re-run `005_financial_reports.sql` để tạo lại bảng
4. Re-run `jobs/sync_financials.py --full-history` để backfill lại

*Nhưng nếu Approach C data đã đầy đủ, không cần restore Approach A.*
