"""
sync_hsx_company — Đồng bộ thông tin công ty từ HSX API vào bảng companies.

ETL logic (upsert via ON CONFLICT DO UPDATE):
  - Symbol đã tồn tại  → UPDATE chỉ: brief, phone, fax, address, web_url
  - Symbol chưa tồn tại → INSERT với: symbol, company_name, exchange, type,
                                       brief, phone, fax, address, web_url

Thiết kế:
  - Chạy độc lập hoặc sau sync_company (enrich step).
  - Chỉ cập nhật 5 cột HSX; không đụng icb_code, charter_capital, history, v.v.
  - Idempotent: chạy nhiều lần không gây trùng lặp.

Cách dùng:
    python main.py sync_hsx_company
"""
from __future__ import annotations

from datetime import datetime, timezone

from config.constants import JOB_SYNC_HSX_COMPANY
from etl.extractors.hsx_company import HSXCompanyExtractor
from etl.loaders.postgres import PostgresLoader
from etl.transformers.hsx_company import HSXCompanyTransformer
from utils.logger import logger

# Chỉ UPDATE những cột này khi symbol đã tồn tại
_UPDATE_COLS = ["brief", "phone", "fax", "address", "web_url"]


class SyncHSXCompanyJob:
    def __init__(self) -> None:
        self._extractor   = HSXCompanyExtractor()
        self._transformer = HSXCompanyTransformer()
        self._loader      = PostgresLoader()

    def run(self) -> dict:
        """
        Chạy toàn bộ ETL pipeline HSX → companies.

        Returns:
            {"fetched": int, "upserted": int}
        """
        log_id = self._loader.load_log(
            JOB_SYNC_HSX_COMPANY, symbol="ALL", status="running"
        )
        start = datetime.now(tz=timezone.utc)

        try:
            # ── Extract ───────────────────────────────────────────────────────
            logger.info("[sync_hsx_company] Fetching từ HSX API...")
            records = self._extractor.extract_all()
            logger.info(f"[sync_hsx_company] Fetched: {len(records)} records.")

            # ── Transform ─────────────────────────────────────────────────────
            df = self._transformer.transform(records)
            if df.empty:
                logger.warning("[sync_hsx_company] Không có dữ liệu sau transform.")
                self._loader.load_log(
                    JOB_SYNC_HSX_COMPANY, symbol="ALL", status="success",
                    records_fetched=0, records_inserted=0, log_id=log_id,
                )
                return {"fetched": 0, "upserted": 0}

            # ── Load ──────────────────────────────────────────────────────────
            # ON CONFLICT (symbol) DO UPDATE SET brief=..., phone=..., ...
            # Nếu symbol chưa có → INSERT toàn bộ các cột trong df.
            upserted = self._loader.load(
                df,
                table="companies",
                conflict_columns=["symbol"],
                update_columns=_UPDATE_COLS,
            )

            elapsed = (datetime.now(tz=timezone.utc) - start).total_seconds()
            logger.info(
                f"[sync_hsx_company] Hoàn tất {elapsed:.1f}s | "
                f"Fetched: {len(df)} | Upserted: {upserted}"
            )
            self._loader.load_log(
                JOB_SYNC_HSX_COMPANY, symbol="ALL", status="success",
                records_fetched=len(df), records_inserted=upserted, log_id=log_id,
            )
            return {"fetched": len(df), "upserted": upserted}

        except Exception as exc:
            logger.error(f"[sync_hsx_company] Lỗi: {exc}")
            self._loader.load_log(
                JOB_SYNC_HSX_COMPANY, symbol="ALL", status="error",
                error_message=str(exc), log_id=log_id,
            )
            raise


def run() -> dict:
    """Entry point cho main.py và scheduler."""
    return SyncHSXCompanyJob().run()
