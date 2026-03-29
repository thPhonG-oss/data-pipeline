"""Transformer cho dữ liệu trading: ratio_summary."""
import json
import math
from datetime import UTC, datetime, timezone

import pandas as pd

from etl.base.transformer import BaseTransformer
from utils.logger import logger

# Đổi tên cột API → tên cột schema DB
_RENAME_MAP: dict[str, str] = {
    "de":            "debt_to_equity",
    "at":            "asset_turnover",
    "fat":           "fixed_asset_turnover",
    "dso":           "receivable_days",
    "dpo":           "payable_days",
    "ccc":           "cash_conversion_cycle",
    "ev_per_ebitda": "ev_ebitda",
}

# Cột lưu vào BIGINT (giá trị tiền, đơn vị đồng)
_BIGINT_COLS = [
    "revenue", "net_profit", "ev", "ebitda", "ebit",
    "issue_share", "charter_capital",
]

# Cột lưu vào NUMERIC (tỷ lệ, hệ số, chỉ số)
_FLOAT_COLS = [
    "revenue_growth", "net_profit_growth", "ebit_margin",
    "roe", "roic", "roa",
    "pe", "pb", "ps", "pcf",
    "eps", "eps_ttm", "bvps",
    "current_ratio", "quick_ratio", "cash_ratio", "interest_coverage",
    "debt_to_equity", "net_profit_margin", "gross_margin",
    "ev_ebitda", "asset_turnover", "fixed_asset_turnover",
    "receivable_days", "payable_days", "cash_conversion_cycle",
    "dividend",
]

# Cột không có trong schema DB → gom vào extra_metrics JSONB
_EXTRA_COLS = [
    "ae", "fae", "le",
    "rtq4", "rtq10", "rtq17",
    "charter_capital_ratio", "acp",
    "length_report", "update_date",
]

# Cột có trong schema DB (sau khi đổi tên)
_DB_COLS = [
    "symbol", "year_report", "quarter_report",
    "revenue", "revenue_growth",
    "net_profit", "net_profit_growth",
    "ebit_margin", "roe", "roa", "roic",
    "pe", "pb", "ps", "pcf",
    "eps", "eps_ttm", "bvps",
    "current_ratio", "quick_ratio", "cash_ratio", "interest_coverage",
    "debt_to_equity", "net_profit_margin", "gross_margin",
    "ev", "ev_ebitda", "ebitda", "ebit",
    "asset_turnover", "fixed_asset_turnover",
    "receivable_days", "inventory_days", "payable_days", "cash_conversion_cycle",
    "dividend", "issue_share", "charter_capital",
    "extra_metrics", "fetched_at",
]


def _to_int_or_none(val) -> int | None:
    """Chuyển giá trị sang int, trả None nếu null hoặc không hợp lệ."""
    if val is None:
        return None
    try:
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return int(val)
    except (TypeError, ValueError):
        return None


def _to_float_or_none(val) -> float | None:
    """Chuyển giá trị sang float, trả None nếu null hoặc không hợp lệ."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


# NUMERIC(10,4): tổng 10 chữ số, 4 sau dấu thập phân → max 6 chữ số trước = 999999.9999
_NUMERIC_10_4_MAX = 999_999.9999


def _to_float_bounded(val) -> float | None:
    """Như _to_float_or_none nhưng trả None nếu vượt giới hạn NUMERIC(10,4).
    Dùng cho các cột tỷ số (pe, pb, roe...) — giá trị cực đoan không có ý nghĩa."""
    f = _to_float_or_none(val)
    if f is None:
        return None
    return None if abs(f) > _NUMERIC_10_4_MAX else f


def _build_extra_metrics(row: pd.Series, extra_cols: list[str]) -> dict | None:
    """Gom các cột không có trong schema thành dict cho extra_metrics JSONB."""
    result: dict = {}
    for col in extra_cols:
        if col not in row.index:
            continue
        val = row[col]
        if val is None:
            continue
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            continue
        # Chuyển numpy types sang Python native để JSON serializable
        if hasattr(val, "item"):
            val = val.item()
        result[col] = val
    return result if result else None


class TradingTransformer(BaseTransformer):
    """
    Chuẩn hóa DataFrame thô từ TradingExtractor thành format sẵn sàng upsert
    vào bảng ratio_summary.
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        """Alias cho transform_ratio_summary() — tương thích BaseTransformer interface."""
        return self.transform_ratio_summary(df, symbol)

    def transform_ratio_summary(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Chuyển DataFrame thô từ Company.ratio_summary() sang schema ratio_summary.

        Các bước:
        1. Đổi tên cột theo _RENAME_MAP
        2. Thêm symbol và quarter_report=None
        3. Ép kiểu BIGINT và NUMERIC
        4. Gom cột lạ vào extra_metrics JSONB
        5. drop_duplicates trên conflict key
        6. Giữ đúng cột trong _DB_COLS
        """
        df = df.copy()

        # 1. Đổi tên cột
        df.rename(columns=_RENAME_MAP, inplace=True)

        # 2. Thêm các cột bắt buộc
        df["symbol"] = symbol
        df["quarter_report"] = 0      # 0 = annual snapshot; NULL không dùng được làm conflict key
        df["inventory_days"] = None    # API không cung cấp trực tiếp
        df["fetched_at"] = datetime.now(tz=UTC)

        # 3. Ép kiểu BIGINT
        for col in _BIGINT_COLS:
            if col in df.columns:
                df[col] = df[col].apply(_to_int_or_none)

        # 4. Ép kiểu NUMERIC (float) — dùng bounded để tránh NUMERIC(10,4) overflow
        for col in _FLOAT_COLS:
            if col in df.columns:
                df[col] = df[col].apply(_to_float_bounded)

        # 5. Ép kiểu year_report → int
        if "year_report" in df.columns:
            df["year_report"] = df["year_report"].apply(_to_int_or_none)

        # 6. Xây dựng extra_metrics từ các cột không có trong schema
        present_extra = [c for c in _EXTRA_COLS if c in df.columns]
        if present_extra:
            df["extra_metrics"] = df.apply(
                lambda row: _build_extra_metrics(row, present_extra), axis=1
            )
        else:
            df["extra_metrics"] = None

        # 7. Loại dòng thiếu conflict key
        df = df.dropna(subset=["symbol", "year_report"])

        # 8. Deduplicate conflict key — tránh CardinalityViolation
        df = df.drop_duplicates(
            subset=["symbol", "year_report", "quarter_report"], keep="last"
        )

        # 9. Chỉ giữ cột có trong schema DB (bỏ cột dư)
        final_cols = [c for c in _DB_COLS if c in df.columns]
        df = df[final_cols]

        logger.info(f"[ratio_summary] {symbol}: {len(df)} dòng sau transform.")
        return df.reset_index(drop=True)
