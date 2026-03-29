"""
HSXCompanyExtractor — lấy danh sách cổ phiếu từ API chính thức HOSE.

Endpoint: GET https://api.hsx.vn/l/api/v1/1/securities/stock
Params  : pageIndex, pageSize, alphabet, sectorId
Auth    : không cần
Trả về  : ~403 mã niêm yết trên HOSE, phân trang.
"""
from __future__ import annotations

import time

import requests

from utils.logger import logger

_HSX_BASE          = "https://api.hsx.vn/l/api/v1/1/securities/stock"
_PAGE_SIZE         = 100
_REQUEST_TIMEOUT   = 15   # giây
_SLEEP_BETWEEN_PAGES = 0.3  # giây — tránh rate-limit


class HSXCompanyExtractor:
    """Fetch toàn bộ danh sách cổ phiếu HOSE từ HSX API."""

    def extract_all(self) -> list[dict]:
        """
        Fetch tất cả trang từ HSX API.

        Returns:
            List raw dict, mỗi phần tử là 1 record từ API.
        """
        records: list[dict] = []
        page = 1

        while True:
            batch = self._fetch_page(page)
            if not batch:
                break

            records.extend(batch)
            logger.debug(
                f"[hsx_extractor] Page {page}: {len(batch)} records. "
                f"Tổng cộng: {len(records)}"
            )

            if len(batch) < _PAGE_SIZE:
                break  # trang cuối

            page += 1
            time.sleep(_SLEEP_BETWEEN_PAGES)

        logger.info(f"[hsx_extractor] Hoàn tất: {len(records)} records.")
        return records

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fetch_page(self, page_index: int) -> list[dict]:
        params = {
            "pageIndex": page_index,
            "pageSize":  _PAGE_SIZE,
            "alphabet":  "",
            "sectorId":  "",
        }
        resp = requests.get(_HSX_BASE, params=params, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()

        payload = resp.json()
        if not payload.get("success"):
            raise ValueError(f"HSX API trả về lỗi: {payload.get('message')}")

        return payload["data"]["list"]
