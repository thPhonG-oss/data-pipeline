"""
verify_hsx_company.py — Kiểm tra kết quả sync từ HSX API vào bảng companies.

Checks:
  1. Tổng số HOSE symbols trong companies
  2. Số symbols đã có brief / phone / address / web_url
  3. Tỷ lệ fill (%) cho từng cột mới
  4. Top 10 mẫu records với đủ dữ liệu
  5. Symbols HOSE thiếu dữ liệu (brief IS NULL)
  6. Kiểm tra pipeline_logs — log gần nhất của job sync_hsx_company

Output: in ra console + ghi vào docs/hsx_company_verify_results.md
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import text

# Đảm bảo import từ root dự án
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.connection import engine  # noqa: E402
from utils.logger import logger   # noqa: E402

_DOCS_DIR   = Path(__file__).resolve().parents[1] / "docs"
_OUTPUT_FILE = _DOCS_DIR / "hsx_company_verify_results.md"
_NEW_COLS   = ["brief", "phone", "fax", "address", "web_url"]


def run_checks() -> dict:
    """Chạy tất cả checks, trả về dict kết quả."""
    results: dict = {}

    with engine.connect() as conn:
        # ── 1. Tổng HOSE ──────────────────────────────────────────────────────
        total_hose = conn.execute(text(
            "SELECT COUNT(*) FROM companies WHERE exchange = 'HOSE'"
        )).scalar()
        results["total_hose"] = total_hose

        # ── 2. Fill rate cho từng cột mới ─────────────────────────────────────
        fill_stats: dict[str, int] = {}
        for col in _NEW_COLS:
            count = conn.execute(text(
                f"SELECT COUNT(*) FROM companies "
                f"WHERE exchange = 'HOSE' AND {col} IS NOT NULL AND {col} <> ''"
            )).scalar()
            fill_stats[col] = count
        results["fill_stats"] = fill_stats

        # ── 3. Sample records đã có đủ dữ liệu ───────────────────────────────
        rows = conn.execute(text("""
            SELECT symbol, company_name, brief, phone, address, web_url
            FROM companies
            WHERE exchange = 'HOSE'
              AND brief IS NOT NULL
            ORDER BY symbol
            LIMIT 10
        """)).fetchall()
        results["sample"] = [dict(r._mapping) for r in rows]

        # ── 4. Symbols thiếu brief (HSX không trả về hoặc chưa sync) ─────────
        missing_rows = conn.execute(text("""
            SELECT symbol, company_name
            FROM companies
            WHERE exchange = 'HOSE'
              AND brief IS NULL
            ORDER BY symbol
        """)).fetchall()
        results["missing_brief"] = [dict(r._mapping) for r in missing_rows]

        # ── 5. Log gần nhất của job sync_hsx_company ──────────────────────────
        log_row = conn.execute(text("""
            SELECT id, status, records_fetched, records_inserted,
                   started_at, finished_at, error_message
            FROM pipeline_logs
            WHERE job_name = 'sync_hsx_company'
            ORDER BY started_at DESC
            LIMIT 1
        """)).fetchone()
        results["last_log"] = dict(log_row._mapping) if log_row else None

    return results


def format_report(results: dict) -> str:
    """Tạo Markdown report từ kết quả checks."""
    now       = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total     = results["total_hose"]
    fill      = results["fill_stats"]

    lines: list[str] = []
    lines += [
        f"# HSX Company Sync — Verify Results",
        f"",
        f"**Generated:** {now}",
        f"**Source:** `api.hsx.vn/l/api/v1/1/securities/stock`",
        f"",
        f"---",
        f"",
        f"## 1. Tổng quan",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| HOSE symbols trong DB | **{total:,}** |",
    ]

    for col in _NEW_COLS:
        cnt  = fill.get(col, 0)
        pct  = (cnt / total * 100) if total else 0.0
        lines.append(f"| `{col}` filled | **{cnt:,}** ({pct:.1f}%) |")

    lines += ["", "---", "", "## 2. Pipeline Log (lần chạy gần nhất)", ""]
    log = results.get("last_log")
    if log:
        lines += [
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Status | `{log['status']}` |",
            f"| Records fetched | {log['records_fetched']:,} |",
            f"| Records upserted | {log['records_inserted']:,} |",
            f"| Started at | {log['started_at']} |",
            f"| Finished at | {log['finished_at']} |",
        ]
        if log.get("error_message"):
            lines.append(f"| Error | `{log['error_message']}` |")
    else:
        lines.append("_(Chưa có log — job chưa chạy lần nào)_")

    # ── Sample records ────────────────────────────────────────────────────────
    lines += ["", "---", "", "## 3. Sample records (10 mã đầu đã có brief)", ""]
    sample = results.get("sample", [])
    if sample:
        lines.append("| symbol | company_name | brief | phone | web_url |")
        lines.append("|--------|-------------|-------|-------|---------|")
        for r in sample:
            sym  = r.get("symbol", "")
            name = (r.get("company_name") or "")[:40]
            brief = (r.get("brief") or "")[:30]
            phone = (r.get("phone") or "")[:20]
            web   = (r.get("web_url") or "")[:35]
            lines.append(f"| {sym} | {name} | {brief} | {phone} | {web} |")
    else:
        lines.append("_(Chưa có dữ liệu)_")

    # ── Missing brief ─────────────────────────────────────────────────────────
    missing = results.get("missing_brief", [])
    lines += ["", "---", "", f"## 4. HOSE symbols thiếu brief ({len(missing)} mã)", ""]
    if missing:
        lines.append("| symbol | company_name |")
        lines.append("|--------|-------------|")
        for r in missing[:50]:
            lines.append(f"| {r['symbol']} | {r.get('company_name', '')} |")
        if len(missing) > 50:
            lines.append(f"| _(và {len(missing) - 50} mã khác...)_ | |")
    else:
        lines.append("**Tất cả HOSE symbols đã có brief.**")

    return "\n".join(lines) + "\n"


def main() -> None:
    logger.info("[verify_hsx_company] Đang kiểm tra...")
    results = run_checks()
    report  = format_report(results)

    # In ra console
    print(report)

    # Ghi vào docs/
    _DOCS_DIR.mkdir(parents=True, exist_ok=True)
    _OUTPUT_FILE.write_text(report, encoding="utf-8")
    logger.info(f"[verify_hsx_company] Kết quả đã lưu: {_OUTPUT_FILE}")


if __name__ == "__main__":
    main()
