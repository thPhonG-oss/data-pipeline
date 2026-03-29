"""
Cross-source validator: So sánh BCTC VCI (trong DB) với KBS (fetch qua vnstock).
Ghi flag vào data_quality_flags khi chênh lệch > DIFF_THRESHOLD.

Nguồn dữ liệu DB: 4 bảng Approach C (fin_balance_sheet, fin_income_statement, fin_cash_flow).

Đơn vị:
  VCI lưu trong Approach C tables: VND nguyên (NUMERIC(20,2))
  KBS qua vnstock Finance:         nghìn VND → nhân ×1000 trước khi so sánh

Cách so sánh:
  diff_pct = |VCI - KBS*1000| / |VCI| × 100
  Flag khi diff_pct > 2%
"""
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import text

from db.connection import engine
from etl.loaders.postgres import PostgresLoader
from utils.logger import logger

_DIFF_THRESHOLD = 0.02   # 2%
_KBS_SCALE = 1000        # KBS trả về nghìn VND → nhân ×1000 để ra VND nguyên

# Mapping: canonical column trong financial_reports → item_id KBS Finance
_BALANCE_SHEET_MAP = {
    "total_assets":      "total_assets",
    "total_liabilities": "a.liabilities",
    "total_equity":      "b.owners_equity",
}

_INCOME_STMT_MAP = {
    "net_revenue":  "n_3.net_revenue",
    "gross_profit": "n_5.gross_profit",
    "net_profit":   "profit_after_tax_for_shareholders_of_parent_company",
}

_CASHFLOW_MAP = {
    "cfo": "net_cash_flows_from_operating_activities",
}

# Approach C: mapping statement_type → tên bảng DB
_TABLE_MAP = {
    "balance_sheet":    "fin_balance_sheet",
    "income_statement": "fin_income_statement",
    "cash_flow":        "fin_cash_flow",
}

# (statement_type, mapping cột DB→KBS item_id, method Finance KBS)
_STATEMENTS = [
    ("balance_sheet",    _BALANCE_SHEET_MAP, "balance_sheet"),
    ("income_statement", _INCOME_STMT_MAP,   "income_statement"),
    ("cash_flow",        _CASHFLOW_MAP,      "cash_flow"),
]


class FinanceCrossValidator:
    """
    Validate BCTC cho 1 symbol: so sánh VCI (financial_reports) với KBS (vnstock).
    Ghi flag vào data_quality_flags. Trả về số flags mới.
    """

    def __init__(self) -> None:
        self._loader = PostgresLoader()

    def validate_symbol(self, symbol: str) -> int:
        """Chạy cross-validate cho tất cả loại BCTC của 1 symbol."""
        total = 0
        for stmt_type, col_map, finance_method in _STATEMENTS:
            try:
                total += self._validate_statement(symbol, stmt_type, col_map, finance_method)
            except Exception as exc:
                logger.warning(f"[cross_validate] {symbol}/{stmt_type} lỗi: {exc}")
        return total

    # ── Internal ──────────────────────────────────────────────────────────────

    def _validate_statement(
        self,
        symbol: str,
        stmt_type: str,
        col_map: dict,
        finance_method: str,
    ) -> int:
        df_vci = self._fetch_vci(symbol, stmt_type)
        if df_vci is None or df_vci.empty:
            return 0

        df_kbs = self._fetch_kbs(symbol, finance_method)
        if df_kbs is None or df_kbs.empty:
            return 0

        return self._compare_and_flag(symbol, stmt_type, df_vci, df_kbs, col_map)

    def _fetch_vci(self, symbol: str, stmt_type: str) -> pd.DataFrame | None:
        """Đọc 3 năm gần nhất từ bảng Approach C tương ứng (period_type='year', source='vci')."""
        table = _TABLE_MAP[stmt_type]
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT * FROM {table}
                    WHERE symbol      = :sym
                      AND period_type = 'year'
                      AND source      = 'vci'
                    ORDER BY period DESC
                    LIMIT 3
                """),
                {"sym": symbol},
            ).fetchall()
        if not rows:
            return None
        return pd.DataFrame(rows, columns=list(rows[0]._fields))

    def _fetch_kbs(self, symbol: str, finance_method: str) -> pd.DataFrame | None:
        """
        Lấy BCTC từ KBS qua vnstock Finance.
        Trả về DataFrame dạng rộng: rows=items (có cột item_id), cols=years.
        """
        try:
            from vnstock import Finance
            df = getattr(
                Finance(source="kbs", symbol=symbol),
                finance_method,
            )(period="year", lang="en")
            return df if df is not None and not df.empty else None
        except Exception as exc:
            logger.warning(f"[cross_validate] {symbol} KBS {finance_method} lỗi: {exc}")
            return None

    def _compare_and_flag(
        self,
        symbol: str,
        stmt_type: str,
        df_vci: pd.DataFrame,
        df_kbs: pd.DataFrame,
        col_map: dict,
    ) -> int:
        flags = []
        now = datetime.now(tz=timezone.utc)

        for _, vci_row in df_vci.iterrows():
            period = str(vci_row.get("period", ""))
            if len(period) != 4 or not period.isdigit():
                continue
            year_str = period

            if year_str not in df_kbs.columns:
                continue

            for db_col, kbs_item_id in col_map.items():
                if db_col not in df_vci.columns:
                    continue

                kbs_rows = df_kbs[df_kbs["item_id"] == kbs_item_id]
                if kbs_rows.empty:
                    continue

                v_vci_raw = vci_row.get(db_col)
                v_kbs_raw = kbs_rows.iloc[0][year_str]

                try:
                    v_vci = float(v_vci_raw)
                    v_kbs = float(v_kbs_raw) * _KBS_SCALE
                except (TypeError, ValueError):
                    continue

                if v_vci == 0 or pd.isna(v_vci) or pd.isna(v_kbs):
                    continue

                diff_pct = abs(v_vci - v_kbs) / abs(v_vci)
                if diff_pct > _DIFF_THRESHOLD:
                    flags.append({
                        "symbol":      symbol,
                        "table_name":  _TABLE_MAP[stmt_type],
                        "period":      period,
                        "column_name": db_col,
                        "source_a":    "vci",
                        "value_a":     round(v_vci, 4),
                        "source_b":    "kbs",
                        "value_b":     round(v_kbs, 4),
                        "diff_pct":    round(diff_pct * 100, 4),
                        "flagged_at":  now,
                    })

        if not flags:
            logger.info(f"[cross_validate] {symbol}/{stmt_type}: Không có dị thường.")
            return 0

        df_flags = pd.DataFrame(flags)
        inserted = self._loader.load(
            df_flags,
            "data_quality_flags",
            ["symbol", "table_name", "period", "column_name", "source_a", "source_b"],
        )
        logger.warning(
            f"[cross_validate] {symbol}/{stmt_type}: "
            f"{len(flags)} flag(s) — {inserted} mới ghi vào data_quality_flags."
        )
        return inserted
