"""Transformer cho danh mục chứng khoán và phân ngành ICB."""
import pandas as pd

from config.constants import VALID_EXCHANGES, VALID_SECURITY_TYPES, VALID_STATUSES
from etl.base.transformer import BaseTransformer
from utils.logger import logger

# Mapping type từ vnstock API sang DB constraint
_TYPE_MAP: dict[str, str] = {
    "STOCK": "STOCK",
    "IFC": "FUND",    # Investment Fund Certificate → FUND
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

    def transform_symbols(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Chuẩn hóa bảng companies.

        Input columns:  symbol, type, exchange, status, company_name,
                        company_name_eng, short_name, listed_date,
                        delisted_date, company_id, fund_type, isin,
                        short_name_eng, tax_code, index_code
        Output columns: symbol, company_name, company_name_eng, short_name,
                        exchange, type, status, icb_code,
                        listed_date, delisted_date, company_id, isin, tax_code
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
                df[col] = (
                    pd.to_datetime(df[col], errors="coerce")
                    .apply(lambda x: x.date() if not pd.isna(x) else None)
                )

        # company_id sang int nullable
        if "company_id" in df.columns:
            df["company_id"] = pd.to_numeric(df["company_id"], errors="coerce").astype("Int64")

        # tax_code: một số công ty có nhiều mã ngăn cách bởi '/' → chỉ lấy mã đầu tiên
        if "tax_code" in df.columns:
            df["tax_code"] = (
                df["tax_code"]
                .astype(str)
                .str.split("/")
                .str[0]
                .str.strip()
                .replace("nan", None)
            )

        # icb_code không có trong all_symbols() → để None, sẽ cập nhật khi sync_company chạy
        df["icb_code"] = None

        df = df[[
            "symbol", "company_name", "company_name_eng", "short_name",
            "exchange", "type", "status", "icb_code",
            "listed_date", "delisted_date", "company_id", "isin", "tax_code",
        ]]

        before = len(df)
        df = df.dropna(subset=["symbol", "company_name", "exchange", "type"])
        dropped = before - len(df)
        if dropped:
            logger.warning(f"[companies] Bỏ {dropped} dòng thiếu dữ liệu bắt buộc.")

        logger.info(f"[companies] Sau transform: {len(df)} công ty.")
        return df.reset_index(drop=True)
