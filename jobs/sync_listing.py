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

    # ── 1. Fetch symbols raw (dùng chung cho cả ICB supplement lẫn companies) ──
    time.sleep(settings.request_delay)
    try:
        df_symbols_raw = extractor.extract_symbols()
    except Exception as exc:
        logger.error(f"[sync_listing] extract_symbols() thất bại: {exc}")
        df_symbols_raw = None

    # ── 2. ICB Industries ──────────────────────────────────────────────────────
    log_id = loader.load_log(job_name=JOB_SYNC_LISTING, status="running")
    try:
        # 2a. JSON → upsert (update nếu tồn tại, insert nếu chưa có)
        logger.info("[sync_listing] Đọc ICB từ file JSON cục bộ...")
        json_records = extractor.load_icb_from_json()
        df_icb_json = transformer.transform_industries_from_json(json_records)
        rows_json = loader.load(df_icb_json, "icb_industries", CONFLICT_KEYS["icb_industries"])
        logger.success(f"[sync_listing] icb_industries (JSON): {rows_json} rows upserted.")

        # 2b. industries_icb() (vnstock API) → upsert các code bổ sung từ thị trường VN
        rows_extra = 0
        extra_fetched = 0
        try:
            df_icb_api_raw = extractor.extract_industries()
            df_icb_extra = transformer.transform_industries(df_icb_api_raw)
            extra_fetched = len(df_icb_extra)
            if not df_icb_extra.empty:
                # Không update parent_code khi upsert từ API vì API không có hierarchy.
                # Tránh ghi đè parent_code đầy đủ đã được insert từ JSON.
                rows_extra = loader.load(
                    df_icb_extra,
                    "icb_industries",
                    CONFLICT_KEYS["icb_industries"],
                    update_columns=["icb_name", "en_icb_name", "level"],
                )
                logger.success(
                    f"[sync_listing] icb_industries (vnstock API): {rows_extra} rows upserted."
                )
        except Exception as exc:
            logger.warning(f"[sync_listing] industries_icb() thất bại (không nghiêm trọng): {exc}")

        total_icb = rows_json + rows_extra
        results["icb_industries"] = {"status": "success", "records": total_icb}
        loader.load_log(
            job_name=JOB_SYNC_LISTING,
            status="success",
            records_fetched=len(df_icb_json) + extra_fetched,
            records_inserted=total_icb,
            log_id=log_id,
        )
        logger.info(
            f"[sync_listing] icb_industries tổng: {total_icb} rows (JSON={rows_json}, symbols={rows_extra})."
        )
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

    # ── 3. Companies (reuse df_symbols_raw) ────────────────────────────────────
    if df_symbols_raw is None:
        results["companies"] = {"status": "failed", "records": 0}
        logger.error("[sync_listing] Bỏ qua companies vì extract_symbols() đã thất bại ở bước 1.")
        return results

    log_id2 = loader.load_log(job_name=JOB_SYNC_LISTING, status="running")
    try:
        df_companies = transformer.transform_symbols(df_symbols_raw)
        rows = loader.load(df_companies, "companies", CONFLICT_KEYS["companies"])
        results["companies"] = {"status": "success", "records": rows}
        loader.load_log(
            job_name=JOB_SYNC_LISTING,
            status="success",
            records_fetched=len(df_companies),
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
