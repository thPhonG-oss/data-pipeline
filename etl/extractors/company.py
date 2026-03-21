"""Extractor cho thông tin doanh nghiệp: overview, shareholders, officers, subsidiaries, events."""
import pandas as pd
from vnstock_data import Company

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry


class CompanyExtractor(BaseExtractor):
    """
    Lấy 5 loại dữ liệu doanh nghiệp từ vnstock_data.Company.

    - extract_overview(symbol)     → 1 dòng: id, issue_share, charter_capital, icb_name4
    - extract_shareholders(symbol) → danh sách cổ đông lớn
    - extract_officers(symbol)     → ban lãnh đạo
    - extract_subsidiaries(symbol) → công ty con / liên kết
    - extract_events(symbol)       → sự kiện doanh nghiệp
    """

    def extract(self, symbol: str, data_type: str = "overview", **kwargs) -> pd.DataFrame:
        """Dispatch theo data_type — tương thích BaseExtractor interface."""
        dispatch = {
            "overview":     self.extract_overview,
            "shareholders": self.extract_shareholders,
            "officers":     self.extract_officers,
            "subsidiaries": self.extract_subsidiaries,
            "events":       self.extract_events,
        }
        if data_type not in dispatch:
            raise ValueError(f"data_type không hợp lệ: '{data_type}'. Chọn: {list(dispatch)}")
        return dispatch[data_type](symbol)

    def _company(self, symbol: str) -> Company:
        return Company(source=self.source, symbol=symbol)

    @vnstock_retry()
    def extract_overview(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[company] {symbol} overview...")
        df = self._company(symbol).overview()
        if df is None or df.empty:
            raise ValueError(f"{symbol}: overview() trả về DataFrame rỗng.")
        logger.info(f"[company] {symbol} overview: OK.")
        return df

    @vnstock_retry()
    def extract_shareholders(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[company] {symbol} shareholders...")
        df = self._company(symbol).shareholders()
        if df is None:
            df = pd.DataFrame()
        if not df.empty:
            logger.info(f"[company] {symbol} shareholders: {len(df)} cổ đông.")
        return df

    @vnstock_retry()
    def extract_officers(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[company] {symbol} officers...")
        df = self._company(symbol).officers()
        if df is None:
            df = pd.DataFrame()
        if not df.empty:
            logger.info(f"[company] {symbol} officers: {len(df)} người.")
        return df

    @vnstock_retry()
    def extract_subsidiaries(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[company] {symbol} subsidiaries...")
        df = self._company(symbol).subsidiaries()
        if df is None:
            df = pd.DataFrame()
        if not df.empty:
            logger.info(f"[company] {symbol} subsidiaries: {len(df)} đơn vị.")
        return df

    @vnstock_retry()
    def extract_events(self, symbol: str) -> pd.DataFrame:
        logger.info(f"[company] {symbol} events...")
        df = self._company(symbol).events()
        if df is None:
            df = pd.DataFrame()
        if not df.empty:
            logger.info(f"[company] {symbol} events: {len(df)} sự kiện.")
        return df
