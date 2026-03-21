"""PostgreSQL loader — upsert DataFrame vào bảng bằng ON CONFLICT DO UPDATE."""
from typing import Optional

import pandas as pd
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert

from config.constants import SERVER_GENERATED_COLS
from config.settings import settings
from db.connection import engine
from etl.base.loader import BaseLoader
from etl.loaders.helpers import chunk_dataframe, df_to_records
from utils.logger import logger


class PostgresLoader(BaseLoader):
    """
    Upsert DataFrame vào PostgreSQL bằng INSERT ... ON CONFLICT DO UPDATE.

    Cách dùng:
        loader = PostgresLoader()
        rows = loader.load(
            df,
            table="balance_sheets",
            conflict_columns=["symbol", "period", "period_type"],
        )
    """

    def __init__(self, chunk_size: Optional[int] = None) -> None:
        self.chunk_size = chunk_size or settings.db_chunk_size
        self._metadata = MetaData()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _reflect_table(self, table_name: str) -> Table:
        """
        Reflect schema bảng từ DB (cache trong _metadata).
        Bảng phải tồn tại trong DB trước khi load.
        """
        if table_name not in self._metadata.tables:
            self._metadata.reflect(bind=engine, only=[table_name], resolve_fks=False)
        if table_name not in self._metadata.tables:
            raise RuntimeError(
                f"Bảng '{table_name}' không tồn tại trong DB. "
                "Hãy chạy migrations trước: python -m db.migrate"
            )
        return self._metadata.tables[table_name]

    def _resolve_update_columns(
        self,
        table: Table,
        conflict_columns: list[str],
        update_columns: Optional[list[str]],
    ) -> list[str]:
        """
        Xác định danh sách cột sẽ UPDATE khi có conflict.
        Loại trừ: conflict_columns, SERVER_GENERATED_COLS, và cột không có trong df.
        """
        if update_columns is not None:
            return update_columns

        skip = set(conflict_columns) | SERVER_GENERATED_COLS
        return [c.name for c in table.columns if c.name not in skip]

    # ── Public API ────────────────────────────────────────────────────────────

    def load(
        self,
        df: pd.DataFrame,
        table: str,
        conflict_columns: list[str],
        update_columns: Optional[list[str]] = None,
    ) -> int:
        """
        Upsert toàn bộ DataFrame vào bảng PostgreSQL theo từng chunk.

        - Nếu row chưa tồn tại → INSERT
        - Nếu row đã tồn tại (conflict theo conflict_columns) → UPDATE
        - Cột server-generated (id, duration_ms, created_at) không bao giờ bị ghi đè

        Trả về tổng số dòng được xử lý.
        """
        if df.empty:
            logger.debug(f"[{table}] DataFrame rỗng — bỏ qua.")
            return 0

        tbl = self._reflect_table(table)
        update_cols = self._resolve_update_columns(tbl, conflict_columns, update_columns)

        # Chỉ giữ các cột thực sự có trong bảng (bỏ cột dư từ transformer)
        valid_cols = {c.name for c in tbl.columns}
        df_filtered = df[[c for c in df.columns if c in valid_cols]]

        if df_filtered.empty:
            logger.warning(f"[{table}] Không có cột nào khớp với schema bảng.")
            return 0

        # Loại update_cols không có trong df
        update_cols = [c for c in update_cols if c in df_filtered.columns]

        total = 0
        records = df_to_records(df_filtered)

        for start in range(0, len(records), self.chunk_size):
            chunk_records = records[start : start + self.chunk_size]
            if not chunk_records:
                continue

            stmt = pg_insert(tbl).values(chunk_records)
            stmt = stmt.on_conflict_do_update(
                index_elements=conflict_columns,
                set_={col: stmt.excluded[col] for col in update_cols},
            )

            with engine.begin() as conn:
                result = conn.execute(stmt)
                total += result.rowcount

        logger.info(f"[{table}] Upserted {total} rows.")
        return total

    def load_log(
        self,
        job_name: str,
        symbol: Optional[str] = None,
        status: str = "running",
        records_fetched: int = 0,
        records_inserted: int = 0,
        error_message: Optional[str] = None,
        log_id: Optional[int] = None,
    ) -> int:
        """
        Ghi hoặc cập nhật một dòng vào pipeline_logs.

        - Nếu log_id=None → INSERT mới, trả về id mới.
        - Nếu log_id được truyền vào → UPDATE dòng đó.
        """
        from datetime import datetime, timezone

        tbl = self._reflect_table("pipeline_logs")

        with engine.begin() as conn:
            if log_id is None:
                # INSERT
                result = conn.execute(
                    tbl.insert().values(
                        job_name=job_name,
                        symbol=symbol,
                        status=status,
                        records_fetched=records_fetched,
                        records_inserted=records_inserted,
                        error_message=error_message,
                        started_at=datetime.now(tz=timezone.utc),
                    ).returning(tbl.c.id)
                )
                return result.scalar_one()
            else:
                # UPDATE
                conn.execute(
                    tbl.update()
                    .where(tbl.c.id == log_id)
                    .values(
                        status=status,
                        records_fetched=records_fetched,
                        records_inserted=records_inserted,
                        error_message=error_message,
                        finished_at=datetime.now(tz=timezone.utc),
                    )
                )
                return log_id
