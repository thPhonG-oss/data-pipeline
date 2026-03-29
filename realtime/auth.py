"""DNSE authentication manager — JWT token + investorId."""
from datetime import UTC, datetime, timedelta, timezone

import requests

from utils.logger import logger

_AUTH_URL = "https://api.dnse.com.vn/user-service/api/auth"
_ME_URL   = "https://api.dnse.com.vn/user-service/api/me"
_TOKEN_TTL_HOURS = 8
_REFRESH_BEFORE_HOURS = 1   # Refresh when less than 1h remains


class DNSEAuthManager:
    """
    Quản lý JWT token và investorId của DNSE.

    Cách dùng:
        auth = DNSEAuthManager(username=..., password=...)
        token       = auth.get_token()       # str JWT
        investor_id = auth.get_investor_id() # str (dùng làm MQTT username)
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        self._token: str | None = None
        self._investor_id: str | None = None
        self._token_fetched_at: datetime | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    def get_token(self) -> str:
        """Lấy JWT token, tự refresh nếu sắp hết hạn."""
        if self._needs_refresh():
            self._refresh()
        return self._token  # type: ignore[return-value]

    def get_investor_id(self) -> str:
        """Lấy investorId (dùng làm MQTT username)."""
        if self._needs_refresh():
            self._refresh()
        return self._investor_id  # type: ignore[return-value]

    def invalidate(self) -> None:
        """Buộc refresh lần tiếp theo (gọi sau khi MQTT disconnect vì auth)."""
        self._token = None
        self._token_fetched_at = None

    # ── Internal ───────────────────────────────────────────────────────────

    def _needs_refresh(self) -> bool:
        if self._token is None or self._token_fetched_at is None:
            return True
        age = datetime.now(tz=UTC) - self._token_fetched_at
        return age >= timedelta(hours=_TOKEN_TTL_HOURS - _REFRESH_BEFORE_HOURS)

    def _refresh(self) -> None:
        logger.info("[auth] Lấy JWT token từ DNSE...")
        resp = requests.post(_AUTH_URL, json={"username": self._username, "password": self._password}, timeout=10)
        resp.raise_for_status()
        self._token = resp.json()["token"]
        self._token_fetched_at = datetime.now(tz=UTC)

        resp2 = requests.get(_ME_URL, headers={"Authorization": f"Bearer {self._token}"}, timeout=10)
        resp2.raise_for_status()
        self._investor_id = str(resp2.json()["investorId"])
        logger.info(f"[auth] OK — investorId={self._investor_id}")
