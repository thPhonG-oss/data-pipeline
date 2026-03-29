"""
Approach C transformers — phân tách 4 bảng riêng biệt:
    fin_balance_sheet, fin_income_statement, fin_cash_flow, fin_financial_ratios

Reuse toàn bộ parser logic từ etl/transformers/finance_parsers.py.
Thêm mới: RatioParser (chưa có trong Approach A).
"""

from etl.transformers.approach_c.factory import ApproachCFactory
from etl.transformers.approach_c.ratio_parser import RatioParser

__all__ = ["RatioParser", "ApproachCFactory"]
