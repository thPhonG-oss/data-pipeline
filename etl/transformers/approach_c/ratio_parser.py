"""
RatioParser — parse dữ liệu từ Finance(...).ratio() vào fin_financial_ratios.

API trả về DataFrame với cột tiếng Việt, index là số nguyên (không phải period label).
Mỗi row = 1 kỳ báo cáo (year hoặc quarter).

Đặc điểm quan trọng:
    - ROE (%), ROA (%), margins → decimal (0.2763 = 27.63%) — lưu nguyên dạng
    - Banking-only fields = 0.0 cho non-financial → chuyển thành None
    - "Vốn chủ sở hữu" xuất hiện 2 lần → deduplicate trước khi parse
    - "Số CP lưu hành (triệu)" → BIGINT (int, không phải triệu lẻ)
    - "CAR", "Tỷ lệ CASA" → object dtype (có khi là string "N/A") → None nếu không parse được

Đã xác nhận với HPG (non-financial, 39 kỳ × 54 cột).
"""
from __future__ import annotations

import math
from typing import Any

import pandas as pd

from utils.logger import logger

# Mapping tên cột VCI → tên canonical trong fin_financial_ratios
RATIO_MAP: dict[str, str] = {
    # ── Market data ──────────────────────────────────────────────────
    "Số CP lưu hành (triệu)"            : "shares_outstanding_millions",
    "Vốn hóa"                           : "market_cap",
    "Tỷ suất cổ tức (%)"               : "dividend_yield",
    # ── Valuation ─────────────────────────────────────────────────────
    "P/E"                               : "pe_ratio",
    "P/B"                               : "pb_ratio",
    "P/S"                               : "ps_ratio",
    "Giá/ Dòng tiền"                   : "price_to_cf",
    "EV/EBITDA"                         : "ev_to_ebitda",
    # ── Liquidity ─────────────────────────────────────────────────────
    "Hệ số thanh toán tiền"            : "cash_ratio",
    "Hệ số thanh toán nhanh"           : "quick_ratio",
    "Hệ số thanh toán hiện hành"       : "current_ratio",
    # ── Leverage ──────────────────────────────────────────────────────
    "Nợ/Vốn chủ"                       : "debt_to_equity",
    "Đòn bẩy tài chính"               : "financial_leverage",
    # ── Profitability (decimal format: 0.2763 = 27.63%) ───────────────
    "ROE (%)"                           : "roe",
    "ROA (%)"                           : "roa",
    "ROIC"                              : "roic",
    "Biên LN gộp (%)"                 : "gross_margin",
    "Biên EBIT (%)"                    : "ebit_margin",
    "Biên LN trước thuế (%)"          : "pre_tax_margin",
    "Biên LN sau thuế (%)"            : "net_margin",
    # ── Activity ──────────────────────────────────────────────────────
    "Vòng quay tài sản"               : "asset_turnover",
    "Vòng quay TS cố định"            : "fixed_asset_turnover",
    "Số ngày phải thu"                : "days_receivable",
    "Số ngày tồn kho"                 : "days_inventory",
    "Số ngày phải trả"                : "days_payable",
    "Chu kỳ tiền"                     : "cash_cycle",
    # ── Absolute values ───────────────────────────────────────────────
    "EBIT"                              : "ebit",
    "EBITDA"                            : "ebitda",
    # ── Banking-specific (NULL cho non-financial/securities/insurance) ─
    "Biên lãi thuần"                  : "nim",
    "Lãi suất bình quân tài sản sinh lãi": "avg_earning_asset_yield",
    "Chi phí vốn bình quân"           : "avg_cost_of_funds",
    "Thu nhập ngoài lãi"              : "non_interest_income_ratio",
    "CIR"                               : "cir",
    "CAR"                               : "car",
    "LDR (%)"                           : "ldr",
    "Nợ xấu (%)"                       : "npl_ratio",
    "DP rủi ro/Nợ xấu"               : "npl_coverage",
    "DP rủi ro/Cho vay"               : "provision_to_loans",
    "Tăng trưởng cho vay (%)"         : "loan_growth",
    "Tăng trưởng tiền gửi (%)"        : "deposit_growth",
    "Vốn chủ/Tổng tài sản"           : "equity_to_assets",
    "Tỷ lệ CASA"                      : "casa_ratio",
}

# Tập canonical fields chỉ có ý nghĩa cho ngân hàng — non-fin = 0.0 → None
_BANKING_ONLY_FIELDS: frozenset[str] = frozenset({
    "nim", "avg_earning_asset_yield", "avg_cost_of_funds", "non_interest_income_ratio",
    "cir", "car", "ldr", "npl_ratio", "npl_coverage", "provision_to_loans",
    "loan_growth", "deposit_growth", "equity_to_assets", "casa_ratio",
})


def _to_numeric(val: Any) -> float | None:
    """Chuyển về float. Trả None khi NaN / Inf / không parse được."""
    if val is None:
        return None
    if isinstance(val, float):
        return None if (math.isnan(val) or math.isinf(val)) else val
    if isinstance(val, int):
        return float(val)
    try:
        result = float(val)
        return None if (math.isnan(result) or math.isinf(result)) else result
    except (ValueError, TypeError):
        return None


def _build_raw(row: pd.Series) -> dict[str, Any]:
    """Serialize row thành dict cho raw_details JSONB."""
    raw: dict[str, Any] = {}
    for col, val in row.items():
        col_str = str(col)
        if val is None:
            raw[col_str] = None
        elif isinstance(val, float):
            raw[col_str] = None if (math.isnan(val) or math.isinf(val)) else val
        elif isinstance(val, (int, str, bool)):
            raw[col_str] = val
        else:
            try:
                raw[col_str] = None if pd.isna(val) else str(val)
            except (TypeError, ValueError):
                raw[col_str] = str(val)
    return raw


class RatioParser:
    """
    Parser cho dữ liệu Finance(...).ratio() → fin_financial_ratios.

    Cách dùng:
        parser = RatioParser()
        payloads = parser.parse(df_ratio, symbol="HPG", icb_code="10101010")
        # → list[dict] sẵn sàng load vào fin_financial_ratios
    """

    def parse(
        self,
        df: pd.DataFrame,
        symbol: str,
        icb_code: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Parse DataFrame ratio → list payload dict cho fin_financial_ratios.

        Args:
            df:       DataFrame từ Finance(...).ratio(lang='vi').
                      Cột bao gồm: "Kỳ báo cáo", "Năm", "Quý", + ratio columns.
            symbol:   Mã cổ phiếu (uppercase).
            icb_code: Mã ICB của công ty — lưu vào payload để tránh JOIN khi query.

        Returns:
            List dict, mỗi dict là 1 kỳ báo cáo.
        """
        if df.empty:
            return []

        # Derive template từ icb_code (dùng cùng routing logic với FinanceParserFactory)
        from etl.transformers.finance_factory import FinanceParserFactory
        template = FinanceParserFactory.template_for_icb(icb_code)

        # Deduplicate columns (VCI ratio có "Vốn chủ sở hữu" x2)
        df = df.loc[:, ~df.columns.duplicated(keep="first")]

        payloads: list[dict[str, Any]] = []

        for _, row in df.iterrows():
            period_type_raw = str(row.get("Kỳ báo cáo", "")).strip().lower()
            year_raw        = str(row.get("Năm", "")).strip()
            quarter_raw     = row.get("Quý", None)

            # Bỏ qua row không có năm hợp lệ
            if not year_raw or year_raw in ("nan", "None", ""):
                continue

            if period_type_raw == "quarter" and quarter_raw is not None:
                try:
                    quarter_int = int(quarter_raw)
                    period      = f"{year_raw}Q{quarter_int}"
                    period_type = "quarter"
                except (ValueError, TypeError):
                    continue
            else:
                period      = year_raw
                period_type = "year"

            payload: dict[str, Any] = {
                "symbol":      symbol,
                "period":      period,
                "period_type": period_type,
                "source":      "vci",
                "icb_code":    icb_code,
                "template":    template,
            }

            for vi_name, canonical in RATIO_MAP.items():
                if vi_name in df.columns:
                    val = _to_numeric(row.get(vi_name))
                    # Banking-only: nếu = 0.0 chính xác → None (không phải số thực)
                    if val == 0.0 and canonical in _BANKING_ONLY_FIELDS:
                        val = None
                    payload[canonical] = val
                else:
                    payload[canonical] = None

            # shares_outstanding_millions là int
            som = payload.get("shares_outstanding_millions")
            if som is not None:
                payload["shares_outstanding_millions"] = int(som)

            payload["raw_details"] = _build_raw(row)
            payloads.append(payload)

        logger.debug(
            f"[ratio_parser] {symbol}: {len(payloads)} kỳ → fin_financial_ratios."
        )
        return payloads
