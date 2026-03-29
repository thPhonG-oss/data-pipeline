"""
Transformer chuẩn hóa giá từ VNDirect finfo-api → schema bảng price_history.

VNDirect trả về JSON fields:
  code      → (bỏ — đã có symbol)
  date      → date       (string 'YYYY-MM-DD')
  open      → open       (×1000 → VND nguyên)
  high      → high       (×1000 → VND nguyên)
  low       → low        (×1000 → VND nguyên)
  close     → close      (×1000 → VND nguyên)
  adClose   → close_adj  (×1000 → VND nguyên, giá điều chỉnh)
  volume    → volume     (cổ phiếu)
  nmVolume  → volume_nm  (khối lượng khớp lệnh thông thường)
  value     → value      (triệu VND — giữ nguyên đơn vị)

Đơn vị giá VNDirect: nghìn VND → nhân ×1000 trước khi lưu.
"""

import math

import pandas as pd

from etl.base.transformer import BaseTransformer
from utils.logger import logger

_PRICE_SCALE = 1000  # VNDirect trả về nghìn VND, cần ×1000


def _to_int(val, scale: int = 1) -> int | None:
    if val is None:
        return None
    try:
        f = float(val) * scale
        return None if (math.isnan(f) or math.isinf(f)) else int(round(f))
    except (TypeError, ValueError):
        return None


class VNDirectPriceTransformer(BaseTransformer):
    """
    Chuyển DataFrame từ VNDirectPriceExtractor → schema price_history.

    Column mapping (VNDirect JSON → price_history):
      date      → date
      open      → open       (×1000)
      high      → high       (×1000)
      low       → low        (×1000)
      close     → close      (×1000)
      adClose   → close_adj  (×1000)
      volume    → volume
      nmVolume  → volume_nm
      value     → value      (giữ nguyên triệu VND)
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        rows = []

        for _, row in df.iterrows():
            raw_date = row.get("date")
            if raw_date is None:
                logger.warning(f"[vndirect_price_tx] {symbol}: thiếu cột date, bỏ qua dòng.")
                continue

            close_val = _to_int(row.get("close"), _PRICE_SCALE)
            if close_val is None:
                logger.warning(f"[vndirect_price_tx] {symbol}: close=None tại {raw_date}, bỏ qua.")
                continue

            rows.append(
                {
                    "symbol": symbol.upper(),
                    "date": pd.to_datetime(raw_date).date(),
                    "open": _to_int(row.get("open"), _PRICE_SCALE),
                    "high": _to_int(row.get("high"), _PRICE_SCALE),
                    "low": _to_int(row.get("low"), _PRICE_SCALE),
                    "close": close_val,
                    "close_adj": _to_int(row.get("adClose"), _PRICE_SCALE),
                    "volume": _to_int(row.get("volume")),
                    "volume_nm": _to_int(row.get("nmVolume")),
                    "value": _to_int(row.get("value")),  # Triệu VND — giữ nguyên
                    "source": "vndirect",
                }
            )

        result = pd.DataFrame(rows)
        logger.info(f"[vndirect_price_tx] {symbol}: transform xong {len(result)} dòng.")
        return result
