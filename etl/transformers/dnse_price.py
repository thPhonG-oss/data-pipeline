"""
Transformer chuẩn hóa giá từ KBS (qua vnstock) → schema bảng price_history.

vnstock Quote(source='kbs').history() trả về DataFrame với columns:
  time   → date       (datetime → date)
  open   → open       (INTEGER VND)
  high   → high       (INTEGER VND)
  low    → low        (INTEGER VND)
  close  → close      (INTEGER VND)
  volume → volume     (BIGINT)

Lưu ý:
  - KBS trả về nghìn VND (vd: 20.78 = 20,780 đồng) → _NEEDS_SCALE = True
  - Không có adjusted close → close_adj = NULL
"""
import math

import pandas as pd

from etl.base.transformer import BaseTransformer
from utils.logger import logger

# KBS trả về nghìn VND → cần nhân ×1000 để ra VND nguyên
_NEEDS_SCALE = True


def _to_int(val, scale: int = 1) -> int | None:
    if val is None:
        return None
    try:
        f = float(val) * scale
        return None if (math.isnan(f) or math.isinf(f)) else int(round(f))
    except (TypeError, ValueError):
        return None


class DNSEPriceTransformer(BaseTransformer):
    """
    Chuyển DataFrame từ DNSEPriceExtractor → schema price_history.

    Column mapping (vnstock DNSE → price_history):
      time   → date
      open   → open
      high   → high
      low    → low
      close  → close
      volume → volume
      (không có) → close_adj = NULL
      (không có) → volume_nm = NULL
      (không có) → value = NULL
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        scale = 1000 if _NEEDS_SCALE else 1
        rows = []

        for _, row in df.iterrows():
            # Xử lý cột ngày — vnstock DNSE thường trả về 'time'
            raw_date = row.get("time") or row.get("date")
            if raw_date is None:
                logger.warning(f"[dnse_price_tx] {symbol}: thiếu cột date, bỏ qua dòng.")
                continue

            close_val = _to_int(row.get("close"), scale)
            if close_val is None:
                logger.warning(f"[dnse_price_tx] {symbol}: close=None tại {raw_date}, bỏ qua.")
                continue

            rows.append({
                "symbol":    symbol.upper(),
                "date":      pd.to_datetime(raw_date).date(),
                "open":      _to_int(row.get("open"), scale),
                "high":      _to_int(row.get("high"), scale),
                "low":       _to_int(row.get("low"), scale),
                "close":     close_val,
                "close_adj": None,       # DNSE không cung cấp adjusted close
                "volume":    _to_int(row.get("volume")),
                "volume_nm": None,       # Chỉ có từ VNDirect
                "value":     None,       # Chỉ có từ VNDirect
                "source":    "kbs",
            })

        result = pd.DataFrame(rows)
        logger.info(f"[dnse_price_tx] {symbol}: transform xong {len(result)} dòng.")
        return result
