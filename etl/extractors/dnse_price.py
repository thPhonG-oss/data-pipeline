"""
Extractor lấy giá lịch sử OHLCV từ KBS qua vnstock Quote(source='kbs').

KBS (KB Securities) là nguồn mặc định của vnstock từ v3.4.0, không cần auth.
Đây là primary source cho sync_prices — thay thế DNSE do provider DNSE
chưa có trong vnstock 3.5.0 (chỉ có fmp, kbs, msn, vci).

Đơn vị giá KBS: nghìn VND → transformer cần nhân ×1000.
"""

from datetime import date

import pandas as pd

from etl.base.extractor import BaseExtractor
from utils.logger import logger

_YEARS_DEFAULT = 5  # Số năm lấy khi chưa có dữ liệu trong DB


class KBSPriceExtractor(BaseExtractor):
    """Lấy giá lịch sử OHLCV từ KBS (KB Securities) qua vnstock Quote(source='kbs')."""

    def __init__(self) -> None:
        super().__init__(source="kbs")

    def extract(self, symbol: str, **kwargs) -> pd.DataFrame | None:
        return self.extract_price_history(
            symbol,
            start=kwargs.get("start"),
            end=kwargs.get("end"),
        )

    def extract_price_history(
        self,
        symbol: str,
        start: date | None = None,
        end: date | None = None,
        interval: str = "1D",
    ) -> pd.DataFrame | None:
        """
        Lấy lịch sử giá OHLCV từ KBS qua vnstock.

        Returns:
            DataFrame với columns: time, open, high, low, close, volume
            Giá đơn vị nghìn VND (transformer sẽ nhân ×1000).
        """
        if end is None:
            end = date.today()
        if start is None:
            start = end.replace(year=end.year - _YEARS_DEFAULT)

        try:
            from vnstock import Quote

            df = Quote(source="kbs", symbol=symbol.upper()).history(
                start=str(start),
                end=str(end),
                interval=interval,
            )
        except Exception as exc:
            logger.error(f"[kbs_price] {symbol}: lỗi khi fetch: {exc}")
            raise

        if df is None or df.empty:
            logger.warning(f"[kbs_price] {symbol}: vnstock trả về rỗng ({start} → {end}).")
            return None

        logger.info(f"[kbs_price] {symbol}: {len(df)} phiên ({start} → {end}).")
        return df
