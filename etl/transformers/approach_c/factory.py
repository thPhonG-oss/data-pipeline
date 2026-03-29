"""
ApproachCFactory — routing parser cho 4 bảng Approach C.

- BS/IS/CF: dùng lại FinanceParserFactory (đã có)
- ratio: dùng RatioParser (mới)

Routing bảng đích:
    statement_type          → table
    "balance_sheet"         → fin_balance_sheet
    "income_statement"      → fin_income_statement
    "cash_flow"             → fin_cash_flow
    "ratio"                 → fin_financial_ratios
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from etl.transformers.approach_c.ratio_parser import RatioParser
from etl.transformers.finance_factory import FinanceParserFactory

# Mapping statement_type → table name trong DB
TABLE_MAP: dict[str, str] = {
    "balance_sheet": "fin_balance_sheet",
    "income_statement": "fin_income_statement",
    "cash_flow": "fin_cash_flow",
    "ratio": "fin_financial_ratios",
}

_RATIO_PARSER = RatioParser()


class ApproachCFactory:
    """
    Factory trả về payloads đã parse cho 4 bảng Approach C.

    Cách dùng:
        payloads, table = ApproachCFactory.parse(
            df=df_raw,
            symbol="HPG",
            statement_type="ratio",
            icb_code="10101010",
        )
        loader.load(pd.DataFrame(payloads), table, conflict_columns=...)
    """

    @staticmethod
    def parse(
        df: pd.DataFrame,
        symbol: str,
        statement_type: str,
        icb_code: str | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Parse DataFrame → (payloads, table_name).

        Args:
            df:             DataFrame thô từ Finance extractor.
            symbol:         Mã cổ phiếu (uppercase).
            statement_type: "balance_sheet" | "income_statement" | "cash_flow" | "ratio"
            icb_code:       ICB code để định tuyến template (không dùng cho ratio).

        Returns:
            (payloads, table_name)
        """
        if statement_type not in TABLE_MAP:
            raise ValueError(
                f"statement_type không hợp lệ: '{statement_type}'. Chọn: {list(TABLE_MAP)}"
            )

        table = TABLE_MAP[statement_type]

        if statement_type == "ratio":
            payloads = _RATIO_PARSER.parse(df, symbol, icb_code=icb_code)
        else:
            parser = FinanceParserFactory.get_parser(icb_code, statement_type)
            payloads = parser.parse(df, symbol, icb_code=icb_code)

        return payloads, table

    @staticmethod
    def table_for(statement_type: str) -> str:
        """Trả về tên bảng đích cho statement_type."""
        return TABLE_MAP[statement_type]
