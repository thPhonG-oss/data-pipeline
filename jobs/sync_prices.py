"""Job đồng bộ giá lịch sử OHLCV — KBS primary, VNDirect fallback.

Luồng xử lý cho mỗi symbol:
  1. Query MAX(date) trong price_history từ DB (incremental sync)
  2. Nếu có: chỉ fetch từ ngày cuối+1 đến hôm nay
  3. Nếu chưa có (lần đầu): fetch 5 năm lịch sử
  4. Thử KBS trước → nếu lỗi tự động fallback sang VNDirect
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

from sqlalchemy import text

from config.constants import CONFLICT_KEYS, JOB_SYNC_PRICES
from config.settings import settings
from db.connection import engine
from etl.extractors.dnse_price import KBSPriceExtractor
from etl.extractors.vndirect_price import VNDirectPriceExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.dnse_price import KBSPriceTransformer
from etl.transformers.vndirect_price import VNDirectPriceTransformer
from utils.logger import logger

_TABLE = "price_history"
_CONFLICT_KEYS = CONFLICT_KEYS[_TABLE]
_YEARS_DEFAULT = 5


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


def _get_last_date(symbol: str) -> date | None:
    """Lấy ngày mới nhất đã có trong DB cho symbol này (bất kỳ source)."""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT MAX(date) FROM price_history WHERE symbol = :sym"),
            {"sym": symbol},
        ).fetchone()
    return row[0] if row and row[0] else None


def _run_one(
    symbol: str,
    kbs_ext: KBSPriceExtractor,
    kbs_tx: KBSPriceTransformer,
    vnd_ext: VNDirectPriceExtractor,
    vnd_tx: VNDirectPriceTransformer,
    loader: PostgresLoader,
    full_history: bool = False,
) -> dict:
    """Chạy E→T→L cho một symbol với DNSE primary + VNDirect fallback."""
    log_id = loader.load_log(job_name=JOB_SYNC_PRICES, symbol=symbol, status="running")

    try:
        # Xác định start date (incremental)
        today = date.today()
        if full_history:
            start = today.replace(year=today.year - _YEARS_DEFAULT)
        else:
            last = _get_last_date(symbol)
            if last:
                start = last + timedelta(days=1)
                if start > today:
                    loader.load_log(
                        job_name=JOB_SYNC_PRICES,
                        symbol=symbol,
                        status="skipped",
                        log_id=log_id,
                    )
                    return {"symbol": symbol, "status": "skipped", "rows": 0, "source": "none"}
            else:
                start = today.replace(year=today.year - _YEARS_DEFAULT)

        # Thử KBS primary (qua vnstock)
        source_used = "kbs"
        df_raw = None
        try:
            df_raw = kbs_ext.extract_price_history(symbol, start=start, end=today)
            time.sleep(settings.request_delay)
        except Exception as kbs_exc:
            logger.warning(
                f"[sync_prices] {symbol}: KBS lỗi ({kbs_exc}), chuyển sang VNDirect fallback."
            )
            source_used = "vndirect"

        # Fallback VNDirect nếu DNSE lỗi hoặc trả về rỗng
        if df_raw is None or (hasattr(df_raw, "empty") and df_raw.empty):
            try:
                df_raw = vnd_ext.extract_price_history(symbol, start=start, end=today)
                source_used = "vndirect"
                time.sleep(settings.request_delay)
            except Exception as vnd_exc:
                raise RuntimeError(
                    f"Cả DNSE lẫn VNDirect đều lỗi cho {symbol}: {vnd_exc}"
                ) from vnd_exc

        if df_raw is None or (hasattr(df_raw, "empty") and df_raw.empty):
            loader.load_log(
                job_name=JOB_SYNC_PRICES,
                symbol=symbol,
                status="skipped",
                log_id=log_id,
            )
            return {"symbol": symbol, "status": "skipped", "rows": 0, "source": source_used}

        # Transform
        if source_used == "kbs":
            df = kbs_tx.transform(df_raw, symbol)
        else:
            df = vnd_tx.transform(df_raw, symbol)

        if df.empty:
            loader.load_log(
                job_name=JOB_SYNC_PRICES,
                symbol=symbol,
                status="skipped",
                log_id=log_id,
            )
            return {"symbol": symbol, "status": "skipped", "rows": 0, "source": source_used}

        # Load
        rows = loader.load(df, _TABLE, _CONFLICT_KEYS)
        loader.load_log(
            job_name=JOB_SYNC_PRICES,
            symbol=symbol,
            status="success",
            records_fetched=len(df),
            records_inserted=rows,
            log_id=log_id,
        )
        return {"symbol": symbol, "status": "success", "rows": rows, "source": source_used}

    except Exception as exc:
        logger.error(f"[sync_prices] {symbol} lỗi: {exc}")
        loader.load_log(
            job_name=JOB_SYNC_PRICES,
            symbol=symbol,
            status="failed",
            error_message=str(exc)[:500],
            log_id=log_id,
        )
        return {"symbol": symbol, "status": "failed", "rows": 0, "source": "none"}


def run(
    symbols: list[str] | None = None,
    max_workers: int | None = None,
    full_history: bool = False,
) -> dict:
    """
    Đồng bộ giá lịch sử OHLCV vào bảng price_history.

    Args:
        symbols:      Danh sách mã cần sync. Mặc định: tất cả STOCK đang niêm yết.
        max_workers:  Số luồng song song. Mặc định: settings.max_workers.
        full_history: True = fetch lại 5 năm lịch sử (bỏ qua incremental).
    """
    symbols = symbols or _get_listed_symbols()
    max_workers = max_workers or settings.max_workers

    logger.info(
        f"[sync_prices] Bắt đầu: {len(symbols)} mã, "
        f"{max_workers} luồng, full_history={full_history}."
    )

    kbs_ext = KBSPriceExtractor()
    kbs_tx = KBSPriceTransformer()
    vnd_ext = VNDirectPriceExtractor()
    vnd_tx = VNDirectPriceTransformer()
    loader = PostgresLoader()

    totals = {"success": 0, "failed": 0, "skipped": 0, "rows": 0, "kbs": 0, "vndirect": 0}

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _run_one,
                sym,
                kbs_ext,
                kbs_tx,
                vnd_ext,
                vnd_tx,
                loader,
                full_history,
            ): sym
            for sym in symbols
        }
        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]
            if result["source"] in ("kbs", "vndirect"):
                totals[result["source"]] += 1

    logger.info(
        f"[sync_prices] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']} | "
        f"KBS={totals['kbs']} | VNDirect={totals['vndirect']}"
    )
    return totals


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Đồng bộ giá lịch sử OHLCV.")
    parser.add_argument(
        "--symbol",
        nargs="+",
        default=None,
        metavar="SYM",
        help="Mã cần sync. Mặc định: tất cả STOCK đang niêm yết.",
    )
    parser.add_argument("--workers", type=int, default=None, help="Số luồng song song.")
    parser.add_argument(
        "--full-history", action="store_true", help="Fetch lại 5 năm lịch sử (bỏ qua incremental)."
    )
    args = parser.parse_args()

    result = run(
        symbols=[s.upper() for s in args.symbol] if args.symbol else None,
        max_workers=args.workers,
        full_history=args.full_history,
    )
    logger.info(f"Kết quả: {result}")
