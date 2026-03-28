"""Transformer cho dữ liệu doanh nghiệp: overview, shareholders, officers, subsidiaries, events."""
from datetime import date

import pandas as pd
from sqlalchemy import text

from db.connection import engine
from etl.base.transformer import BaseTransformer
from utils.logger import logger

# Mapping tên tiếng Việt của loại công ty → giá trị schema
_SUBSIDIARY_TYPE_MAP = {
    "công ty con":     "subsidiary",
    "công ty liên kết": "associated",
    "liên kết":        "associated",
}

# SQL Server minimum datetime sentinel — API trả về khi không có giá trị
_SQL_MIN_DATE = date(1753, 1, 1)


def _lookup_icb_code(icb_name4: str | None) -> str | None:
    """Tra cứu icb_code theo icb_name ở level 4 từ bảng icb_industries.

    Thử khớp tên tiếng Việt (icb_name) trước, fallback sang tên tiếng Anh (en_icb_name).
    """
    if not icb_name4:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("""
                SELECT icb_code FROM icb_industries
                WHERE level = 4 AND (icb_name = :name OR en_icb_name = :name)
                LIMIT 1
            """),
            {"name": icb_name4},
        ).fetchone()
    return row[0] if row else None


def _to_date(val) -> date | None:
    """Chuyển giá trị sang Python date, trả None nếu không hợp lệ.
    Trả None cho SQL Server sentinel 1753-01-01.
    """
    if val is None or (isinstance(val, float) and val != val):
        return None
    try:
        d = pd.to_datetime(val).date()
        return None if d == _SQL_MIN_DATE else d
    except Exception:
        return None


class CompanyTransformer(BaseTransformer):
    """
    Chuẩn hóa DataFrames từ CompanyExtractor.

    - transform_overview(df, symbol)     → dict để UPDATE companies
    - transform_shareholders(df, symbol) → DataFrame cho shareholders
    - transform_officers(df, symbol)     → DataFrame cho officers
    - transform_subsidiaries(df, symbol) → DataFrame cho subsidiaries
    - transform_events(df, symbol)       → DataFrame cho corporate_events
    """

    def transform(self, df: pd.DataFrame, symbol: str, **context) -> pd.DataFrame:
        data_type = context.get("data_type", "overview")
        dispatch = {
            "shareholders": self.transform_shareholders,
            "officers":     self.transform_officers,
            "subsidiaries": self.transform_subsidiaries,
            "events":       self.transform_events,
            "news":         self.transform_news,
        }
        if data_type not in dispatch:
            raise ValueError(f"data_type '{data_type}' không có transform DataFrame.")
        return dispatch[data_type](df, symbol)

    # ── Overview → dict for companies UPDATE ─────────────────────────────────

    def transform_overview(self, df: pd.DataFrame, symbol: str) -> dict:
        """
        Trả về dict chứa các trường cần UPDATE vào bảng companies.
        Tra cứu icb_code từ icb_name4.
        """
        if df.empty:
            logger.warning(f"[company] {symbol}: overview trống, bỏ qua update.")
            return {}
        row = df.iloc[0]
        icb_name4 = row.get("icb_name4")
        icb_code = _lookup_icb_code(icb_name4)

        def _str_or_none(val) -> str | None:
            s = str(val).strip() if pd.notna(val) else None
            return s if s else None

        result = {
            "symbol":          symbol,
            "company_id":      int(row["id"]) if pd.notna(row.get("id")) else None,
            "issue_share":     int(row["issue_share"]) if pd.notna(row.get("issue_share")) else None,
            "charter_capital": int(row["charter_capital"]) if pd.notna(row.get("charter_capital")) else None,
            "icb_code":        icb_code,
            "history":         _str_or_none(row.get("history")),
            "company_profile": _str_or_none(row.get("company_profile")),
        }
        logger.info(
            f"[company] {symbol} overview → icb_code={icb_code}, "
            f"issue_share={result['issue_share']}, charter_capital={result['charter_capital']}"
        )
        return result

    # ── Shareholders ──────────────────────────────────────────────────────────

    def transform_shareholders(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        df["symbol"] = symbol
        df["snapshot_date"] = date.today()
        df["update_date"] = df["update_date"].apply(_to_date)
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
        df["share_own_percent"] = pd.to_numeric(df["share_own_percent"], errors="coerce")

        result = df[["symbol", "share_holder", "quantity", "share_own_percent",
                     "update_date", "snapshot_date"]].copy()
        result = result.dropna(subset=["share_holder"])
        result = result.drop_duplicates(subset=["symbol", "share_holder", "snapshot_date"], keep="last")
        logger.info(f"[shareholders] {symbol}: {len(result)} cổ đông sau transform.")
        return result.reset_index(drop=True)

    # ── Officers ──────────────────────────────────────────────────────────────

    def transform_officers(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        df["symbol"] = symbol
        df["snapshot_date"] = date.today()
        df["status"] = "working"
        df["update_date"] = df["update_date"].apply(_to_date)
        df["officer_own_percent"] = pd.to_numeric(df["officer_own_percent"], errors="coerce")
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")

        result = df[["symbol", "officer_name", "officer_position", "position_short_name",
                     "officer_own_percent", "quantity", "update_date",
                     "status", "snapshot_date"]].copy()
        result = result.dropna(subset=["officer_name"])
        result = result.drop_duplicates(subset=["symbol", "officer_name", "status", "snapshot_date"], keep="last")
        logger.info(f"[officers] {symbol}: {len(result)} lãnh đạo sau transform.")
        return result.reset_index(drop=True)

    # ── Subsidiaries ──────────────────────────────────────────────────────────

    def transform_subsidiaries(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        df["symbol"] = symbol
        df["snapshot_date"] = date.today()
        df["type"] = df["type"].str.strip().str.lower().map(_SUBSIDIARY_TYPE_MAP)
        df["ownership_percent"] = pd.to_numeric(df["ownership_percent"], errors="coerce")

        result = df[["symbol", "sub_organ_code", "organ_name",
                     "ownership_percent", "type", "snapshot_date"]].copy()
        result = result.dropna(subset=["organ_name"])
        result = result.drop_duplicates(subset=["symbol", "organ_name", "snapshot_date"], keep="last")
        logger.info(f"[subsidiaries] {symbol}: {len(result)} đơn vị sau transform.")
        return result.reset_index(drop=True)

    # ── Corporate Events ──────────────────────────────────────────────────────

    def transform_events(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        df["symbol"] = symbol

        for col in ["public_date", "issue_date", "record_date", "exright_date"]:
            if col in df.columns:
                df[col] = df[col].apply(_to_date)

        df["ratio"] = pd.to_numeric(df["ratio"], errors="coerce")
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        # record_date có thể NULL — dùng issue_date làm fallback cho conflict key
        df["record_date"] = df.apply(
            lambda r: r["record_date"] if r["record_date"] is not None else r.get("issue_date"),
            axis=1,
        )

        result = df[["symbol", "event_title", "event_list_code", "event_list_name",
                     "public_date", "issue_date", "record_date", "exright_date",
                     "ratio", "value", "source_url"]].copy()
        # Drop rows where event_list_code is null (can't upsert without conflict key)
        result = result.dropna(subset=["event_list_code"])
        # Deduplicate on conflict key — prevents CardinalityViolation in ON CONFLICT DO UPDATE
        result = result.drop_duplicates(subset=["symbol", "event_list_code", "record_date"], keep="last")
        logger.info(f"[corporate_events] {symbol}: {len(result)} sự kiện sau transform.")
        return result.reset_index(drop=True)

    # ── Company News ──────────────────────────────────────────────────────────

    def transform_news(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        df = df.copy()
        df["symbol"] = symbol

        # Đổi tên để tránh từ khóa SQL và khớp schema
        df = df.rename(columns={
            "id":       "vci_id",
            "floor":    "floor_price",
            "ceiling":  "ceiling_price",
        })

        # public_date: Unix milliseconds → TIMESTAMPTZ (UTC)
        if "public_date" in df.columns:
            df["public_date"] = pd.to_datetime(
                pd.to_numeric(df["public_date"], errors="coerce"),
                unit="ms", utc=True,
            )

        # vci_id: đảm bảo là số nguyên
        if "vci_id" in df.columns:
            df["vci_id"] = pd.to_numeric(df["vci_id"], errors="coerce").astype("Int64")

        # Giá → số nguyên
        for col in ["close_price", "ref_price", "floor_price", "ceiling_price"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")

        if "price_change_pct" in df.columns:
            df["price_change_pct"] = pd.to_numeric(df["price_change_pct"], errors="coerce")

        keep = [
            "vci_id", "symbol", "news_title", "news_sub_title", "friendly_sub_title",
            "news_id", "news_short_content", "news_full_content", "news_source_link",
            "news_image_url", "lang_code", "public_date",
            "close_price", "ref_price", "floor_price", "ceiling_price", "price_change_pct",
        ]
        keep = [c for c in keep if c in df.columns]
        df = df[keep].dropna(subset=["vci_id"])
        df = df.drop_duplicates(subset=["vci_id", "symbol"], keep="last")
        logger.info(f"[company_news] {symbol}: {len(df)} bài sau transform.")
        return df.reset_index(drop=True)
