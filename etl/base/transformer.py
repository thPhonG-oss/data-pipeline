"""Abstract base class cho tất cả Transformers."""
from abc import ABC, abstractmethod

import pandas as pd


class BaseTransformer(ABC):
    """
    Nhận DataFrame thô từ Extractor, trả về DataFrame đã chuẩn hóa
    sẵn sàng để load vào PostgreSQL.

    Trách nhiệm:
        - Đổi tên cột (tiếng Việt → tên cột schema)
        - Ép kiểu dữ liệu (str → int/float/date)
        - Loại bỏ dòng không hợp lệ (toàn null, thiếu key)
        - Thêm metadata cột (symbol, period, period_type, source...)
        - Serialize dữ liệu gốc vào cột raw_data (nếu bảng có JSONB)
    """

    @abstractmethod
    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        """
        Chuẩn hóa DataFrame.

        Args:
            df: DataFrame thô từ Extractor.
            symbol: Mã chứng khoán đang xử lý.
            **context: Thông tin thêm, ví dụ:
                - period_type: 'year' | 'quarter'
                - source: 'vci'
                - snapshot_date: date (cho shareholders, officers...)

        Returns:
            DataFrame đã chuẩn hóa, các cột khớp với schema bảng đích.
        """
        ...
