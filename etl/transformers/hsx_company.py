"""
HSXCompanyTransformer — chuẩn hóa dữ liệu từ HSX API → payload cho bảng companies.

Mapping:
    code     → symbol         (uppercase)
    name     → company_name
    brief    → brief
    phone    → phone
    fax      → fax
    address  → address
    webUrl   → web_url

Khi upsert:
    - Symbol đã tồn tại  → chỉ UPDATE: brief, phone, fax, address, web_url
    - Symbol chưa tồn tại → INSERT với các trường cơ bản
      (company_name, exchange='HOSE', type='stock', + 5 trường mới)
"""

from __future__ import annotations

import pandas as pd

from utils.logger import logger

# securitiesType từ API → giá trị type lưu trong DB
_TYPE_MAP: dict[int, str] = {
    1: "STOCK",
}
_DEFAULT_TYPE = "STOCK"


class HSXCompanyTransformer:
    """Transform raw HSX API records → DataFrame chuẩn bị upsert vào companies."""

    def transform(self, records: list[dict]) -> pd.DataFrame:
        """
        Args:
            records: List dict thô từ HSXCompanyExtractor.extract_all().

        Returns:
            DataFrame với các cột:
                symbol, company_name, exchange, type,
                brief, phone, fax, address, web_url
        """
        if not records:
            return pd.DataFrame()

        rows: list[dict] = []
        for r in records:
            symbol = str(r.get("code") or "").strip().upper()
            if not symbol:
                continue

            rows.append(
                {
                    "symbol": symbol,
                    "company_name": (r.get("name") or "").strip(),
                    "exchange": "HOSE",
                    "type": _TYPE_MAP.get(r.get("securitiesType"), _DEFAULT_TYPE),
                    "brief": _clean_str(r.get("brief")),
                    "phone": _clean_str(r.get("phone")),
                    "fax": _clean_str(r.get("fax")),
                    "address": _clean_str(r.get("address")),
                    "web_url": _clean_str(r.get("webUrl")),
                }
            )

        df = pd.DataFrame(rows)
        df = df.drop_duplicates(subset=["symbol"], keep="first")

        logger.info(f"[hsx_transformer] {len(df)} records sau transform.")
        return df


# ── helpers ───────────────────────────────────────────────────────────────────


def _clean_str(val: object) -> str | None:
    """Strip whitespace; trả None nếu rỗng hoặc null."""
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None
