"""Job đồng bộ thông tin doanh nghiệp: cổ đông, lãnh đạo, công ty con, sự kiện."""
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy import text

from config.constants import CONFLICT_KEYS, JOB_SYNC_COMPANY
from config.settings import settings
from db.connection import engine
from etl.extractors.company import CompanyExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.company import CompanyTransformer
from utils.logger import logger

# Các loại dữ liệu cần sync — overview xử lý riêng (UPDATE companies, không upsert)
_DATA_TYPES = ["shareholders", "officers", "subsidiaries", "events", "news"]

_TABLE_MAP = {
    "shareholders": "shareholders",
    "officers":     "officers",
    "subsidiaries": "subsidiaries",
    "events":       "corporate_events",
    "news":         "company_news",
}


def _get_listed_symbols() -> list[str]:
    """Lấy danh sách mã cổ phiếu đang niêm yết từ bảng companies."""
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT symbol FROM companies WHERE status = 'listed' AND type = 'STOCK' ORDER BY symbol")
        ).fetchall()
    return [r[0] for r in rows]


def _update_companies_overview(symbol: str, extractor: CompanyExtractor,
                                transformer: CompanyTransformer) -> bool:
    """
    Lấy overview và UPDATE trực tiếp vào bảng companies.
    Trả về True nếu thành công.
    """
    try:
        df_raw = extractor.extract_overview(symbol)
        time.sleep(settings.request_delay)
        data = transformer.transform_overview(df_raw, symbol)

        if not data:
            return True

        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE companies
                    SET company_id      = :company_id,
                        issue_share     = :issue_share,
                        charter_capital = :charter_capital,
                        icb_code        = COALESCE(:icb_code, icb_code),
                        history         = COALESCE(:history, history),
                        company_profile = COALESCE(:company_profile, company_profile),
                        updated_at      = NOW()
                    WHERE symbol = :symbol
                """),
                data,
            )
        return True
    except Exception as exc:
        logger.exception(f"[sync_company] {symbol}/overview lỗi: {exc}")
        return False


def _run_one(
    symbol: str,
    data_type: str,
    extractor: CompanyExtractor,
    transformer: CompanyTransformer,
    loader: PostgresLoader,
) -> dict:
    """Chạy E→T→L cho một symbol + data_type. Trả về result dict."""
    table = _TABLE_MAP[data_type]
    log_id = loader.load_log(job_name=JOB_SYNC_COMPANY, symbol=symbol, status="running")
    try:
        df_raw = extractor.extract(symbol, data_type=data_type)
        time.sleep(settings.request_delay)

        if df_raw.empty:
            loader.load_log(job_name=JOB_SYNC_COMPANY, symbol=symbol,
                            status="skipped", log_id=log_id)
            return {"symbol": symbol, "data_type": data_type, "status": "skipped", "rows": 0}

        df = transformer.transform(df_raw, symbol, data_type=data_type)
        if df.empty:
            loader.load_log(job_name=JOB_SYNC_COMPANY, symbol=symbol,
                            status="skipped", log_id=log_id)
            return {"symbol": symbol, "data_type": data_type, "status": "skipped", "rows": 0}

        rows = loader.load(df, table, CONFLICT_KEYS[table])
        loader.load_log(job_name=JOB_SYNC_COMPANY, symbol=symbol,
                        status="success", records_fetched=len(df),
                        records_inserted=rows, log_id=log_id)
        return {"symbol": symbol, "data_type": data_type, "status": "success", "rows": rows}

    except Exception as exc:
        logger.exception(f"[sync_company] {symbol}/{data_type} lỗi: {exc}")
        loader.load_log(job_name=JOB_SYNC_COMPANY, symbol=symbol,
                        status="failed", error_message=str(exc)[:500], log_id=log_id)
        return {"symbol": symbol, "data_type": data_type, "status": "failed", "rows": 0}


def run(
    symbols: list[str] | None = None,
    data_types: list[str] | None = None,
    max_workers: int | None = None,
    sync_overview: bool = True,
) -> dict:
    """
    Đồng bộ thông tin doanh nghiệp vào PostgreSQL.

    Args:
        symbols:      Danh sách mã cần sync. Mặc định: tất cả STOCK đang niêm yết.
        data_types:   Loại dữ liệu cần sync. Mặc định: tất cả 4 loại.
        max_workers:  Số luồng song song. Mặc định: settings.max_workers.
        sync_overview: Có UPDATE icb_code/charter_capital/issue_share vào companies hay không.
    """
    symbols = symbols or _get_listed_symbols()
    data_types = data_types or _DATA_TYPES
    max_workers = max_workers or settings.max_workers

    logger.info(
        f"[sync_company] Bắt đầu: {len(symbols)} mã × {len(data_types)} loại "
        f"({'+ overview ' if sync_overview else ''}{max_workers} luồng)."
    )

    extractor = CompanyExtractor(source=settings.vnstock_source)
    transformer = CompanyTransformer()
    loader = PostgresLoader()

    # ── Phase A: UPDATE companies (overview) — sequential để tránh lock contention ──
    if sync_overview:
        overview_ok = 0
        overview_fail = 0
        for sym in symbols:
            ok = _update_companies_overview(sym, extractor, transformer)
            time.sleep(settings.request_delay)
            if ok:
                overview_ok += 1
            else:
                overview_fail += 1
        logger.info(f"[sync_company] Overview done: ok={overview_ok} fail={overview_fail}")

    # ── Phase B: Upsert shareholders / officers / subsidiaries / events ──────────
    totals = {"success": 0, "failed": 0, "skipped": 0, "rows": 0}
    tasks = [(sym, dt) for sym in symbols for dt in data_types]

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_run_one, sym, dt, extractor, transformer, loader): (sym, dt)
            for sym, dt in tasks
        }
        for future in as_completed(futures):
            result = future.result()
            totals[result["status"]] += 1
            totals["rows"] += result["rows"]

    logger.info(
        f"[sync_company] Xong. "
        f"Success={totals['success']} | Failed={totals['failed']} | "
        f"Skipped={totals['skipped']} | Rows={totals['rows']}"
    )
    return totals


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Đồng bộ thông tin doanh nghiệp.")
    parser.add_argument(
        "--symbols", nargs="+", default=None,
        help="Mã cần sync. Mặc định: tất cả STOCK đang niêm yết.",
    )
    parser.add_argument(
        "--data-types", nargs="+", default=None,
        choices=_DATA_TYPES,
        help="Loại dữ liệu. Mặc định: tất cả 5 loại.",
    )
    parser.add_argument(
        "--workers", type=int, default=None,
        help="Số luồng song song. Mặc định: settings.max_workers.",
    )
    parser.add_argument(
        "--no-overview", action="store_true",
        help="Bỏ qua bước UPDATE icb_code/charter_capital/issue_share trong companies.",
    )
    args = parser.parse_args()

    result = run(
        symbols=[s.upper() for s in args.symbols] if args.symbols else None,
        data_types=args.data_types,
        max_workers=args.workers,
        sync_overview=not args.no_overview,
    )
    logger.info(f"Kết quả: {result}")
