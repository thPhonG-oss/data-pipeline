"""Job đồng bộ danh mục chứng khoán và phân ngành ICB."""
import time

from config.constants import CONFLICT_KEYS, JOB_SYNC_LISTING
from config.settings import settings
from etl.extractors.listing import ListingExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.listing import ListingTransformer
from utils.logger import logger


def run() -> dict:
    """
    Đồng bộ toàn bộ danh mục từ vnstock_data vào PostgreSQL.

    Thứ tự chạy:
    1. icb_industries — phải insert trước vì companies có FK → icb_industries
    2. companies

    Returns:
        dict với status và số records của từng bảng.
    """
    extractor = ListingExtractor(source=settings.vnstock_source)
    transformer = ListingTransformer()
    loader = PostgresLoader()

    results = {
        "icb_industries": {"status": "skipped", "records": 0},
        "companies": {"status": "skipped", "records": 0},
    }

    # ── 1. ICB Industries (từ file JSON cục bộ) ────────────────────────────────
    log_id = loader.load_log(job_name=JOB_SYNC_LISTING, status="running")
    try:
        logger.info("[sync_listing] Đọc ICB từ file JSON cục bộ (không gọi vnstock API).")
        records = extractor.load_icb_from_json()
        df = transformer.transform_industries_from_json(records)
        rows = loader.load(df, "icb_industries", CONFLICT_KEYS["icb_industries"])
        results["icb_industries"] = {"status": "success", "records": rows}
        loader.load_log(
            job_name=JOB_SYNC_LISTING,
            status="success",
            records_fetched=len(df),
            records_inserted=rows,
            log_id=log_id,
        )
        logger.success(f"[sync_listing] icb_industries: {rows} rows upserted (source: local JSON).")
    except Exception as exc:
        results["icb_industries"]["status"] = "failed"
        logger.error(f"[sync_listing] icb_industries thất bại: {exc}")
        loader.load_log(
            job_name=JOB_SYNC_LISTING,
            status="failed",
            error_message=str(exc),
            log_id=log_id,
        )
        # Không thể sync companies nếu ICB lỗi (FK constraint)
        return results

    # ── 2. Companies ───────────────────────────────────────────────────────────
    time.sleep(settings.request_delay)
    log_id2 = loader.load_log(job_name=JOB_SYNC_LISTING, status="running")
    try:
        df_raw = extractor.extract_symbols()
        df = transformer.transform_symbols(df_raw)
        rows = loader.load(df, "companies", CONFLICT_KEYS["companies"])
        results["companies"] = {"status": "success", "records": rows}
        loader.load_log(
            job_name=JOB_SYNC_LISTING,
            status="success",
            records_fetched=len(df),
            records_inserted=rows,
            log_id=log_id2,
        )
        logger.success(f"[sync_listing] companies: {rows} rows upserted.")
    except Exception as exc:
        results["companies"]["status"] = "failed"
        logger.error(f"[sync_listing] companies thất bại: {exc}")
        loader.load_log(
            job_name=JOB_SYNC_LISTING,
            status="failed",
            error_message=str(exc),
            log_id=log_id2,
        )

    return results


if __name__ == "__main__":
    result = run()
    logger.info(f"Kết quả: {result}")
