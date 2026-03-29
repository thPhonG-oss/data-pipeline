"""
Job đồng bộ báo cáo tài chính theo Approach C — 4 bảng riêng biệt.

Khác biệt so với sync_financials.py (Approach A):
    - Sync thêm "ratio" (fin_financial_ratios) — MỚI
    - Load vào fin_balance_sheet / fin_income_statement / fin_cash_flow / fin_financial_ratios
    - _apply_mapping() đã được fix: None thay vì 0.0 khi cột không có

Cách dùng:
    python -m jobs.sync_financials_c
    python -m jobs.sync_financials_c --symbols HPG VCB SSI BVH
    python -m jobs.sync_financials_c --report-types ratio
"""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from sqlalchemy import text

from config.constants import (
    FINANCIAL_REPORT_TYPES,
    JOB_SYNC_FINANCIALS_C,
)
from config.settings import settings
from db.connection import engine
from etl.extractors.finance import FinanceExtractor
from etl.loaders.approach_c_loader import ApproachCLoader
from etl.loaders.postgres import PostgresLoader
from etl.transformers.approach_c.factory import ApproachCFactory
from utils.logger import logger

# 4 loại bao gồm ratio (Approach A chỉ có 3)
_ALL_REPORT_TYPES = [*FINANCIAL_REPORT_TYPES, "ratio"]


def _get_listed_symbols() -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT symbol FROM companies WHERE status = 'listed' ORDER BY symbol")
        ).fetchall()
    return [r[0] for r in rows]


def _get_icb_codes(symbols: list[str]) -> dict[str, str | None]:
    if not symbols:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT symbol, icb_code FROM companies WHERE symbol = ANY(:syms)"),
            {"syms": symbols},
        ).fetchall()
    return {r[0]: r[1] for r in rows}


def _run_one(
    symbol: str,
    report_type: str,
    icb_code: str | None,
    extractor: FinanceExtractor,
    approach_c_loader: ApproachCLoader,
    pg_loader: PostgresLoader,
) -> dict:
    """E→T→L cho 1 symbol + report_type vào bảng Approach C."""
    log_id = pg_loader.load_log(
        job_name=JOB_SYNC_FINANCIALS_C, symbol=symbol, status="running"
    )
    try:
        df_raw = extractor.extract(symbol, report_type=report_type)
        time.sleep(settings.request_delay)

        if df_raw.empty:
            pg_loader.load_log(
                job_name=JOB_SYNC_FINANCIALS_C, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "report_type": report_type, "status": "skipped", "rows": 0}

        payloads, table = ApproachCFactory.parse(
            df=df_raw,
            symbol=symbol,
            statement_type=report_type,
            icb_code=icb_code,
        )

        if not payloads:
            pg_loader.load_log(
                job_name=JOB_SYNC_FINANCIALS_C, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "report_type": report_type, "status": "skipped", "rows": 0}

        rows = approach_c_loader.load(payloads, statement_type=report_type)
        pg_loader.load_log(
            job_name=JOB_SYNC_FINANCIALS_C, symbol=symbol,
            status="success", records_fetched=len(payloads),
            records_inserted=rows, log_id=log_id,
        )
        return {"symbol": symbol, "report_type": report_type, "status": "success", "rows": rows}

    except Exception as exc:
        logger.exception(f"[sync_financials_c] {symbol}/{report_type} lỗi: {exc}")
        pg_loader.load_log(
            job_name=JOB_SYNC_FINANCIALS_C, symbol=symbol,
            status="failed", error_message=str(exc)[:500], log_id=log_id,
        )
        return {"symbol": symbol, "report_type": report_type, "status": "failed", "rows": 0}


def run(
    symbols: list[str] | None = None,
    report_types: list[str] | None = None,
    max_workers: int | None = None,
) -> dict:
    """
    Đồng bộ BCTC + ratio vào 4 bảng Approach C.

    Args:
        symbols:      Mặc định: tất cả mã đang niêm yết.
        report_types: Mặc định: balance_sheet, income_statement, cash_flow, ratio.
        max_workers:  Mặc định: settings.max_workers.
    """
    symbols      = symbols or _get_listed_symbols()
    report_types = report_types or _ALL_REPORT_TYPES
    max_workers  = max_workers or settings.max_workers

    icb_map = _get_icb_codes(symbols)

    logger.info(
        f"[sync_financials_c] Bắt đầu: {len(symbols)} mã × {len(report_types)} loại "
        f"({max_workers} luồng) → Approach C tables."
    )

    extractor      = FinanceExtractor(source=settings.vnstock_source)
    approach_c_ldr = ApproachCLoader()
    pg_ldr         = PostgresLoader()

    totals = {"success": 0, "failed": 0, "skipped": 0, "rows": 0}
    tasks  = [(sym, rt) for sym in symbols for rt in report_types]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one, sym, rt, icb_map.get(sym), extractor, approach_c_ldr, pg_ldr
            ): (sym, rt)
            for sym, rt in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]

    logger.info(
        f"[sync_financials_c] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']}"
    )
    return totals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ BCTC Approach C (4 bảng riêng).")
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Mã cần sync. Mặc định: tất cả mã đang niêm yết.",
    )
    parser.add_argument(
        "--report-types", nargs="+", default=None,
        choices=_ALL_REPORT_TYPES,
        help=f"Loại báo cáo. Mặc định: {_ALL_REPORT_TYPES}",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Số luồng. Mặc định: settings.max_workers.",
    )
    args = parser.parse_args()

    result = run(
        symbols=[s.upper() for s in args.symbols] if args.symbols else None,
        report_types=args.report_types,
        max_workers=args.workers,
    )
    logger.info(f"Kết quả: {result}")
