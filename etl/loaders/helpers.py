"""Hàm tiện ích dùng chung cho các loaders."""
import math
from typing import Any, Generator

import numpy as np
import pandas as pd


def sanitize_for_postgres(df: pd.DataFrame) -> pd.DataFrame:
    """
    Thay thế NaN / NaT / inf / -inf bằng None để psycopg2 ánh xạ sang NULL.

    Cũng chuyển các kiểu numpy int/float sang Python native để tránh lỗi
    serialization khi dùng với SQLAlchemy dialect.
    """
    df = df.copy()

    for col in df.columns:
        # Thay thế inf/-inf
        if pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].replace([np.inf, -np.inf], np.nan)

        # Thay NaN/NaT bằng None
        df[col] = df[col].where(df[col].notna(), other=None)

        # Numpy int64/float64 → Python int/float để tránh lỗi JSONB serialization
        if pd.api.types.is_integer_dtype(df[col]):
            df[col] = df[col].apply(
                lambda x: int(x) if x is not None else None
            )
        elif pd.api.types.is_float_dtype(df[col]):
            df[col] = df[col].apply(
                lambda x: float(x) if (x is not None and not math.isnan(x)) else None
            )

    return df


def df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Chuyển DataFrame thành list[dict] đã sanitize, sẵn sàng insert."""
    return sanitize_for_postgres(df).to_dict(orient="records")


def chunk_dataframe(
    df: pd.DataFrame, chunk_size: int
) -> Generator[pd.DataFrame, None, None]:
    """Chia DataFrame thành các chunk nhỏ để bulk insert."""
    for start in range(0, len(df), chunk_size):
        yield df.iloc[start : start + chunk_size]


def build_raw_data(row: pd.Series) -> dict[str, Any]:
    """
    Chuyển một dòng DataFrame thành dict JSON-serializable để lưu vào raw_data JSONB.
    Các giá trị numpy sẽ được chuyển sang kiểu Python native.
    """
    result: dict[str, Any] = {}
    for key, val in row.items():
        if val is None or (isinstance(val, float) and math.isnan(val)):
            result[str(key)] = None
        elif isinstance(val, (np.integer,)):
            result[str(key)] = int(val)
        elif isinstance(val, (np.floating,)):
            result[str(key)] = float(val)
        elif isinstance(val, (np.bool_,)):
            result[str(key)] = bool(val)
        elif hasattr(val, "isoformat"):  # date / datetime
            result[str(key)] = val.isoformat()
        else:
            result[str(key)] = val
    return result
