"""Watchlist manager — danh sách symbol cần subscribe real-time."""

from sqlalchemy import text

from db.connection import engine
from utils.logger import logger

# VN30 hardcode (fallback khi DB không kết nối được)
_VN30_FALLBACK = [
    "ACB",
    "BCM",
    "BID",
    "BVH",
    "CTG",
    "FPT",
    "GAS",
    "GVR",
    "HDB",
    "HPG",
    "MBB",
    "MSN",
    "MWG",
    "PLX",
    "POW",
    "SAB",
    "SHB",
    "SSB",
    "SSI",
    "STB",
    "TCB",
    "TPB",
    "VCB",
    "VHM",
    "VIB",
    "VIC",
    "VJC",
    "VNM",
    "VPB",
    "VRE",
]


class WatchlistManager:
    """
    Quản lý danh sách symbol cần subscribe OHLC real-time.

    Thứ tự ưu tiên:
      1. watchlist_str (từ env REALTIME_WATCHLIST) — nếu có
      2. Query DB: SELECT symbol FROM companies WHERE index_code LIKE '%VN30%'
      3. Fallback hardcode: 30 mã VN30
    """

    def __init__(self, watchlist_str: str = "") -> None:
        self._watchlist_str = watchlist_str

    def get_symbols(self) -> list[str]:
        """Trả về danh sách symbol đã chuẩn hóa (uppercase, sorted, unique)."""
        if self._watchlist_str.strip():
            symbols = [s.strip().upper() for s in self._watchlist_str.split(",") if s.strip()]
            return sorted(set(symbols))

        return self._load_from_db()

    # ── Internal ───────────────────────────────────────────────────────────

    def _load_from_db(self) -> list[str]:
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT DISTINCT symbol FROM companies "
                        "WHERE status = 'listed' AND index_code LIKE '%VN30%' "
                        "ORDER BY symbol"
                    )
                ).fetchall()
            if rows:
                symbols = [r[0] for r in rows]
                logger.info(f"[watchlist] Loaded {len(symbols)} symbols from DB.")
                return symbols
        except Exception as exc:
            logger.warning(f"[watchlist] DB query failed: {exc} — using VN30 fallback.")
        return sorted(_VN30_FALLBACK)
