"""Job đồng bộ báo cáo tài chính cho toàn bộ danh mục."""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text

from config.constants import CONFLICT_KEYS, FINANCIAL_REPORT_TYPES, JOB_SYNC_FINANCIALS
from config.settings import settings
from db.connection import engine
from etl.extractors.finance import FinanceExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.finance import FinanceTransformer
from utils.logger import logger

_TABLE_MAP = {
    "balance_sheet":    "balance_sheets",
    "income_statement": "income_statements",
    "cash_flow":        "cash_flows",
    "ratio":            "financial_ratios",
}


def _get_listed_symbols() -> list[str]:
    """Lấy danh sách mã chứng khoán đang niêm yết từ bảng companies."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT symbol FROM companies WHERE status = 'listed' ORDER BY symbol")
        ).fetchall()
    return [r[0] for r in rows]


def _run_one(
    symbol: str,
    report_type: str,
    extractor: FinanceExtractor,
    transformer: FinanceTransformer,
    loader: PostgresLoader,
) -> dict:
    """Chạy E→T→L cho một symbol + report_type. Trả về result dict."""
    table = _TABLE_MAP[report_type]
    log_id = loader.load_log(
        job_name=JOB_SYNC_FINANCIALS, symbol=symbol, status="running"
    )
    try:
        df_raw = extractor.extract(symbol, report_type=report_type)
        time.sleep(settings.request_delay)

        df = transformer.transform(df_raw, symbol, report_type=report_type)
        if df.empty:
            loader.load_log(
                job_name=JOB_SYNC_FINANCIALS, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "report_type": report_type, "status": "skipped", "rows": 0}

        rows = loader.load(df, table, CONFLICT_KEYS[table])
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
    Đồng bộ báo cáo tài chính vào PostgreSQL.

    Args:
        symbols:      Danh sách mã cần sync. Mặc định: tất cả mã đang niêm yết từ DB.
        report_types: Loại báo cáo cần sync. Mặc định: tất cả 4 loại.
        max_workers:  Số luồng song song. Mặc định: settings.max_workers.
    """
    symbols = symbols or _get_listed_symbols()
    report_types = report_types or FINANCIAL_REPORT_TYPES
    max_workers = max_workers or settings.max_workers

    logger.info(
        f"[sync_financials] Bắt đầu: {len(symbols)} mã × {len(report_types)} loại báo cáo "
        f"({max_workers} luồng)."
    )

    extractor = FinanceExtractor(source=settings.vnstock_source)
    transformer = FinanceTransformer()
    loader = PostgresLoader()

    totals = {"success": 0, "failed": 0, "skipped": 0, "rows": 0}

    # Tạo danh sách tất cả tasks: (symbol, report_type)
    tasks = [(sym, rt) for sym in symbols for rt in report_types]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_one, sym, rt, extractor, transformer, loader): (sym, rt)
            for sym, rt in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]

    logger.info(
        f"[sync_financials] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']}"
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
        help="Loại báo cáo. Mặc định: tất cả 4 loại.",
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
