"""Extractor cho báo cáo tài chính: balance_sheet, income_statement, cash_flow, ratio."""
import pandas as pd
from vnstock_data import Finance

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry


class FinanceExtractor(BaseExtractor):
    """
    Lấy 4 loại báo cáo tài chính từ vnstock_data.Finance.

    Một lần gọi API trả về cả dữ liệu năm lẫn quý trong cùng DataFrame
    (phân biệt qua cột report_period = 'year'/'quarter').
    """

    def extract(self, symbol: str, report_type: str = "balance_sheet", **kwargs) -> pd.DataFrame:
        """Dispatch theo report_type — tương thích BaseExtractor interface."""
        dispatch = {
            "balance_sheet":      self.extract_balance_sheet,
            "income_statement":   self.extract_income_statement,
            "cash_flow":          self.extract_cash_flow,
            "ratio":              self.extract_ratio,
        }
        if report_type not in dispatch:
            raise ValueError(f"report_type không hợp lệ: '{report_type}'. Chọn: {list(dispatch)}")
        return dispatch[report_type](symbol)

    def _finance(self, symbol: str) -> Finance:
        return Finance(source=self.source, symbol=symbol, period="year")

    @vnstock_retry()
    def extract_balance_sheet(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[finance] {symbol} balance_sheet...")
        df = self._finance(symbol).balance_sheet(lang="vi")
        if df is None or df.empty:
            raise ValueError(f"{symbol}: balance_sheet() trả về DataFrame rỗng.")
        logger.info(f"[finance] {symbol} balance_sheet: {len(df)} kỳ.")
        return df

    @vnstock_retry()
    def extract_income_statement(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[finance] {symbol} income_statement...")
        df = self._finance(symbol).income_statement(lang="vi")
        if df is None or df.empty:
            raise ValueError(f"{symbol}: income_statement() trả về DataFrame rỗng.")
        logger.info(f"[finance] {symbol} income_statement: {len(df)} kỳ.")
        return df

    @vnstock_retry()
    def extract_cash_flow(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[finance] {symbol} cash_flow...")
        df = self._finance(symbol).cash_flow(lang="vi")
        if df is None or df.empty:
            raise ValueError(f"{symbol}: cash_flow() trả về DataFrame rỗng.")
        logger.info(f"[finance] {symbol} cash_flow: {len(df)} kỳ.")
        return df

    @vnstock_retry()
    def extract_ratio(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[finance] {symbol} ratio...")
        df = self._finance(symbol).ratio(lang="vi")
        if df is None or df.empty:
            raise ValueError(f"{symbol}: ratio() trả về DataFrame rỗng.")
        logger.info(f"[finance] {symbol} ratio: {len(df)} kỳ.")
        return df
