"""
ApproachCLoader — upsert payloads vào 4 bảng Approach C.

Mỗi statement_type có conflict key riêng:
    fin_balance_sheet      → (symbol, period, period_type)
    fin_income_statement   → (symbol, period, period_type)
    fin_cash_flow          → (symbol, period, period_type)
    fin_financial_ratios   → (symbol, period, period_type)

Tất cả đều dùng PostgresLoader.load() — upsert generic.
"""

from __future__ import annotations

import pandas as pd

from config.constants import CONFLICT_KEYS
from etl.loaders.postgres import PostgresLoader
from etl.transformers.approach_c.factory import TABLE_MAP
from utils.logger import logger


class ApproachCLoader:
    """
    Loader chuyên dụng cho 4 bảng Approach C.

    Cách dùng:
        loader = ApproachCLoader()
        rows = loader.load(payloads, statement_type="ratio")
    """

    def __init__(self) -> None:
        self._pg = PostgresLoader()

    def load(
        self,
        payloads: list[dict],
        statement_type: str,
    ) -> int:
        """
        Upsert payloads vào bảng tương ứng với statement_type.

        Args:
            payloads:       List dict đã parse từ ApproachCFactory.
            statement_type: "balance_sheet" | "income_statement" | "cash_flow" | "ratio"

        Returns:
            Số rows đã xử lý.
        """
        if not payloads:
            return 0

        table = TABLE_MAP[statement_type]
        conflict_columns = CONFLICT_KEYS[table]

        df = pd.DataFrame(payloads)
        rows = self._pg.load(
            df,
            table=table,
            conflict_columns=conflict_columns,
            jsonb_merge_columns=["raw_details"],
        )
        logger.debug(f"[approach_c_loader] {table}: {rows} rows upserted.")
        return rows
