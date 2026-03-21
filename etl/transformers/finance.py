"""Transformer cho 4 loại báo cáo tài chính."""
import pandas as pd

from etl.base.transformer import BaseTransformer
from etl.loaders.helpers import build_raw_data
from utils.logger import logger

# ── Column maps: tên cột tiếng Việt từ API → tên cột schema ──────────────────

_BS_COL_MAP = {
    "Tiền và tương đương tiền":        "cash_and_equivalents",
    "Đầu tư ngắn hạn":                 "short_term_investments",
    "Các khoản phải thu":              "accounts_receivable",
    "Hàng tồn kho, ròng":             "inventory",
    "Tài sản lưu động khác":           "other_current_assets",
    "TÀI SẢN NGẮN HẠN":               "total_current_assets",
    "Phải thu dài hạn":                "long_term_receivables",
    "Tài sản cố định":                 "fixed_assets",
    "Giá trị ròng tài sản đầu tư":    "investment_properties",
    "Đầu tư dài hạn":                  "long_term_investments",
    "GTCL tài sản cố định vô hình":   "intangible_assets",
    "Tài sản dài hạn khác":            "other_long_term_assets",
    "TÀI SẢN DÀI HẠN":                "total_long_term_assets",
    "TỔNG CỘNG TÀI SẢN":              "total_assets",
    "Vay ngắn hạn":                    "short_term_debt",
    "Phải trả người bán":              "accounts_payable",
    "Người mua trả tiền trước":        "advances_from_customers",
    "Phải trả khác":                   "other_current_liabilities",
    "Nợ ngắn hạn":                     "total_current_liabilities",
    "Vay dài hạn":                     "long_term_debt",
    "Phải trả dài hạn khác":          "other_long_term_liabilities",
    "Nợ dài hạn":                      "total_long_term_liabilities",
    "NỢ PHẢI TRẢ":                    "total_liabilities",
    "Vốn góp":                         "charter_capital_fs",
    "Thặng dư vốn cổ phần":           "share_premium",
    "Lãi chưa phân phối":             "retained_earnings",
    "Vốn khác":                        "other_equity",
    "Lợi ích cổ đông không kiểm soát": "minority_interest",
    "Vốn chủ sở hữu":                 "total_equity",
    "Tổng cộng nguồn vốn":            "total_liabilities_equity",
}

_IS_COL_MAP = {
    "Doanh thu bán hàng và cung cấp dịch vụ": "gross_revenue",
    "Các khoản giảm trừ doanh thu":           "revenue_deductions",
    "Doanh thu thuần":                        "net_revenue",
    "Giá vốn hàng bán":                      "cogs",
    "Lợi nhuận gộp":                         "gross_profit",
    "Doanh thu hoạt động tài chính":         "financial_income",
    "Chi phí tài chính":                     "financial_expense",
    "Chi phí lãi vay":                       "interest_expense",
    "Chi phí bán hàng":                      "selling_expense",
    "Chi phí quản lý doanh nghiệp":          "admin_expense",
    "Lãi/(lỗ) từ hoạt động kinh doanh":     "operating_profit",
    "Thu nhập khác":                         "other_income",
    "Chi phí khác":                          "other_expense",
    "Lãi/(lỗ) từ công ty liên doanh":       "profit_from_associates",
    "Lãi/(lỗ) trước thuế":                  "ebt",
    "Chi phí thuế thu nhập doanh nghiệp":   "income_tax",
    "Lãi/(lỗ) thuần sau thuế":              "profit_after_tax",
    "Lợi ích của cổ đông thiểu số":         "minority_profit",
    "Lợi nhuận của Cổ đông của Công ty mẹ": "net_profit",
    "Lãi cơ bản trên cổ phiếu (VND)":      "eps_basic",
    "Lãi trên cổ phiếu pha loãng (VND)":   "eps_diluted",
}

_CF_COL_MAP = {
    "Lợi nhuận/(lỗ) trước thuế":                                                           "net_profit_before_tax",
    "Khấu hao TSCĐ và BĐSĐT":                                                             "depreciation",
    "Chi phí dự phòng":                                                                    "provision",
    "Lãi/lỗ chênh lệch tỷ giá hối đoái do đánh giá lại các khoản mục tiền tệ có gốc ngoại tệ": "unrealized_fx_gain_loss",
    "(Lãi)/lỗ từ hoạt động đầu tư":                                                       "investment_income",
    "Chi phí lãi vay":                                                                     "interest_expense_cf",
    "(Tăng)/giảm các khoản phải thu":                                                      "change_in_receivables",
    "(Tăng)/giảm hàng tồn kho":                                                           "change_in_inventory",
    "Tăng/(giảm) các khoản phải trả":                                                     "change_in_payables",
    "(Tăng)/giảm chi phí trả trước":                                                       "other_operating_changes",
    "Thuế thu nhập doanh nghiệp đã nộp":                                                   "income_tax_paid",
    "Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh":                       "operating_cash_flow",
    "Tiền chi để mua sắm, xây dựng TSCĐ và các tài sản dài hạn khác":                    "capex",
    "Tiền thu từ thanh lý, nhượng bán TSCĐ và các tài sản dài hạn khác":                 "proceeds_from_asset_disposal",
    "Tiền chi đầu tư góp vốn vào đơn vị khác":                                            "investment_purchases",
    "Tiền thu hồi đầu tư góp vốn vào đơn vị khác":                                       "investment_proceeds",
    "Tiền thu lãi cho vay, cổ tức và lợi nhuận được chia":                                "interest_and_dividends_received",
    "Lưu chuyển tiền thuần từ hoạt động đầu tư":                                          "investing_cash_flow",
    "Tiền thu được các khoản đi vay":                                                      "proceeds_from_borrowings",
    "Tiền trả nợ gốc vay":                                                                 "repayment_of_borrowings",
    "Tiền thu từ phát hành cổ phiếu, nhận vốn góp của chủ sở hữu":                       "proceeds_from_equity_issuance",
    "Cổ tức, lợi nhuận đã trả cho chủ sở hữu":                                           "dividends_paid",
    "Lưu chuyển tiền thuần từ hoạt động tài chính":                                       "financing_cash_flow",
    "Lưu chuyển tiền thuần trong kỳ":                                                      "net_cash_change",
    "Tiền và tương đương tiền đầu kỳ":                                                     "beginning_cash",
    "Tiền và tương đương tiền cuối kỳ":                                                    "ending_cash",
}

_RATIO_COL_MAP = {
    "P/E":                    "pe",
    "P/B":                    "pb",
    "P/S":                    "ps",
    "Giá/ Dòng tiền":        "pcf",
    "EV/EBITDA":              "ev_ebitda",
    "ROE (%)":                "roe",
    "ROA (%)":                "roa",
    "ROIC":                   "roic",
    "Biên LN gộp (%)":       "gross_margin",
    "Biên EBIT (%)":         "ebit_margin",
    "Biên LN sau thuế (%)":  "net_profit_margin",
    "EBITDA":                 "ebitda",
    "EBIT":                   "ebit",
    "Hệ số thanh toán tiền":  "cash_ratio",
    "Hệ số thanh toán nhanh": "quick_ratio",
    "Hệ số thanh toán hiện hành": "current_ratio",
    "Nợ/Vốn chủ":            "debt_to_equity",
    "Đòn bẩy tài chính":     "financial_leverage",
    "Số ngày phải thu":       "receivable_days",
    "Số ngày tồn kho":        "inventory_days",
    "Số ngày phải trả":       "payable_days",
    "Chu kỳ tiền":            "cash_conversion_cycle",
    "Vòng quay tài sản":      "asset_turnover",
    "Vòng quay TS cố định":   "fixed_asset_turnover",
    "Nợ xấu (%)":             "npl_ratio",
    "LDR (%)":                "ldr",
    "CAR":                    "car",
    "Biên lãi thuần":         "nim",
}

# Cột metadata — không đưa vào raw_data
_META_COLS = {"report_period", "Mã CP", "Kỳ báo cáo", "Năm", "Quý",
              "Mã TTM", "Loại tỷ lệ", "Mã năm tỷ lệ"}


_INT64_MAX = 9_223_372_036_854_775_807
_INT64_MIN = -9_223_372_036_854_775_808


def _safe_int64(x):
    """Convert float to int safely, returning pd.NA for NaN or out-of-range values."""
    if pd.isna(x):
        return pd.NA
    try:
        i = int(x)  # int() is exact; avoids float64 precision issues near BIGINT_MAX
        return i if _INT64_MIN <= i <= _INT64_MAX else pd.NA
    except (OverflowError, ValueError):
        return pd.NA


def _parse_period(raw: str) -> tuple[str, str]:
    """
    Chuyển đổi index kỳ báo cáo sang (period, period_type).
        '2024'    → ('2024',   'year')
        '2024-Q1' → ('2024Q1', 'quarter')
    """
    raw = str(raw).strip()
    if "-Q" in raw:
        year, q = raw.split("-Q", 1)
        return f"{year}Q{q}", "quarter"
    return raw, "year"


class FinanceTransformer(BaseTransformer):
    """
    Chuẩn hóa DataFrame thô từ FinanceExtractor.

    - transform_balance_sheet(df, symbol)   → DataFrame cho balance_sheets
    - transform_income_statement(df, symbol) → DataFrame cho income_statements
    - transform_cash_flow(df, symbol)       → DataFrame cho cash_flows
    - transform_ratio(df, symbol)           → DataFrame cho financial_ratios
    - transform(df, symbol, report_type)    → dispatch theo report_type
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        report_type = context.get("report_type", "balance_sheet")
        dispatch = {
            "balance_sheet":    self.transform_balance_sheet,
            "income_statement": self.transform_income_statement,
            "cash_flow":        self.transform_cash_flow,
            "ratio":            self.transform_ratio,
        }
        return dispatch[report_type](df, symbol)

    # ── Core helper ───────────────────────────────────────────────────────────

    def _base_transform(
        self,
        df: pd.DataFrame,
        symbol: str,
        col_map: dict[str, str],
        schema_cols: list[str],
        has_raw_data: bool = True,
    ) -> pd.DataFrame:
        """
        Logic chung cho tất cả report types:
        1. Reset index → lấy kỳ báo cáo
        2. Parse period + period_type từ index
        3. Build raw_data từ tất cả cột dữ liệu
        4. Rename cột theo col_map
        5. Chọn cột schema, ép kiểu số → int (BIGINT) / float (NUMERIC)
        """
        df = df.copy()

        # 1. Lấy period từ index
        df["_period_raw"] = df.index.astype(str)
        df[["period", "period_type"]] = pd.DataFrame(
            df["_period_raw"].map(_parse_period).tolist(),
            index=df.index,
        )

        # 2. Symbol — dùng tham số input để đảm bảo khớp FK với bảng companies
        # (Mã CP từ VCI API có thể trả về mã khác với ticker chuẩn)
        df["symbol"] = symbol

        # 3. raw_data — serialize tất cả cột dữ liệu gốc (trừ meta)
        if has_raw_data:
            data_cols = [c for c in df.columns if c not in _META_COLS and not c.startswith("_")]
            df["raw_data"] = df[data_cols].apply(
                lambda row: build_raw_data(row), axis=1
            )

        df["source"] = self._source_from_df(df)

        # 4. Rename
        df = df.rename(columns=col_map)

        # 5. Chọn cột schema
        final_cols = ["symbol", "period", "period_type"] + schema_cols
        if has_raw_data:
            final_cols += ["raw_data"]
        final_cols += ["source"]

        for col in final_cols:
            if col not in df.columns:
                df[col] = None

        df = df[final_cols]

        # Deduplicate columns — insurance companies may produce duplicate names after rename
        if df.columns.duplicated().any():
            df = df.loc[:, ~df.columns.duplicated(keep="first")]

        # 6. Ép kiểu: số lớn → int nullable (BIGINT), float → float
        bigint_cols = [c for c in schema_cols if c in _BIGINT_COLS]
        float_cols  = [c for c in schema_cols if c in _FLOAT_COLS]

        for col in bigint_cols:
            s = pd.to_numeric(df[col], errors="coerce").replace([float("inf"), float("-inf")], None)
            df[col] = pd.array(s.apply(_safe_int64), dtype="Int64")

        for col in float_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Float64")

        # 7. Loại dòng toàn null (trừ symbol/period)
        value_cols = [c for c in schema_cols if c not in ("source",)]
        before = len(df)
        df = df.dropna(subset=value_cols, how="all")
        dropped = before - len(df)
        if dropped:
            logger.debug(f"[{symbol}] Bỏ {dropped} dòng toàn null.")

        return df.reset_index(drop=True)

    def _source_from_df(self, df: pd.DataFrame) -> str:
        """Lấy nguồn từ metadata nếu có, mặc định 'vci'."""
        return "vci"

    # ── Public transform methods ──────────────────────────────────────────────

    def transform_balance_sheet(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        result = self._base_transform(df, symbol, _BS_COL_MAP, _BS_SCHEMA_COLS)
        logger.info(f"[balance_sheets] {symbol}: {len(result)} kỳ sau transform.")
        return result

    def transform_income_statement(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        result = self._base_transform(df, symbol, _IS_COL_MAP, _IS_SCHEMA_COLS)
        logger.info(f"[income_statements] {symbol}: {len(result)} kỳ sau transform.")
        return result

    def transform_cash_flow(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        result = self._base_transform(df, symbol, _CF_COL_MAP, _CF_SCHEMA_COLS)
        logger.info(f"[cash_flows] {symbol}: {len(result)} kỳ sau transform.")
        return result

    def transform_ratio(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        result = self._base_transform(
            df, symbol, _RATIO_COL_MAP, _RATIO_SCHEMA_COLS, has_raw_data=False
        )
        logger.info(f"[financial_ratios] {symbol}: {len(result)} kỳ sau transform.")
        return result


# ── Schema column lists (theo models.py) ─────────────────────────────────────

_BS_SCHEMA_COLS = [
    "cash_and_equivalents", "short_term_investments", "accounts_receivable",
    "inventory", "other_current_assets", "total_current_assets",
    "long_term_receivables", "fixed_assets", "investment_properties",
    "long_term_investments", "intangible_assets", "other_long_term_assets",
    "total_long_term_assets", "total_assets",
    "short_term_debt", "accounts_payable", "advances_from_customers",
    "other_current_liabilities", "total_current_liabilities",
    "long_term_debt", "other_long_term_liabilities", "total_long_term_liabilities",
    "total_liabilities",
    "charter_capital_fs", "share_premium", "retained_earnings", "other_equity",
    "minority_interest", "total_equity", "total_liabilities_equity",
]

_IS_SCHEMA_COLS = [
    "gross_revenue", "revenue_deductions", "net_revenue",
    "cogs", "gross_profit",
    "financial_income", "financial_expense", "interest_expense",
    "selling_expense", "admin_expense", "operating_profit",
    "other_income", "other_expense", "profit_from_associates",
    "ebt", "income_tax", "profit_after_tax", "minority_profit", "net_profit",
    "eps_basic", "eps_diluted",
]

_CF_SCHEMA_COLS = [
    "net_profit_before_tax", "depreciation", "provision",
    "unrealized_fx_gain_loss", "investment_income", "interest_expense_cf",
    "change_in_receivables", "change_in_inventory", "change_in_payables",
    "other_operating_changes", "income_tax_paid", "operating_cash_flow",
    "capex", "proceeds_from_asset_disposal", "investment_purchases",
    "investment_proceeds", "interest_and_dividends_received", "investing_cash_flow",
    "proceeds_from_borrowings", "repayment_of_borrowings",
    "proceeds_from_equity_issuance", "dividends_paid", "financing_cash_flow",
    "net_cash_change", "beginning_cash", "ending_cash",
]

_RATIO_SCHEMA_COLS = [
    "pe", "pb", "ps", "pcf", "ev_ebitda",
    "roe", "roa", "roic", "gross_margin", "ebit_margin", "net_profit_margin",
    "ebitda", "ebit",
    "current_ratio", "quick_ratio", "cash_ratio", "interest_coverage",
    "debt_to_equity", "debt_to_assets", "financial_leverage",
    "asset_turnover", "fixed_asset_turnover",
    "inventory_days", "receivable_days", "payable_days", "cash_conversion_cycle",
    "eps", "eps_ttm", "bvps", "dividend",
    "npl_ratio", "car", "ldr", "nim",
]

# Cột lưu dạng BIGINT (int64)
_BIGINT_COLS = set(
    _BS_SCHEMA_COLS
    + _CF_SCHEMA_COLS
    + ["gross_revenue", "revenue_deductions", "net_revenue", "cogs",
       "gross_profit", "financial_income", "financial_expense", "interest_expense",
       "selling_expense", "admin_expense", "operating_profit",
       "other_income", "other_expense", "profit_from_associates",
       "ebt", "income_tax", "profit_after_tax", "minority_profit", "net_profit",
       "ebitda", "ebit"]
) - {"eps_basic", "eps_diluted"}

# Cột lưu dạng NUMERIC/float
_FLOAT_COLS = {
    "eps_basic", "eps_diluted",
    "pe", "pb", "ps", "pcf", "ev_ebitda",
    "roe", "roa", "roic", "gross_margin", "ebit_margin", "net_profit_margin",
    "current_ratio", "quick_ratio", "cash_ratio", "interest_coverage",
    "debt_to_equity", "debt_to_assets", "financial_leverage",
    "asset_turnover", "fixed_asset_turnover",
    "inventory_days", "receivable_days", "payable_days", "cash_conversion_cycle",
    "eps", "eps_ttm", "bvps", "dividend",
    "npl_ratio", "car", "ldr", "nim",
}
