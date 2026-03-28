"""Job đồng bộ báo cáo tài chính cho toàn bộ danh mục."""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from sqlalchemy import text

from config.constants import CONFLICT_KEYS, FINANCIAL_REPORT_TYPES, JOB_SYNC_FINANCIALS
from config.settings import settings
from db.connection import engine
from etl.extractors.finance import FinanceExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.finance_factory import FinanceParserFactory
from etl.validators.cross_source import FinanceCrossValidator
from utils.logger import logger

# Chỉ validate 3 loại BCTC chính (không validate ratio)
_VALIDATE_REPORT_TYPES = {"balance_sheet", "income_statement", "cash_flow"}


def _get_listed_symbols() -> list[str]:
    """Lấy danh sách mã chứng khoán đang niêm yết từ bảng companies."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT symbol FROM companies WHERE status = 'listed' ORDER BY symbol")
        ).fetchall()
    return [r[0] for r in rows]


def _get_icb_codes(symbols: list[str]) -> dict[str, str | None]:
    """Fetch icb_code cho tất cả symbols trong một query duy nhất."""
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
    loader: PostgresLoader,
) -> dict:
    """Chạy E→T→L cho một symbol + report_type. Trả về result dict."""
    log_id = loader.load_log(
        job_name=JOB_SYNC_FINANCIALS, symbol=symbol, status="running"
    )
    try:
        df_raw = extractor.extract(symbol, report_type=report_type)
        time.sleep(settings.request_delay)

        if df_raw.empty:
            loader.load_log(
                job_name=JOB_SYNC_FINANCIALS, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "report_type": report_type, "status": "skipped", "rows": 0}

        # Route đến parser phù hợp theo ICB Level-1
        parser = FinanceParserFactory.get_parser(icb_code, report_type)
        payloads = parser.parse(df_raw, symbol)

        if not payloads:
            loader.load_log(
                job_name=JOB_SYNC_FINANCIALS, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "report_type": report_type, "status": "skipped", "rows": 0}

        df = pd.DataFrame(payloads)
        rows = loader.load(
            df,
            "financial_reports",
            CONFLICT_KEYS["financial_reports"],
            jsonb_merge_columns=["raw_details"],
        )
        loader.load_log(
            job_name=JOB_SYNC_FINANCIALS, symbol=symbol,
            status="success", records_fetched=len(df),
            records_inserted=rows, log_id=log_id,
        )
        return {"symbol": symbol, "report_type": report_type, "status": "success", "rows": rows}

    except Exception as exc:
        logger.exception(f"[sync_financials] {symbol}/{report_type} lỗi: {exc}")
        loader.load_log(
            job_name=JOB_SYNC_FINANCIALS, symbol=symbol,
            status="failed", error_message=str(exc)[:500], log_id=log_id,
        )
        return {"symbol": symbol, "report_type": report_type, "status": "failed", "rows": 0}


def run(
    symbols: list[str] | None = None,
    report_types: list[str] | None = None,
    max_workers: int | None = None,
) -> dict:
    """
    Đồng bộ báo cáo tài chính vào bảng financial_reports.

    Args:
        symbols:      Danh sách mã cần sync. Mặc định: tất cả mã đang niêm yết từ DB.
        report_types: Loại báo cáo cần sync. Mặc định: tất cả 3 loại (BS/IS/CF).
        max_workers:  Số luồng song song. Mặc định: settings.max_workers.
    """
    symbols     = symbols or _get_listed_symbols()
    report_types = report_types or FINANCIAL_REPORT_TYPES
    max_workers = max_workers or settings.max_workers

    # Fetch icb_code một lần cho tất cả symbols để định tuyến parser
    icb_map = _get_icb_codes(symbols)

    logger.info(
        f"[sync_financials] Bắt đầu: {len(symbols)} mã × {len(report_types)} loại "
        f"({max_workers} luồng) → financial_reports."
    )

    extractor = FinanceExtractor(source=settings.vnstock_source)
    loader    = PostgresLoader()
    validator = FinanceCrossValidator()

    totals = {"success": 0, "failed": 0, "skipped": 0, "rows": 0, "flags": 0}
    tasks  = [(sym, rt) for sym in symbols for rt in report_types]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_one, sym, rt, icb_map.get(sym), extractor, loader): (sym, rt)
            for sym, rt in tasks
        }
        sym_report_done: dict[str, set] = {sym: set() for sym in symbols}

        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]

            sym = result["symbol"]
            rt  = result["report_type"]
            if result["status"] == "success" and rt in _VALIDATE_REPORT_TYPES:
                sym_report_done[sym].add(rt)

            # Khi đủ 3 loại BCTC → chạy cross-validate với KBS
            if sym_report_done[sym] == _VALIDATE_REPORT_TYPES:
                sym_report_done[sym] = set()
                try:
                    flags = validator.validate_symbol(sym)
                    totals["flags"] += flags
                except Exception as exc:
                    logger.warning(f"[sync_financials] Cross-validate {sym} lỗi: {exc}")

    logger.info(
        f"[sync_financials] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']} | "
        f"Flags={totals['flags']}"
    )
    return totals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ báo cáo tài chính.")
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Mã cần sync. Mặc định: tất cả mã đang niêm yết trong DB.",
    )
    parser.add_argument(
        "--report-types", nargs="+", default=None,
        choices=FINANCIAL_REPORT_TYPES,
        help="Loại báo cáo. Mặc định: tất cả 3 loại (balance_sheet, income_statement, cash_flow).",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Số luồng song song. Mặc định: settings.max_workers.",
    )
    args = parser.parse_args()

    result = run(
        symbols=[s.upper() for s in args.symbols] if args.symbols else None,
        report_types=args.report_types,
        max_workers=args.workers,
    )
    logger.info(f"Kết quả: {result}")
