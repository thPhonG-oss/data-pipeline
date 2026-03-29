"""Abstract base class cho tất cả Loaders."""

from abc import ABC, abstractmethod

import pandas as pd


class BaseLoader(ABC):
    """
    Nhận DataFrame đã chuẩn hóa từ Transformer và ghi vào storage.

    Cách dùng:
        class MyLoader(BaseLoader):
            def load(self, df, table, conflict_columns) -> int:
                # upsert vào DB
                return rows_affected
    """

    @abstractmethod
    def load(
        self,
        df: pd.DataFrame,
        table: str,
        conflict_columns: list[str],
        update_columns: list[str] | None = None,
    ) -> int:
        """
        Upsert DataFrame vào bảng đích.

        Args:
            df: DataFrame đã chuẩn hóa, các cột khớp với bảng.
            table: Tên bảng đích trong PostgreSQL.
            conflict_columns: Cột làm khóa ON CONFLICT (unique key).
            update_columns: Cột sẽ UPDATE khi conflict.
                            Nếu None → update tất cả trừ conflict_columns và id.

        Returns:
            Số dòng được insert hoặc update.

        Raises:
            Exception: Nếu kết nối DB lỗi hoặc vi phạm constraint không xử lý được.
        """
        ...
