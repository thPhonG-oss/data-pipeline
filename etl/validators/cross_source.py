"""
Cross-source validator: So sánh BCTC VCI (trong DB) với KBS (fetch qua vnstock).
Ghi flag vào data_quality_flags khi chênh lệch > DIFF_THRESHOLD.

Đơn vị:
  VCI lưu trong DB: VND nguyên
  KBS qua vnstock Finance: nghìn VND → nhân ×1000 trước khi so sánh

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

# Mapping: tên cột trong DB → item_id tương ứng trong KBS Finance output
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
    "operating_cash_flow": "net_cash_flows_from_operating_activities",
}

# (tên bảng DB, mapping cột DB→KBS item_id, method Finance)
_TABLES = [
    ("balance_sheets",    _BALANCE_SHEET_MAP, "balance_sheet"),
    ("income_statements", _INCOME_STMT_MAP,   "income_statement"),
    ("cash_flows",        _CASHFLOW_MAP,       "cash_flow"),
]


class FinanceCrossValidator:
    """
    Validate BCTC cho 1 symbol: so sánh VCI (DB) với KBS (vnstock).
    Ghi flag vào data_quality_flags. Trả về số flags mới.
    """

    def __init__(self) -> None:
        self._loader = PostgresLoader()

    def validate_symbol(self, symbol: str) -> int:
        """Chạy cross-validate cho tất cả loại BCTC của 1 symbol."""
        total = 0
        for table_name, col_map, finance_method in _TABLES:
            try:
                total += self._validate_table(symbol, table_name, col_map, finance_method)
            except Exception as exc:
                logger.warning(f"[cross_validate] {symbol}/{table_name} lỗi: {exc}")
        return total

    # ── Internal ──────────────────────────────────────────────────────────────

    def _validate_table(
        self,
        symbol: str,
        table_name: str,
        col_map: dict,
        finance_method: str,
    ) -> int:
        df_vci = self._fetch_vci(symbol, table_name)
        if df_vci is None or df_vci.empty:
            return 0

        df_kbs = self._fetch_kbs(symbol, finance_method)
        if df_kbs is None or df_kbs.empty:
            return 0

        return self._compare_and_flag(symbol, table_name, df_vci, df_kbs, col_map)

    def _fetch_vci(self, symbol: str, table: str) -> pd.DataFrame | None:
        """Đọc 3 năm gần nhất từ DB (period_type='year', source='vci')."""
        with engine.connect() as conn:
            rows = conn.execute(
                text(f"""
                    SELECT * FROM {table}
                    WHERE symbol = :sym
                      AND period_type = 'year'
                      AND source = 'vci'
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
        table_name: str,
        df_vci: pd.DataFrame,
        df_kbs: pd.DataFrame,
        col_map: dict,
    ) -> int:
        flags = []
        now = datetime.now(tz=timezone.utc)

        for _, vci_row in df_vci.iterrows():
            period = str(vci_row.get("period", ""))
            # Chỉ so sánh báo cáo năm (period = '2023', '2024'...)
            if len(period) != 4 or not period.isdigit():
                continue
            year_str = period   # KBS dùng '2023', '2024' làm tên cột

            if year_str not in df_kbs.columns:
                continue

            for db_col, kbs_item_id in col_map.items():
                if db_col not in df_vci.columns:
                    continue

                # Tìm dòng KBS theo item_id
                kbs_rows = df_kbs[df_kbs["item_id"] == kbs_item_id]
                if kbs_rows.empty:
                    continue

                v_vci_raw = vci_row.get(db_col)
                v_kbs_raw = kbs_rows.iloc[0][year_str]

                try:
                    v_vci = float(v_vci_raw)
                    v_kbs = float(v_kbs_raw) * _KBS_SCALE   # nghìn VND → VND
                except (TypeError, ValueError):
                    continue

                if v_vci == 0 or pd.isna(v_vci) or pd.isna(v_kbs):
                    continue

                diff_pct = abs(v_vci - v_kbs) / abs(v_vci)
                if diff_pct > _DIFF_THRESHOLD:
                    flags.append({
                        "symbol":      symbol,
                        "table_name":  table_name,
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
            logger.info(f"[cross_validate] {symbol}/{table_name}: Không có dị thường.")
            return 0

        df_flags = pd.DataFrame(flags)
        inserted = self._loader.load(
            df_flags,
            "data_quality_flags",
            ["symbol", "table_name", "period", "column_name", "source_a", "source_b"],
        )
        logger.warning(
            f"[cross_validate] {symbol}/{table_name}: "
            f"{len(flags)} flag(s) — {inserted} mới ghi vào data_quality_flags."
        )
        return inserted
