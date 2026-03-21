"""Extractor cho danh mục chứng khoán và phân ngành ICB."""
import pandas as pd
from vnstock_data import Listing

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry

# all_symbols() từ vci chỉ trả về 2 cột (symbol, organ_name).
# Nguồn vnd trả về đầy đủ: exchange, type, status, listed_date, ...
_SYMBOLS_SOURCE = "vnd"


class ListingExtractor(BaseExtractor):
    """
    Lấy dữ liệu danh mục từ vnstock_data.Listing.

    - extract_symbols()    → DataFrame thô cho companies    (dùng vnd)
    - extract_industries() → DataFrame thô cho icb_industries (dùng self.source)
    """

    def extract(self, symbol: str = "", **kwargs) -> pd.DataFrame:
        """Alias cho extract_symbols() — tương thích BaseExtractor interface."""
        return self.extract_symbols()

    @vnstock_retry()
    def extract_symbols(self) -> pd.DataFrame:
        """Lấy toàn bộ mã chứng khoán từ Listing.all_symbols().

        Dùng nguồn vnd vì vci chỉ trả về 2 cột (symbol, organ_name).
        """
        logger.info(f"[listing] Listing({_SYMBOLS_SOURCE}).all_symbols()...")
        df = Listing(source=_SYMBOLS_SOURCE).all_symbols()
        if df is None or df.empty:
            raise ValueError("all_symbols() trả về DataFrame rỗng.")
        logger.info(f"[listing] Lấy được {len(df)} mã chứng khoán.")
        return df

    @vnstock_retry()
    def extract_industries(self) -> pd.DataFrame:
        """Lấy phân ngành ICB từ Listing.industries_icb()."""
        logger.info(f"[listing] Listing({self.source}).industries_icb()...")
        df = Listing(source=self.source).industries_icb()
        if df is None or df.empty:
            raise ValueError("industries_icb() trả về DataFrame rỗng.")
        logger.info(f"[listing] Lấy được {len(df)} ngành ICB.")
        return df
