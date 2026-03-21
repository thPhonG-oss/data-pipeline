"""Job đồng bộ ratio_summary — snapshot tài chính mới nhất, chạy hàng ngày."""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text

from config.constants import CONFLICT_KEYS, JOB_SYNC_RATIOS
from config.settings import settings
from db.connection import engine
from etl.extractors.trading import TradingExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.trading import TradingTransformer
from utils.logger import logger


def _get_listed_symbols() -> list[str]:
    """Lấy danh sách mã STOCK đang niêm yết từ bảng companies."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT symbol FROM companies "
                "WHERE status = 'listed' AND type = 'STOCK' "
                "ORDER BY symbol"
            )
        ).fetchall()
    return [r[0] for r in rows]


def _run_one(
    symbol: str,
    extractor: TradingExtractor,
    transformer: TradingTransformer,
    loader: PostgresLoader,
) -> dict:
    """Chạy E→T→L cho một symbol. Trả về result dict."""
    log_id = loader.load_log(job_name=JOB_SYNC_RATIOS, symbol=symbol, status="running")
    try:
        df_raw = extractor.extract_ratio_summary(symbol)
        time.sleep(settings.request_delay)

        if df_raw is None:
            loader.load_log(
                job_name=JOB_SYNC_RATIOS, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "status": "skipped", "rows": 0}

        df = transformer.transform_ratio_summary(df_raw, symbol)

        if df.empty:
            loader.load_log(
                job_name=JOB_SYNC_RATIOS, symbol=symbol,
                status="skipped", log_id=log_id,
            )
            return {"symbol": symbol, "status": "skipped", "rows": 0}

        rows = loader.load(df, "ratio_summary", CONFLICT_KEYS["ratio_summary"])
        loader.load_log(
            job_name=JOB_SYNC_RATIOS, symbol=symbol,
            status="success", records_fetched=len(df),
            records_inserted=rows, log_id=log_id,
        )
        return {"symbol": symbol, "status": "success", "rows": rows}

    except Exception as exc:
        logger.error(f"[sync_ratios] {symbol} lỗi: {exc}")
        loader.load_log(
            job_name=JOB_SYNC_RATIOS, symbol=symbol,
            status="failed", error_message=str(exc)[:500], log_id=log_id,
        )
        return {"symbol": symbol, "status": "failed", "rows": 0}


def run(
    symbols: list[str] | None = None,
    max_workers: int | None = None,
) -> dict:
    """
    Đồng bộ ratio_summary vào PostgreSQL.

    Args:
        symbols:     Danh sách mã cần sync. Mặc định: tất cả STOCK đang niêm yết.
        max_workers: Số luồng song song. Mặc định: settings.max_workers.
    """
    symbols = symbols or _get_listed_symbols()
    max_workers = max_workers or settings.max_workers

    logger.info(
        f"[sync_ratios] Bắt đầu: {len(symbols)} mã ({max_workers} luồng)."
    )

    extractor = TradingExtractor(source=settings.vnstock_source)
    transformer = TradingTransformer()
    loader = PostgresLoader()

    totals = {"success": 0, "failed": 0, "skipped": 0, "rows": 0}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_one, sym, extractor, transformer, loader): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]

    logger.info(
        f"[sync_ratios] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']}"
    )
    return totals


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Đồng bộ ratio_summary.")
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Mã cần sync. Mặc định: tất cả STOCK đang niêm yết trong DB.",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Số luồng song song. Mặc định: settings.max_workers.",
    )
    args = parser.parse_args()

    result = run(
        symbols=[s.upper() for s in args.symbols] if args.symbols else None,
        max_workers=args.workers,
    )
    logger.info(f"Kết quả: {result}")
