"""
Extractor lấy giá lịch sử OHLCV từ VNDirect finfo-api.

Dùng làm FALLBACK khi DNSE không khả dụng (token hết hạn, endpoint thay đổi, account bị khóa).
Public API — không cần authentication. Ổn định từ 2019.
Đơn vị giá trả về: nghìn VND (×1000 để ra VND nguyên khi lưu DB).
Có adClose (adjusted close) — ưu điểm so với DNSE.
"""

from datetime import date

import pandas as pd
import requests

from etl.base.extractor import BaseExtractor
from utils.logger import logger
from utils.retry import vnstock_retry

_BASE_URL = "https://finfo-api.vndirect.com.vn"
_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.vndirect.com.vn/",
}
_PAGE_SIZE = 500


class VNDirectPriceExtractor(BaseExtractor):
    """Lấy giá lịch sử OHLCV từ VNDirect finfo-api (fallback cho DNSE)."""

    def __init__(self) -> None:
        super().__init__(source="vndirect")

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
    ) -> pd.DataFrame | None:
        """
        Lấy lịch sử giá OHLCV từ VNDirect finfo-api với pagination.

        Args:
            symbol: Mã chứng khoán (ví dụ: "HPG").
            start:  Từ ngày. None = 5 năm gần nhất.
            end:    Đến ngày. None = hôm nay.

        Returns:
            DataFrame với raw columns từ VNDirect, hoặc None nếu rỗng.
        """
        if end is None:
            end = date.today()
        if start is None:
            start = end.replace(year=end.year - 5)

        all_records: list[dict] = []
        page = 1
        while True:
            batch = self._fetch_page(symbol, start, end, page)
            if not batch:
                break
            all_records.extend(batch)
            if len(batch) < _PAGE_SIZE:
                break
            page += 1

        if not all_records:
            logger.warning(f"[vndirect_price] {symbol}: API trả về rỗng ({start} → {end}).")
            return None

        df = pd.DataFrame(all_records)
        logger.info(f"[vndirect_price] {symbol}: {len(df)} phiên ({start} → {end}).")
        return df

    @vnstock_retry()
    def _fetch_page(self, symbol: str, start: date, end: date, page: int) -> list[dict]:
        params = {
            "sort": "date",
            "size": _PAGE_SIZE,
            "page": page,
            "q": f"code:{symbol.upper()}~date:gte:{start}~date:lte:{end}",
        }
        resp = requests.get(
            f"{_BASE_URL}/v4/stock_prices/",
            params=params,
            headers=_HEADERS,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
