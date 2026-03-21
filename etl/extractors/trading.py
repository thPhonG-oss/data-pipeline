"""Extractor cho dữ liệu trading: ratio_summary (snapshot tài chính mới nhất)."""
import pandas as pd
from vnstock_data import Company

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry


class TradingExtractor(BaseExtractor):
    """
    Lấy dữ liệu ratio_summary từ vnstock_data.Company.

    - extract_ratio_summary(symbol) → snapshot tài chính mới nhất
    """

    def extract(self, symbol: str, **kwargs) -> pd.DataFrame | None:
        """Alias cho extract_ratio_summary() — tương thích BaseExtractor interface."""
        return self.extract_ratio_summary(symbol)

    def _company(self, symbol: str) -> Company:
        return Company(source=self.source, symbol=symbol)

    @vnstock_retry()
    def extract_ratio_summary(self, symbol: str) -> pd.DataFrame | None:
        """
        Lấy snapshot tài chính mới nhất từ Company.ratio_summary().

        Trả về None nếu API không có dữ liệu (bình thường với một số mã).
        Raise exception (và retry) nếu lỗi API thực sự.
        """
        logger.info(f"[trading] {symbol} ratio_summary...")
        try:
            df = self._company(symbol).ratio_summary()
        except TypeError:
            # API nội bộ trả về None cho một số mã → không retry, bỏ qua
            logger.warning(f"[trading] {symbol}: API trả về kiểu không hợp lệ (bỏ qua).")
            return None

        if df is None or df.empty:
            logger.warning(f"[trading] {symbol}: ratio_summary() trả về rỗng.")
            return None

        # Một số mã API trả về DataFrame chỉ có cột 'symbol', không có dữ liệu thực
        if "year_report" not in df.columns:
            logger.warning(f"[trading] {symbol}: thiếu cột year_report (bỏ qua).")
            return None

        logger.info(f"[trading] {symbol} ratio_summary: {len(df)} dòng.")
        return df
