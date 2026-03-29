"""Transformer cho danh mục chứng khoán và phân ngành ICB."""

import pandas as pd

from config.constants import VALID_EXCHANGES, VALID_SECURITY_TYPES, VALID_STATUSES
from etl.base.transformer import BaseTransformer
from utils.logger import logger

# Suy ra level ICB từ độ dài icb_code (chuẩn FTSE Russell)
_LEVEL_BY_CODE_LEN: dict[int, int] = {2: 1, 4: 2, 6: 3, 8: 4}
# Số ký tự của parent tương ứng với từng level
_PARENT_CODE_LEN: dict[int, int] = {4: 2, 6: 4, 8: 6}

# Mapping type từ vnstock API sang DB constraint
_TYPE_MAP: dict[str, str] = {
    "STOCK": "STOCK",
    "IFC": "FUND",  # Investment Fund Certificate → FUND
    "ETF": "ETF",
    "BOND": "BOND",
    "CW": "CW",
    "FUND": "FUND",
}


class ListingTransformer(BaseTransformer):
    """
    Chuẩn hóa DataFrame thô từ ListingExtractor thành format sẵn sàng upsert.

    - transform_industries(df) → DataFrame cho icb_industries
    - transform_symbols(df)    → DataFrame cho companies
    - transform(df, symbol)    → alias cho transform_symbols
    """

    def transform(self, df: pd.DataFrame, symbol: str = "", **context) -> pd.DataFrame:
        """Alias cho transform_symbols() — tương thích BaseTransformer interface."""
        return self.transform_symbols(df)

    def transform_industries(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Chuẩn hóa bảng ICB industries.

        Input columns:  icb_name, en_icb_name, icb_code, level
        Output columns: icb_code, icb_name, en_icb_name, level, parent_code
        """
        df = df.copy()

        # icb_code sang string (DB lưu VARCHAR)
        df["icb_code"] = df["icb_code"].astype(str).str.strip()

        # Đảm bảo level là int
        df["level"] = pd.to_numeric(df["level"], errors="coerce").astype("Int64")

        # parent_code không có trong API → để None
        df["parent_code"] = None

        df = df[["icb_code", "icb_name", "en_icb_name", "level", "parent_code"]]

        before = len(df)
        df = df.dropna(subset=["icb_code", "icb_name", "level"])
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[icb_industries] Bỏ {dropped} dòng thiếu dữ liệu bắt buộc.")

        logger.info(f"[icb_industries] Sau transform: {len(df)} ngành.")
        return df.reset_index(drop=True)

    def transform_industries_from_json(self, records: list[dict]) -> pd.DataFrame:
        """
        Chuẩn hóa danh sách record từ load_icb_from_json() thành DataFrame.

        Input:  list[dict] với keys icb_code, icb_name, en_icb_name, level,
                            parent_code, definition
        Output: DataFrame với cột icb_code (str), icb_name, en_icb_name,
                level (int), parent_code, definition
        """
        df = pd.DataFrame(records)

        # icb_code sang string (DB lưu VARCHAR)
        df["icb_code"] = df["icb_code"].astype(str).str.strip()

        # Đảm bảo level là int
        df["level"] = pd.to_numeric(df["level"], errors="coerce").astype("Int64")

        df = df[["icb_code", "icb_name", "en_icb_name", "level", "parent_code", "definition"]]

        before = len(df)
        df = df.dropna(subset=["icb_code", "icb_name", "level"])
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[icb_industries] Bỏ {dropped} dòng thiếu dữ liệu bắt buộc.")

        logger.info(f"[icb_industries] Sau transform (JSON): {len(df)} ngành.")
        return df.reset_index(drop=True)

    def transform_icb_from_symbols(self, df_raw: pd.DataFrame) -> pd.DataFrame:
        """
        Trích xuất ICB codes từ raw DataFrame của all_symbols().
        Dùng làm nguồn bổ sung sau khi đã upsert từ JSON (ON CONFLICT DO NOTHING).

        - Level suy ra từ độ dài icb_code (2→1, 4→2, 6→3, 8→4).
        - parent_code suy ra bằng cách cắt bớt digits cuối.
        - icb_name lấy từ cột name nếu có, fallback về icb_code.

        Returns empty DataFrame nếu all_symbols() không trả về cột icb_code.
        """
        _empty = pd.DataFrame(
            columns=["icb_code", "icb_name", "en_icb_name", "level", "parent_code", "definition"]
        )

        # Tìm cột icb_code trong raw data (vnstock có thể dùng nhiều tên khác nhau)
        icb_col = next(
            (c for c in ["icb_code", "icbCode", "icb", "industry_code"] if c in df_raw.columns),
            None,
        )
        if icb_col is None:
            logger.debug("[icb_industries] all_symbols() không có cột icb_code — bỏ qua bổ sung.")
            return _empty

        # Tìm cột tên ICB nếu có
        name_col = next(
            (c for c in ["icb_name", "icbName", "industry_name"] if c in df_raw.columns),
            None,
        )

        cols = [icb_col] + ([name_col] if name_col else [])
        codes_df = (
            df_raw[cols]
            .copy()
            .assign(**{icb_col: df_raw[icb_col].astype(str).str.strip()})
            .query(f"{icb_col} != '' and {icb_col} != 'nan' and {icb_col} != 'None'")
            .drop_duplicates(subset=[icb_col])
        )

        records = []
        for _, row in codes_df.iterrows():
            code = row[icb_col]
            level = _LEVEL_BY_CODE_LEN.get(len(code))
            if level is None:
                continue  # bỏ qua code không đúng chuẩn ICB
            parent_code = (
                code[: _PARENT_CODE_LEN[len(code)]] if len(code) in _PARENT_CODE_LEN else None
            )
            name = str(row[name_col]).strip() if name_col and pd.notna(row.get(name_col)) else code
            records.append(
                {
                    "icb_code": code,
                    "icb_name": name,
                    "en_icb_name": None,
                    "level": level,
                    "parent_code": parent_code,
                    "definition": None,
                }
            )

        if not records:
            return _empty

        df = pd.DataFrame(records)
        df["level"] = pd.to_numeric(df["level"], errors="coerce").astype("Int64")
        logger.info(f"[icb_industries] Tìm thấy {len(df)} ICB codes từ all_symbols().")
        return df.reset_index(drop=True)

    def transform_symbols(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Chuẩn hóa bảng companies.

        Input columns:  symbol, type, exchange, status, company_name,
                        company_name_eng, short_name, listed_date,
                        delisted_date, company_id, fund_type, isin,
                        short_name_eng, tax_code, index_code
        Output columns: symbol, company_name, company_name_eng, short_name,
                        exchange, type, status,
                        listed_date, delisted_date, company_id, isin, tax_code
        Note: icb_code intentionally excluded — populated later by sync_company
              to avoid overwriting on every listing sync.
        """
        df = df.copy()

        # Chuẩn hóa type → DB constraint
        df["type"] = (
            df["type"]
            .str.upper()
            .map(_TYPE_MAP)
            .fillna("FUND")  # Fallback an toàn cho các type không xác định
        )

        # Lọc chỉ các giá trị hợp lệ
        df = df[df["type"].isin(VALID_SECURITY_TYPES)]
        df = df[df["exchange"].isin(VALID_EXCHANGES)]
        df = df[df["status"].isin(VALID_STATUSES)]

        # Ép kiểu ngày tháng — dùng apply để NaT → None (psycopg2 không nhận NaT)
        for col in ["listed_date", "delisted_date"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce").apply(
                    lambda x: x.date() if not pd.isna(x) else None
                )

        # company_id sang int nullable
        if "company_id" in df.columns:
            df["company_id"] = pd.to_numeric(df["company_id"], errors="coerce").astype("Int64")

        # tax_code: một số công ty có nhiều mã ngăn cách bởi '/' → chỉ lấy mã đầu tiên
        if "tax_code" in df.columns:
            df["tax_code"] = (
                df["tax_code"].astype(str).str.split("/").str[0].str.strip().replace("nan", None)
            )

        # icb_code không có trong all_symbols() — không đưa vào upsert payload để
        # tránh overwrite giá trị đã được sync_company cập nhật.
        df = df[
            [
                "symbol",
                "company_name",
                "company_name_eng",
                "short_name",
                "exchange",
                "type",
                "status",
                "listed_date",
                "delisted_date",
                "company_id",
                "isin",
                "tax_code",
            ]
        ]

        before = len(df)
        df = df.dropna(subset=["symbol", "company_name", "exchange", "type"])
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[companies] Bỏ {dropped} dòng thiếu dữ liệu bắt buộc.")

        logger.info(f"[companies] Sau transform: {len(df)} công ty.")
        return df.reset_index(drop=True)
