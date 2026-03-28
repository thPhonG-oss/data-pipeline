"""
Parser báo cáo tài chính — Factory Pattern với 4 mẫu biểu.

Kiến trúc:
    BaseFinancialParser (ABC)
        ├── NonFinancialParser  — ICB không phải 83/84/85
        ├── BankingParser       — ICB 8300
        ├── SecuritiesParser    — ICB 8500
        └── InsuranceParser     — ICB 8400

Mỗi parser:
    - Định nghĩa FIELD_MAPS: {statement_type → {vi_col_name → canonical_col}}
    - Định nghĩa NULL_FIELDS: {statement_type → {canonical fields không áp dụng}}
    - Kế thừa parse(), _apply_mapping(), _build_raw_details() từ base
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from utils.logger import logger


# Tập cột chi phí cần lấy giá trị tuyệt đối
# (API trả về âm, DB lưu dương để dễ tính toán và screener)
_ABS_FIELDS: frozenset[str] = frozenset({
    # Non-financial
    "cost_of_goods_sold",
    "financial_expenses",
    "interest_expense",
    "selling_expenses",
    "admin_expenses",
    "income_tax",
    "capex",
    "debt_repayment",
    "dividends_paid",
    # Banking
    "credit_provision_expense",
    "loan_loss_reserve",
    "operating_expenses",
    # Securities / Insurance
    "net_insurance_claims",
    "insurance_acquisition_costs",
})


class BaseFinancialParser(ABC):
    """
    Lớp cơ sở cho tất cả parser báo cáo tài chính.

    Subclass cần định nghĩa:
        FIELD_MAPS:  dict[statement_type → dict[vi_col → canonical_col]]
        NULL_FIELDS: dict[statement_type → set[canonical_col]]
    """

    FIELD_MAPS: dict[str, dict[str, str]] = {}
    NULL_FIELDS: dict[str, set[str]] = {}

    def __init__(self, statement_type: str) -> None:
        valid = {"balance_sheet", "income_statement", "cash_flow"}
        if statement_type not in valid:
            raise ValueError(
                f"statement_type không hợp lệ: '{statement_type}'. Chọn: {valid}"
            )
        self.statement_type = statement_type

    # ── Public API ────────────────────────────────────────────────────────────

    def parse(self, df: pd.DataFrame, symbol: str) -> list[dict[str, Any]]:
        """
        Parse tất cả kỳ có trong df, trả về list payload dict.

        Args:
            df:     DataFrame thô từ Finance extractor (index = kỳ báo cáo).
                    Tên cột là tiếng Việt đầy đủ dấu.
            symbol: Mã cổ phiếu (đã chuẩn hóa uppercase).

        Returns:
            List dict, mỗi dict là một kỳ báo cáo sẵn sàng load vào financial_reports.
        """
        mapping     = self.FIELD_MAPS.get(self.statement_type, {})
        null_fields = self.NULL_FIELDS.get(self.statement_type, set())
        payloads: list[dict[str, Any]] = []

        for period_label, row in df.iterrows():
            period, period_type = self._parse_period(str(period_label))
            core        = self._apply_mapping(row, mapping, null_fields)
            raw_details = self._build_raw_details(row)

            payload: dict[str, Any] = {
                "symbol":         symbol,
                "period":         period,
                "period_type":    period_type,
                "statement_type": self.statement_type,
                "template":       self._template_name(),
                "source":         "vci",
            }
            payload.update(core)
            payload["raw_details"] = raw_details
            payloads.append(payload)

        logger.debug(
            f"[finance_parsers] {symbol}/{self.statement_type} "
            f"({self._template_name()}): {len(payloads)} kỳ."
        )
        return payloads

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _apply_mapping(
        self,
        row: pd.Series,
        mapping: dict[str, str],
        null_fields: set[str],
    ) -> dict[str, Any]:
        """
        Resolve từng trường canonical từ row dùng mapping dict.

        Thứ tự ưu tiên:
            1. Trong null_fields                → None (không áp dụng cho template)
            2. Cột nguồn có trong row.index     → giá trị số (abs() nếu cần)
            3. Cột nguồn không có trong row     → 0.0   (áp dụng nhưng không báo cáo)
        """
        # reverse: canonical → tên cột tiếng Việt
        reverse: dict[str, str] = {}
        for vi_name, canonical in mapping.items():
            # Không ghi đè nếu đã có (ưu tiên mapping đầu tiên tìm thấy)
            if canonical not in reverse:
                reverse[canonical] = vi_name

        result: dict[str, Any] = {}
        for canonical in set(mapping.values()):
            if canonical in null_fields:
                result[canonical] = None
                continue

            vi_name = reverse.get(canonical)
            if vi_name and vi_name in row.index:
                val = self._to_numeric(row[vi_name])
                if val is not None and canonical in _ABS_FIELDS:
                    val = abs(val)
                result[canonical] = val if val is not None else 0.0
            else:
                result[canonical] = 0.0

        return result

    def _build_raw_details(self, row: pd.Series) -> dict[str, Any]:
        """
        Serialize toàn bộ row thành dict cho raw_details JSONB.

        Giữ lại cột mã thô (isb*, cfb*) để audit trail.
        Chuyển NaN / Inf → None để tránh lỗi JSON serialization.
        """
        raw: dict[str, Any] = {}
        for col, val in row.items():
            col_str = str(col)
            if val is None:
                raw[col_str] = None
            elif isinstance(val, float):
                if math.isnan(val) or math.isinf(val):
                    raw[col_str] = None
                else:
                    raw[col_str] = val
            elif isinstance(val, (int, str, bool)):
                raw[col_str] = val
            else:
                # numpy types, pd.NA, etc.
                try:
                    if pd.isna(val):
                        raw[col_str] = None
                    else:
                        raw[col_str] = str(val)
                except (TypeError, ValueError):
                    raw[col_str] = str(val)
        return raw

    @staticmethod
    def _to_numeric(val: Any) -> float | None:
        """Chuyển về float. Trả None khi giá trị không hợp lệ."""
        if val is None:
            return None
        if isinstance(val, float):
            return None if (math.isnan(val) or math.isinf(val)) else val
        try:
            result = float(val)
            return None if (math.isnan(result) or math.isinf(result)) else result
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_period(label: str) -> tuple[str, str]:
        """
        Phân tích nhãn kỳ báo cáo từ index DataFrame.

        Ví dụ:
            "2024"    → ("2024",   "year")
            "Q1/2024" → ("2024Q1", "quarter")
            "Q4/2023" → ("2023Q4", "quarter")
            "2024-Q1" → ("2024Q1", "quarter")   # vnstock format cũ
        """
        label = label.strip()
        # Format: "Q1/2024"
        if label.startswith("Q") and "/" in label:
            parts   = label.split("/")
            quarter = parts[0]           # "Q1"
            year    = parts[1] if len(parts) > 1 else "0000"
            return f"{year}{quarter}", "quarter"
        # Format: "2024-Q1" (vnstock cũ)
        if "-Q" in label:
            year, q = label.split("-Q", 1)
            return f"{year}Q{q}", "quarter"
        return label, "year"

    @abstractmethod
    def _template_name(self) -> str:
        """Tên template lưu vào cột template trong DB."""


# ── Concrete Parsers ──────────────────────────────────────────────────────────

class NonFinancialParser(BaseFinancialParser):
    """Parser cho doanh nghiệp phi tài chính (sản xuất, bán lẻ, công nghệ...)."""

    # Import lười (lazy) để tránh vòng lặp import khi package khởi động
    from etl.transformers.mappings.non_financial import (
        BALANCE_SHEET_MAP,
        INCOME_STATEMENT_MAP,
        CASH_FLOW_MAP,
    )

    FIELD_MAPS = {
        "balance_sheet":    BALANCE_SHEET_MAP,
        "income_statement": INCOME_STATEMENT_MAP,
        "cash_flow":        CASH_FLOW_MAP,
    }

    NULL_FIELDS: dict[str, set[str]] = {
        # Phi tài chính không có chỉ tiêu nào force NULL
        "balance_sheet":    set(),
        "income_statement": set(),
        "cash_flow":        set(),
    }

    def _template_name(self) -> str:
        return "non_financial"


class BankingParser(BaseFinancialParser):
    """Parser cho ngân hàng thương mại (ICB 8300)."""

    from etl.transformers.mappings.banking import (
        BALANCE_SHEET_MAP,
        INCOME_STATEMENT_MAP,
        CASH_FLOW_MAP,
    )

    FIELD_MAPS = {
        "balance_sheet":    BALANCE_SHEET_MAP,
        "income_statement": INCOME_STATEMENT_MAP,
        "cash_flow":        CASH_FLOW_MAP,
    }

    NULL_FIELDS: dict[str, set[str]] = {
        # Ngân hàng không có hàng tồn kho, GVHB, lợi nhuận gộp → force NULL
        "balance_sheet": {
            "inventory_net", "inventory_gross", "inventory_allowance",
            "ppe_gross", "accumulated_depreciation", "construction_in_progress",
        },
        "income_statement": {
            "cost_of_goods_sold", "gross_profit",
            "selling_expenses", "admin_expenses",
            "gross_revenue",
        },
        # Ngân hàng VN không có dòng "Lưu chuyển tiền từ HDTC" riêng biệt
        "cash_flow": {"cff"},
    }

    def _template_name(self) -> str:
        return "banking"


class SecuritiesParser(BaseFinancialParser):
    """Parser cho công ty chứng khoán (ICB 8500).

    Mapping đã xác nhận với SSI (Finance source='vci').
    """

    from etl.transformers.mappings.securities import (
        BALANCE_SHEET_MAP,
        INCOME_STATEMENT_MAP,
        CASH_FLOW_MAP,
    )

    FIELD_MAPS = {
        "balance_sheet":    BALANCE_SHEET_MAP,
        "income_statement": INCOME_STATEMENT_MAP,
        "cash_flow":        CASH_FLOW_MAP,
    }

    NULL_FIELDS: dict[str, set[str]] = {
        "balance_sheet": {
            "inventory_net", "inventory_gross", "inventory_allowance",
        },
        "income_statement": {
            "cost_of_goods_sold", "gross_profit",
            "ebt",  # CTCK IS không có dòng lợi nhuận trước thuế riêng
        },
        "cash_flow": set(),
    }

    def _template_name(self) -> str:
        return "securities"


class InsuranceParser(BaseFinancialParser):
    """Parser cho công ty bảo hiểm (ICB 8400).

    Mapping đã xác nhận với BVH (Finance source='vci').
    """

    from etl.transformers.mappings.insurance import (
        BALANCE_SHEET_MAP,
        INCOME_STATEMENT_MAP,
        CASH_FLOW_MAP,
    )

    FIELD_MAPS = {
        "balance_sheet":    BALANCE_SHEET_MAP,
        "income_statement": INCOME_STATEMENT_MAP,
        "cash_flow":        CASH_FLOW_MAP,
    }

    NULL_FIELDS: dict[str, set[str]] = {
        "balance_sheet": {
            "inventory_net", "inventory_gross", "inventory_allowance",
        },
        "income_statement": {
            "cost_of_goods_sold", "gross_profit",
        },
        "cash_flow": set(),
    }

    def _template_name(self) -> str:
        return "insurance"
