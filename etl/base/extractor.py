"""Abstract base class cho tất cả Extractors."""

from abc import ABC, abstractmethod

import pandas as pd


class BaseExtractor(ABC):
    """
    Gọi vnstock_data API và trả về DataFrame thô, chưa làm sạch.

    Cách dùng:
        class MyExtractor(BaseExtractor):
            def extract(self, symbol: str, **kwargs) -> pd.DataFrame:
                return SomeAPI(symbol=symbol, source=self.source).some_method(**kwargs)
    """

    def __init__(self, source: str = "vci") -> None:
        self.source = source.lower()

    @abstractmethod
    def extract(self, symbol: str, **kwargs) -> pd.DataFrame:
        """
        Lấy dữ liệu cho một mã chứng khoán.

        Args:
            symbol: Mã chứng khoán (ví dụ: 'HPG', 'VCB')
            **kwargs: Tham số thêm tuỳ loại dữ liệu (period, start, end, ...)

        Returns:
            DataFrame thô từ API — chưa đổi tên cột, chưa ép kiểu.

        Raises:
            Exception: Nếu API trả lỗi hoặc dữ liệu rỗng sau retry.
        """
        ...
