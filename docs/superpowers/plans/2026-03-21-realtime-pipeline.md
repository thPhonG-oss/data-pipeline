# Real-time Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the batch pipeline with a parallel real-time intraday OHLC data stream: DNSE MDDS (MQTT) → Redis Streams → PostgreSQL `price_intraday` table.

**Architecture:** A dedicated MQTT subscriber process connects to DNSE's KRX market data feed, deserializes OHLC candle messages, and pushes them into Redis Streams. One or more processor workers consume from Redis via consumer groups and batch-upsert into PostgreSQL. The existing batch pipeline (APScheduler jobs) runs completely unchanged.

**Tech Stack:** Python 3.11, paho-mqtt>=2.0, redis>=5.0 (already in venv), SQLAlchemy, PostgreSQL, Docker Compose.

**Spec doc:** `docs/realtime_pipeline_plan.md`

---

## File Map

### New files
| File | Responsibility |
|---|---|
| `db/migrations/007_price_intraday.sql` | Create `price_intraday` table + indexes + retention comments |
| `realtime/__init__.py` | Package marker |
| `realtime/auth.py` | `DNSEAuthManager` — JWT login + investorId fetch, token expiry tracking |
| `realtime/watchlist.py` | `WatchlistManager` — load symbols from env or DB |
| `realtime/session_guard.py` | `is_trading_hours()` — returns True only Mon–Fri 08:45–15:10 |
| `realtime/subscriber.py` | `MQTTSubscriber` — connect MQTT, subscribe OHLC topics, XADD to Redis |
| `realtime/processor.py` | `StreamProcessor` — XREADGROUP from Redis, validate, upsert PostgreSQL |
| `tests/__init__.py` | Package marker |
| `tests/realtime/__init__.py` | Package marker |
| `tests/realtime/test_auth.py` | Unit tests for DNSEAuthManager (mock HTTP) |
| `tests/realtime/test_watchlist.py` | Unit tests for WatchlistManager |
| `tests/realtime/test_session_guard.py` | Unit tests for is_trading_hours() |
| `tests/realtime/test_processor.py` | Unit tests for StreamProcessor transform/validate logic |

### Modified files
| File | Change |
|---|---|
| `config/settings.py` | Add `realtime_watchlist: str`, `realtime_resolutions: str` |
| `config/constants.py` | Add `CONFLICT_KEYS["price_intraday"]` |
| `.env.example` | Add Redis and realtime config vars |
| `docker-compose.yml` | Add `redis`, `realtime-subscriber`, `realtime-processor` services |

---

## Task 1: DB Migration — `price_intraday` table

**Files:**
- Create: `db/migrations/007_price_intraday.sql`

**Context:** `PostgresLoader` reflects tables from DB before loading. The table must exist before the processor runs. Migration files in `db/migrations/` are auto-run by Docker on first init (mounted at `/docker-entrypoint-initdb.d`). For manual runs: `psql -d stockapp -f db/migrations/007_price_intraday.sql`.

- [ ] **Step 1: Create migration file**

```sql
-- db/migrations/007_price_intraday.sql
-- ============================================================
-- Migration 007: Bảng dữ liệu giá intraday (real-time)
-- Lưu nến OHLC 1m và 5m từ DNSE MDDS (MQTT streaming)
-- Tách hoàn toàn khỏi price_history (EOD batch)
-- ============================================================

CREATE TABLE IF NOT EXISTS price_intraday (
    id          BIGSERIAL    PRIMARY KEY,
    symbol      VARCHAR(10)  NOT NULL
                CONSTRAINT fk_pi_symbol REFERENCES companies(symbol),
    time        TIMESTAMPTZ  NOT NULL,
    resolution  SMALLINT     NOT NULL,        -- Timeframe: 1 hoặc 5 (phút)
    open        INTEGER      NOT NULL,        -- VND nguyên (DNSE MDDS trả VND nguyên)
    high        INTEGER      NOT NULL,
    low         INTEGER      NOT NULL,
    close       INTEGER      NOT NULL,
    volume      BIGINT,
    source      VARCHAR(20)  DEFAULT 'dnse_mdds',
    fetched_at  TIMESTAMPTZ  DEFAULT NOW(),

    CONSTRAINT uq_price_intraday UNIQUE (symbol, time, resolution)
);

CREATE INDEX IF NOT EXISTS idx_pi_sym_res_time
    ON price_intraday(symbol, resolution, time DESC);

CREATE INDEX IF NOT EXISTS idx_pi_today
    ON price_intraday(symbol, resolution, time DESC)
    WHERE time >= CURRENT_DATE;

COMMENT ON TABLE price_intraday IS
    'Gia intraday OHLC tu DNSE MDDS (MQTT real-time). '
    'resolution=1 la nen 1 phut, resolution=5 la nen 5 phut. '
    'Don vi gia: VND nguyen. Retention: 1m=30 ngay, 5m=180 ngay.';

COMMENT ON COLUMN price_intraday.resolution IS
    'Timeframe tinh bang phut: 1 = nen 1 phut, 5 = nen 5 phut.';
```

- [ ] **Step 2: Run migration manually against local DB**

```bash
psql -U postgres -d stockapp -f db/migrations/007_price_intraday.sql
```

Expected output:
```
CREATE TABLE
CREATE INDEX
CREATE INDEX
COMMENT
COMMENT
COMMENT
```

- [ ] **Step 3: Verify table exists**

```bash
psql -U postgres -d stockapp -c "\d price_intraday"
```

Expected: table with columns `id, symbol, time, resolution, open, high, low, close, volume, source, fetched_at` and unique constraint on `(symbol, time, resolution)`.

- [ ] **Step 4: Commit**

```bash
git add db/migrations/007_price_intraday.sql
git commit -m "feat(rt): add price_intraday table migration (007)"
```

---

## Task 2: Config & Constants updates

**Files:**
- Modify: `config/settings.py`
- Modify: `config/constants.py`
- Modify: `.env.example`

**Context:** `settings.py` already has `redis_host: str = "localhost"` and `redis_port: int = 6379`. No need to add those. We only add realtime-specific settings.

- [ ] **Step 1: Add realtime settings to `config/settings.py`**

Add after the `dnse_password` field (after line 43):

```python
    # ── Real-time pipeline ─────────────────────────────────────
    # CSV danh sách symbol, vd: "HPG,VCB,FPT". Rỗng = dùng VN30 từ DB.
    realtime_watchlist: str = ""
    # Timeframes cần subscribe, phân cách bằng dấu phẩy: "1,5"
    realtime_resolutions: str = "1,5"
```

- [ ] **Step 2: Add `price_intraday` to CONFLICT_KEYS in `config/constants.py`**

Add after the `"price_history"` line (line 54):

```python
    "price_intraday":    ["symbol", "time", "resolution"],
```

- [ ] **Step 3: Add realtime env vars to `.env.example`**

Add at the end:

```env

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_HOST=localhost
REDIS_PORT=6379

# ── Real-time pipeline (DNSE MDDS MQTT streaming) ─────────────────────────────
# Danh sách mã subscribe real-time (phân cách bằng dấu phẩy).
# Để trống = tự động lấy danh sách VN30 từ bảng companies trong DB.
REALTIME_WATCHLIST=
# Timeframes cần subscribe (phẩy phân cách). 1 = nến 1 phút, 5 = nến 5 phút.
REALTIME_RESOLUTIONS=1,5
```

- [ ] **Step 4: Verify settings load correctly**

```bash
venv/Scripts/python.exe -c "
from config.settings import settings
print('realtime_watchlist:', repr(settings.realtime_watchlist))
print('realtime_resolutions:', repr(settings.realtime_resolutions))
print('redis_host:', settings.redis_host)
print('redis_port:', settings.redis_port)
"
```

Expected:
```
realtime_watchlist: ''
realtime_resolutions: '1,5'
redis_host: localhost
redis_port: 6379
```

- [ ] **Step 5: Commit**

```bash
git add config/settings.py config/constants.py .env.example
git commit -m "feat(rt): add realtime config and price_intraday conflict key"
```

---

## Task 3: Auth module

**Files:**
- Create: `realtime/__init__.py`
- Create: `realtime/auth.py`
- Create: `tests/__init__.py`
- Create: `tests/realtime/__init__.py`
- Create: `tests/realtime/test_auth.py`

**Context:** DNSE auth flow: POST to get JWT token (expires 8h), GET to get investorId. `DNSEAuthManager` caches the token and only re-fetches when within 1h of expiry. Token is used as MQTT password; investorId as MQTT username.

- [ ] **Step 1: Install paho-mqtt**

```bash
venv/Scripts/pip.exe install "paho-mqtt>=2.0"
```

Expected: `Successfully installed paho-mqtt-2.x.x`

- [ ] **Step 2: Create package markers**

`realtime/__init__.py` — empty file.
`tests/__init__.py` — empty file.
`tests/realtime/__init__.py` — empty file.

- [ ] **Step 3: Write failing tests**

```python
# tests/realtime/test_auth.py
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pytest

from realtime.auth import DNSEAuthManager


@pytest.fixture
def auth():
    return DNSEAuthManager(username="test@example.com", password="pass")


def _mock_auth_response(token="tok123"):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"token": token}
    return resp


def _mock_me_response(investor_id=999):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"investorId": investor_id}
    return resp


def test_get_token_fetches_and_caches(auth):
    with patch("realtime.auth.requests.post", return_value=_mock_auth_response()) as mock_post, \
         patch("realtime.auth.requests.get", return_value=_mock_me_response()):
        token = auth.get_token()
        assert token == "tok123"
        # Second call must NOT make another HTTP request
        auth.get_token()
        assert mock_post.call_count == 1


def test_get_investor_id_cached(auth):
    with patch("realtime.auth.requests.post", return_value=_mock_auth_response()), \
         patch("realtime.auth.requests.get", return_value=_mock_me_response(42)) as mock_get:
        investor_id = auth.get_investor_id()
        assert investor_id == "42"
        auth.get_investor_id()
        assert mock_get.call_count == 1


def test_token_refreshed_when_near_expiry(auth):
    with patch("realtime.auth.requests.post", return_value=_mock_auth_response("new_tok")) as mock_post, \
         patch("realtime.auth.requests.get", return_value=_mock_me_response()):
        # Simulate token fetched 7.5h ago (within 1h expiry window of 8h token)
        auth._token = "old_tok"
        auth._investor_id = "1"
        auth._token_fetched_at = datetime.now(tz=timezone.utc) - timedelta(hours=7, minutes=30)

        token = auth.get_token()
        assert token == "new_tok"
        assert mock_post.call_count == 1


def test_raises_on_auth_failure(auth):
    resp = MagicMock()
    resp.raise_for_status.side_effect = Exception("401 Unauthorized")
    with patch("realtime.auth.requests.post", return_value=resp):
        with pytest.raises(Exception, match="401"):
            auth.get_token()
```

- [ ] **Step 4: Run tests to confirm they fail**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'realtime.auth'`

- [ ] **Step 5: Implement `realtime/auth.py`**

```python
"""DNSE authentication manager — JWT token + investorId."""
from datetime import datetime, timezone, timedelta

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
        age = datetime.now(tz=timezone.utc) - self._token_fetched_at
        return age >= timedelta(hours=_TOKEN_TTL_HOURS - _REFRESH_BEFORE_HOURS)

    def _refresh(self) -> None:
        logger.info("[auth] Lấy JWT token từ DNSE...")
        resp = requests.post(_AUTH_URL, json={"username": self._username, "password": self._password}, timeout=10)
        resp.raise_for_status()
        self._token = resp.json()["token"]
        self._token_fetched_at = datetime.now(tz=timezone.utc)

        resp2 = requests.get(_ME_URL, headers={"Authorization": f"Bearer {self._token}"}, timeout=10)
        resp2.raise_for_status()
        self._investor_id = str(resp2.json()["investorId"])
        logger.info(f"[auth] OK — investorId={self._investor_id}")
```

- [ ] **Step 6: Run tests — must pass**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_auth.py -v
```

Expected: `4 passed`

- [ ] **Step 7: Commit**

```bash
git add realtime/__init__.py realtime/auth.py tests/__init__.py tests/realtime/__init__.py tests/realtime/test_auth.py
git commit -m "feat(rt): add DNSEAuthManager with JWT caching and auto-refresh"
```

---

## Task 4: Watchlist module

**Files:**
- Create: `realtime/watchlist.py`
- Create: `tests/realtime/test_watchlist.py`

**Context:** If `REALTIME_WATCHLIST` env var is set (e.g. `"HPG,VCB,FPT"`), use those symbols. Otherwise query `companies` table for symbols where the symbol appears in a VN30 list. Symbols are always uppercased and stripped.

- [ ] **Step 1: Write failing tests**

```python
# tests/realtime/test_watchlist.py
from unittest.mock import patch, MagicMock

from realtime.watchlist import WatchlistManager

_VN30 = [
    "ACB","BCM","BID","BVH","CTG","FPT","GAS","GVR","HDB","HPG",
    "MBB","MSN","MWG","PLX","POW","SAB","SHB","SSB","SSI","STB",
    "TCB","TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VRE",
]


def test_load_from_env():
    mgr = WatchlistManager(watchlist_str="HPG,vcb, FPT ")
    symbols = mgr.get_symbols()
    assert symbols == ["FPT", "HPG", "VCB"]   # sorted, uppercased, stripped


def test_load_from_db_when_env_empty():
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.execute.return_value.fetchall.return_value = [("HPG",), ("VCB",)]

    mock_engine = MagicMock()
    mock_engine.connect.return_value = mock_conn

    with patch("realtime.watchlist.engine", mock_engine):
        mgr = WatchlistManager(watchlist_str="")
        symbols = mgr.get_symbols()
    assert "HPG" in symbols
    assert "VCB" in symbols


def test_empty_env_falls_back_to_vn30_hardcode_on_db_error():
    with patch("realtime.watchlist.engine") as mock_engine:
        mock_engine.connect.side_effect = Exception("DB down")
        mgr = WatchlistManager(watchlist_str="")
        symbols = mgr.get_symbols()
    # Must return hardcoded VN30 fallback (30 symbols)
    assert len(symbols) == 30
    assert "HPG" in symbols


def test_no_duplicates():
    mgr = WatchlistManager(watchlist_str="HPG,HPG,VCB")
    assert mgr.get_symbols().count("HPG") == 1
```

- [ ] **Step 2: Run failing tests**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_watchlist.py -v
```

Expected: `ModuleNotFoundError: No module named 'realtime.watchlist'`

- [ ] **Step 3: Implement `realtime/watchlist.py`**

```python
"""Watchlist manager — danh sách symbol cần subscribe real-time."""
from sqlalchemy import text

from db.connection import engine
from utils.logger import logger

# VN30 hardcode (fallback khi DB không kết nối được)
_VN30_FALLBACK = [
    "ACB","BCM","BID","BVH","CTG","FPT","GAS","GVR","HDB","HPG",
    "MBB","MSN","MWG","PLX","POW","SAB","SHB","SSB","SSI","STB",
    "TCB","TPB","VCB","VHM","VIB","VIC","VJC","VNM","VPB","VRE",
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
```

- [ ] **Step 4: Run tests — must pass**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_watchlist.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add realtime/watchlist.py tests/realtime/test_watchlist.py
git commit -m "feat(rt): add WatchlistManager with env/DB/fallback priority"
```

---

## Task 5: Session Guard

**Files:**
- Create: `realtime/session_guard.py`
- Create: `tests/realtime/test_session_guard.py`

**Context:** Subscriber should only connect during trading hours to avoid unnecessary MQTT connections. HoSE hours: Mon–Fri 09:00–15:00, but we add buffer (subscribe at 08:45, disconnect at 15:10). Timezone: `Asia/Ho_Chi_Minh`.

- [ ] **Step 1: Write failing tests**

```python
# tests/realtime/test_session_guard.py
from datetime import datetime
import zoneinfo

import pytest

from realtime.session_guard import is_trading_hours

_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.mark.parametrize("dt,expected", [
    # Monday 09:00 — in session
    (datetime(2026, 3, 23, 9, 0, tzinfo=_TZ),  True),
    # Friday 14:59 — in session
    (datetime(2026, 3, 27, 14, 59, tzinfo=_TZ), True),
    # Saturday — weekend
    (datetime(2026, 3, 28, 10, 0, tzinfo=_TZ),  False),
    # Sunday — weekend
    (datetime(2026, 3, 29, 10, 0, tzinfo=_TZ),  False),
    # Monday 08:44 — too early
    (datetime(2026, 3, 23, 8, 44, tzinfo=_TZ),  False),
    # Monday 15:11 — too late
    (datetime(2026, 3, 23, 15, 11, tzinfo=_TZ), False),
    # Monday 08:45 — start of window
    (datetime(2026, 3, 23, 8, 45, tzinfo=_TZ),  True),
    # Monday 15:10 — end of window (inclusive)
    (datetime(2026, 3, 23, 15, 10, tzinfo=_TZ), True),
])
def test_is_trading_hours(dt, expected):
    assert is_trading_hours(dt) == expected
```

- [ ] **Step 2: Run failing tests**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_session_guard.py -v
```

Expected: `ModuleNotFoundError: No module named 'realtime.session_guard'`

- [ ] **Step 3: Implement `realtime/session_guard.py`**

```python
"""Session guard — kiểm tra giờ giao dịch HoSE/HNX."""
from datetime import datetime, time
import zoneinfo

_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
_SESSION_START = time(8, 45)   # Mở sớm 15 phút trước ATO
_SESSION_END   = time(15, 10)  # Đóng 10 phút sau ATC


def is_trading_hours(now: datetime | None = None) -> bool:
    """
    Trả về True nếu hiện tại đang trong giờ giao dịch HoSE/HNX:
      - Thứ 2 đến Thứ 6 (weekday 0–4)
      - 08:45 đến 15:10 (Asia/Ho_Chi_Minh)

    Args:
        now: Thời điểm cần kiểm tra. Mặc định: thời điểm hiện tại.
    """
    if now is None:
        now = datetime.now(tz=_TZ)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)

    if now.weekday() >= 5:   # Thứ 7 = 5, Chủ Nhật = 6
        return False

    current_time = now.time().replace(tzinfo=None)
    return _SESSION_START <= current_time <= _SESSION_END
```

- [ ] **Step 4: Run tests — must pass**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_session_guard.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add realtime/session_guard.py tests/realtime/test_session_guard.py
git commit -m "feat(rt): add session guard for trading hours (Mon-Fri 08:45-15:10)"
```

---

## Task 6: Stream Processor

**Files:**
- Create: `realtime/processor.py`
- Create: `tests/realtime/test_processor.py`

**Context:** Processor reads from Redis Streams using consumer groups, transforms raw message dicts into DataFrames, and upserts to PostgreSQL via `PostgresLoader`. Key design: `_transform_message()` is pure (no I/O) and fully testable. The I/O loop (`run()`) is kept thin and not unit-tested directly — test only the transform logic.

DNSE MDDS OHLC payload fields (from spec):
- `symbol`: str (e.g. `"HPG"`)
- `time`: ISO timestamp string (e.g. `"2026-03-21T09:01:00+07:00"`)
- `open`, `high`, `low`, `close`: float, in VND nguyên (no scaling needed)
- `volume`: int
- `resolution`: str (`"1"`, `"5"`, `"1H"`, `"1D"` — we only care about `"1"` and `"5"`)

- [ ] **Step 1: Write failing tests**

```python
# tests/realtime/test_processor.py
import pandas as pd
import pytest

from realtime.processor import _transform_message, _validate_message


_VALID_MSG = {
    "symbol": "HPG",
    "time": "2026-03-21T09:01:00+07:00",
    "open": 20800.0,
    "high": 20900.0,
    "low": 20750.0,
    "close": 20850.0,
    "volume": 1234567,
    "resolution": "1",
}


def test_transform_valid_message():
    row = _transform_message(_VALID_MSG)
    assert row["symbol"] == "HPG"
    assert row["resolution"] == 1
    assert row["open"] == 20800
    assert row["close"] == 20850
    assert row["source"] == "dnse_mdds"
    assert "time" in row
    assert "fetched_at" in row


def test_transform_5min_resolution():
    msg = {**_VALID_MSG, "resolution": "5"}
    row = _transform_message(msg)
    assert row["resolution"] == 5


def test_validate_rejects_missing_field():
    for field in ["symbol", "time", "close", "resolution"]:
        bad = {k: v for k, v in _VALID_MSG.items() if k != field}
        assert _validate_message(bad) is False


def test_validate_rejects_non_numeric_resolution():
    msg = {**_VALID_MSG, "resolution": "1H"}   # 1H not supported
    assert _validate_message(msg) is False


def test_validate_rejects_zero_close():
    msg = {**_VALID_MSG, "close": 0}
    assert _validate_message(msg) is False


def test_transform_price_rounded_to_int():
    msg = {**_VALID_MSG, "close": 20850.7}
    row = _transform_message(msg)
    assert isinstance(row["close"], int)
```

- [ ] **Step 2: Run failing tests**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_processor.py -v
```

Expected: `ModuleNotFoundError: No module named 'realtime.processor'`

- [ ] **Step 3: Implement `realtime/processor.py`**

```python
"""
Stream Processor — đọc từ Redis Streams và upsert vào PostgreSQL.

Kiến trúc:
  Redis Streams (XREADGROUP) → validate → transform → batch upsert PostgreSQL

Chạy:
  python -m realtime.processor
"""
import signal
import socket
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import redis as redis_lib

from config.constants import CONFLICT_KEYS
from config.settings import settings
from etl.loaders.postgres import PostgresLoader
from utils.logger import logger

_STREAMS       = ["stream:ohlc:1m", "stream:ohlc:5m"]
_GROUP_NAME    = "ohlc-processors"
_CONSUMER_NAME = f"worker-{socket.gethostname()}-{__import__('os').getpid()}"
_BATCH_SIZE    = 100
_BLOCK_MS      = 5000    # Block 5s chờ message mới
_AUTOCLAIM_MS  = 30 * 60 * 1000   # Claim pending > 30 phút
_MAX_RETRIES   = 3       # Số lần retry trước khi dead-letter
_TABLE         = "price_intraday"
_CONFLICT_KEYS = CONFLICT_KEYS[_TABLE]

# Resolutions được chấp nhận
_VALID_RESOLUTIONS = {"1", "5"}


# ── Pure functions (testable) ──────────────────────────────────────────────────

def _validate_message(msg: dict) -> bool:
    """Kiểm tra message có đủ fields và hợp lệ không."""
    required = {"symbol", "time", "open", "high", "low", "close", "volume", "resolution"}
    if not required.issubset(msg.keys()):
        return False
    if str(msg.get("resolution", "")) not in _VALID_RESOLUTIONS:
        return False
    try:
        if float(msg["close"]) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _transform_message(msg: dict) -> dict:
    """
    Chuyển đổi raw MQTT message dict thành DB row dict.
    Hàm pure — không có I/O.
    """
    return {
        "symbol":     msg["symbol"].upper(),
        "time":       msg["time"],   # ISO string → PostgresLoader/SQLAlchemy tự parse
        "resolution": int(msg["resolution"]),
        "open":       int(round(float(msg["open"]))),
        "high":       int(round(float(msg["high"]))),
        "low":        int(round(float(msg["low"]))),
        "close":      int(round(float(msg["close"]))),
        "volume":     int(msg.get("volume") or 0),
        "source":     "dnse_mdds",
        "fetched_at": datetime.now(tz=timezone.utc),
    }


# ── StreamProcessor ────────────────────────────────────────────────────────────

class StreamProcessor:
    """
    Đọc messages từ Redis Streams, validate, transform, upsert PostgreSQL.

    Vòng lặp chính:
      1. XAUTOCLAIM: lấy lại pending messages bị stuck
      2. XREADGROUP: đọc batch messages mới
      3. Validate + transform → DataFrame
      4. Batch upsert vào price_intraday
      5. XACK: xác nhận sau khi upsert thành công
    """

    def __init__(self) -> None:
        self._redis = redis_lib.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            decode_responses=True,
        )
        self._loader = PostgresLoader()
        self._running = False
        self._ensure_consumer_groups()

    def run(self) -> None:
        """Vòng lặp chính — chạy đến khi nhận SIGTERM/SIGINT."""
        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT,  self._shutdown)
        logger.info(f"[processor] Bắt đầu — consumer: {_CONSUMER_NAME}")

        while self._running:
            try:
                # 1. Claim lại pending messages cũ
                for stream in _STREAMS:
                    self._autoclaim_pending(stream)

                # 2. Đọc messages mới
                self._read_and_process()

            except redis_lib.ConnectionError as exc:
                logger.error(f"[processor] Redis mất kết nối: {exc}. Retry sau 5s...")
                time.sleep(5)
            except Exception as exc:
                logger.exception(f"[processor] Lỗi không xác định: {exc}")
                time.sleep(1)

        logger.info("[processor] Đã dừng.")

    # ── Internal ────────────────────────────────────────────────────────────

    def _ensure_consumer_groups(self) -> None:
        for stream in _STREAMS:
            try:
                self._redis.xgroup_create(stream, _GROUP_NAME, id="$", mkstream=True)
                logger.info(f"[processor] Tạo consumer group '{_GROUP_NAME}' cho {stream}.")
            except redis_lib.ResponseError as e:
                if "BUSYGROUP" not in str(e):
                    raise

    def _read_and_process(self) -> None:
        stream_ids = {s: ">" for s in _STREAMS}
        results = self._redis.xreadgroup(
            groupname=_GROUP_NAME,
            consumername=_CONSUMER_NAME,
            streams=stream_ids,
            count=_BATCH_SIZE,
            block=_BLOCK_MS,
        )
        if not results:
            return

        for stream_name, messages in results:
            if not messages:
                continue
            self._process_batch(stream_name, messages)

    def _process_batch(self, stream_name: str, messages: list) -> None:
        rows, ack_ids = [], []
        for msg_id, msg_data in messages:
            if not _validate_message(msg_data):
                logger.warning(f"[processor] Invalid message {msg_id}: {msg_data}")
                ack_ids.append(msg_id)   # ACK invalid messages to clear them
                continue
            rows.append(_transform_message(msg_data))
            ack_ids.append(msg_id)

        if rows:
            df = pd.DataFrame(rows)
            try:
                inserted = self._loader.load(df, _TABLE, _CONFLICT_KEYS)
                logger.debug(f"[processor] {stream_name}: upserted {inserted} rows.")
            except Exception as exc:
                logger.error(f"[processor] DB upsert failed: {exc}")
                return   # Do NOT ACK — messages stay pending for retry

        if ack_ids:
            self._redis.xack(stream_name, _GROUP_NAME, *ack_ids)

    def _autoclaim_pending(self, stream: str) -> None:
        try:
            result = self._redis.xautoclaim(
                stream, _GROUP_NAME, _CONSUMER_NAME,
                min_idle_time=_AUTOCLAIM_MS, count=50,
            )
            messages = result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else []
            if messages:
                logger.warning(f"[processor] Reclaiming {len(messages)} pending messages from {stream}.")
                self._process_batch(stream, messages)
        except Exception as exc:
            logger.warning(f"[processor] XAUTOCLAIM error on {stream}: {exc}")

    def _shutdown(self, signum, frame) -> None:
        logger.info("[processor] Nhận tín hiệu dừng...")
        self._running = False


if __name__ == "__main__":
    StreamProcessor().run()
```

- [ ] **Step 4: Run tests — must pass**

```bash
venv/Scripts/python.exe -m pytest tests/realtime/test_processor.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add realtime/processor.py tests/realtime/test_processor.py
git commit -m "feat(rt): add StreamProcessor with Redis Streams consumer group"
```

---

## Task 7: MQTT Subscriber

**Files:**
- Create: `realtime/subscriber.py`

**Context:** The subscriber is the most stateful component (persistent TCP/WebSocket connection to MQTT broker). It is intentionally kept thin: MQTT callbacks only do JSON parse + Redis XADD. All heavy logic (transform, validate, DB) is in the processor. Unit testing MQTT is hard — we will do a live smoke test instead.

MQTT auth: username = `investorId` (str), password = JWT token. Client ID must be unique (`uuid4`). SSL: self-signed cert, use `tls_insecure_set(True)`. Topic pattern for OHLC: `plaintext/quotes/krx/mdds/v2/ohlc/stock/{resolution}/{symbol}`.

- [ ] **Step 1: Implement `realtime/subscriber.py`**

```python
"""
MQTT Subscriber — kết nối DNSE MDDS, nhận OHLC, push vào Redis Streams.

Chạy:
  python -m realtime.subscriber

Vòng lặp sống:
  1. Auth DNSE → JWT + investorId
  2. Kết nối MQTT broker
  3. Subscribe OHLC topics cho watchlist
  4. Nhận messages → XADD Redis Streams
  5. Khi disconnect → backoff reconnect
  6. Refresh JWT mỗi 7h
"""
import json
import signal
import ssl
import threading
import time
import uuid

import paho.mqtt.client as mqtt
import redis as redis_lib

from config.settings import settings
from realtime.auth import DNSEAuthManager
from realtime.watchlist import WatchlistManager
from utils.logger import logger

_BROKER_HOST   = "datafeed-lts-krx.dnse.com.vn"
_BROKER_PORT   = 443
_KEEPALIVE     = 1200   # 20 phút
_QOS           = 1
_TOPIC_PATTERN = "plaintext/quotes/krx/mdds/v2/ohlc/stock/{resolution}/{symbol}"

# Stream key trong Redis: resolution (int) → stream name
_STREAM_MAP = {1: "stream:ohlc:1m", 5: "stream:ohlc:5m"}
_STREAM_MAXLEN = 500_000   # Giới hạn kích thước stream

# JWT refresh timer: mỗi 7h (token hết hạn sau 8h)
_JWT_REFRESH_INTERVAL = 7 * 3600

# Backoff delays khi reconnect (giây)
_BACKOFF = [1, 5, 30, 300]


class MQTTSubscriber:
    """
    Kết nối DNSE MDDS qua MQTT over WSS, nhận OHLC candle messages,
    push vào Redis Streams để processor tiêu thụ.
    """

    def __init__(self) -> None:
        self._auth     = DNSEAuthManager(username=settings.dnse_username, password=settings.dnse_password)
        self._watchlist = WatchlistManager(watchlist_str=settings.realtime_watchlist)
        self._resolutions = [int(r.strip()) for r in settings.realtime_resolutions.split(",") if r.strip()]
        self._redis    = redis_lib.Redis(host=settings.redis_host, port=settings.redis_port, decode_responses=True)
        self._client: mqtt.Client | None = None
        self._running  = False
        self._connected = False

    # ── Public ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Vòng lặp chính — chạy đến khi nhận SIGTERM/SIGINT."""
        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT,  self._shutdown)

        self._schedule_jwt_refresh()
        backoff_idx = 0

        while self._running:
            try:
                self._connect_and_loop()
                backoff_idx = 0   # Reset backoff sau khi kết nối thành công
            except Exception as exc:
                delay = _BACKOFF[min(backoff_idx, len(_BACKOFF) - 1)]
                logger.error(f"[subscriber] Lỗi: {exc}. Reconnect sau {delay}s...")
                backoff_idx += 1
                time.sleep(delay)

        logger.info("[subscriber] Đã dừng.")

    # ── MQTT lifecycle ────────────────────────────────────────────────────

    def _connect_and_loop(self) -> None:
        token       = self._auth.get_token()
        investor_id = self._auth.get_investor_id()
        client_id   = f"dnse-ohlc-sub-{uuid.uuid4().hex[:8]}"

        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id,
            protocol=mqtt.MQTTv5,
            transport="websockets",
        )
        client.username_pw_set(investor_id, token)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
        client.ws_set_options(path="/wss")

        client.on_connect    = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message    = self._on_message

        self._client = client
        logger.info(f"[subscriber] Kết nối MQTT broker ({_BROKER_HOST}:{_BROKER_PORT})...")
        client.connect(_BROKER_HOST, _BROKER_PORT, keepalive=_KEEPALIVE)
        client.loop_forever()   # Blocking — trả về khi disconnect

    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc == 0:
            logger.info("[subscriber] Kết nối MQTT thành công.")
            self._connected = True
            self._subscribe_all(client)
        else:
            logger.error(f"[subscriber] Kết nối MQTT thất bại — rc={rc}")

    def _on_disconnect(self, client, userdata, disconnect_flags, rc, properties=None) -> None:
        self._connected = False
        if self._running:
            logger.warning(f"[subscriber] Mất kết nối MQTT (rc={rc}). Sẽ reconnect...")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            resolution_str = payload.get("resolution", "")
            try:
                resolution = int(resolution_str)
            except (ValueError, TypeError):
                return   # Bỏ qua 1H, 1D... chỉ lưu 1m và 5m

            stream = _STREAM_MAP.get(resolution)
            if stream is None:
                return

            # Redis requires all field values to be strings
            payload["received_at"] = str(int(time.time() * 1000))   # unix ms for latency monitoring
            str_payload = {k: str(v) for k, v in payload.items()}
            self._redis.xadd(stream, str_payload, maxlen=_STREAM_MAXLEN, approximate=True)
        except Exception as exc:
            logger.warning(f"[subscriber] on_message lỗi: {exc}")

    # ── Subscriptions ────────────────────────────────────────────────────

    def _subscribe_all(self, client: mqtt.Client) -> None:
        symbols = self._watchlist.get_symbols()
        topics = []
        for symbol in symbols:
            for resolution in self._resolutions:
                topic = _TOPIC_PATTERN.format(resolution=resolution, symbol=symbol)
                topics.append((topic, _QOS))

        if topics:
            client.subscribe(topics)
            logger.info(f"[subscriber] Subscribed {len(topics)} topics ({len(symbols)} symbols × {len(self._resolutions)} timeframes).")

    # ── JWT auto-refresh ─────────────────────────────────────────────────

    def _schedule_jwt_refresh(self) -> None:
        def _refresh_loop():
            while self._running:
                time.sleep(_JWT_REFRESH_INTERVAL)
                if not self._running:
                    break
                logger.info("[subscriber] Refresh JWT token...")
                self._auth.invalidate()
                if self._client and self._connected:
                    logger.info("[subscriber] Disconnect để reconnect với token mới...")
                    self._client.disconnect()   # _on_disconnect → run() → _connect_and_loop()

        t = threading.Thread(target=_refresh_loop, daemon=True, name="jwt-refresh")
        t.start()

    def _shutdown(self, signum, frame) -> None:
        logger.info("[subscriber] Nhận tín hiệu dừng...")
        self._running = False
        if self._client:
            self._client.disconnect()


if __name__ == "__main__":
    from realtime.session_guard import is_trading_hours
    import sys

    if not is_trading_hours():
        logger.info("[subscriber] Ngoài giờ giao dịch — không khởi động.")
        sys.exit(0)

    MQTTSubscriber().run()
```

- [ ] **Step 2: Verify import works (no syntax errors)**

```bash
venv/Scripts/python.exe -c "from realtime.subscriber import MQTTSubscriber; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add realtime/subscriber.py
git commit -m "feat(rt): add MQTTSubscriber with JWT auto-refresh and backoff reconnect"
```

---

## Task 8: Docker Compose update

**Files:**
- Modify: `docker-compose.yml`

**Context:** Add Redis service + 2 new pipeline services. Redis uses `appendonly yes` for durability. Both realtime services depend on `redis` and `postgres` being healthy.

- [ ] **Step 1: Update `docker-compose.yml`**

Replace the current content with:

```yaml
services:

  # ── PostgreSQL ──────────────────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: stockapp_db
    restart: unless-stopped
    environment:
      POSTGRES_DB:       ${DB_NAME:-stockapp}
      POSTGRES_USER:     ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./db/migrations:/docker-entrypoint-initdb.d
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres}"]
      interval: 10s
      timeout: 5s
      retries: 5

  # ── Redis (message broker for real-time pipeline) ───────────────────────────
  redis:
    image: redis:7-alpine
    container_name: stockapp_redis
    restart: unless-stopped
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: >
      redis-server
      --appendonly yes
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  # ── Batch Pipeline (APScheduler) ─────────────────────────────────────────────
  pipeline:
    build: .
    container_name: stockapp_pipeline
    restart: unless-stopped
    command: python main.py schedule
    env_file: .env
    environment:
      DB_HOST: postgres
      REDIS_HOST: redis
    volumes:
      - ./logs:/app/logs
    depends_on:
      postgres:
        condition: service_healthy

  # ── Real-time: MQTT Subscriber ───────────────────────────────────────────────
  realtime-subscriber:
    build: .
    container_name: stockapp_rt_subscriber
    restart: unless-stopped
    env_file: .env
    environment:
      DB_HOST: postgres
      REDIS_HOST: redis
    command: python -m realtime.subscriber
    volumes:
      - ./logs:/app/logs
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy

  # ── Real-time: Stream Processor ──────────────────────────────────────────────
  realtime-processor:
    build: .
    container_name: stockapp_rt_processor
    restart: unless-stopped
    env_file: .env
    environment:
      DB_HOST: postgres
      REDIS_HOST: redis
    command: python -m realtime.processor
    volumes:
      - ./logs:/app/logs
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      replicas: 1   # Tăng lên 2-3 khi cần scale

volumes:
  postgres_data:
  redis_data:
```

- [ ] **Step 2: Validate docker-compose syntax**

```bash
docker compose config --quiet
```

Expected: No errors (quiet mode prints nothing on success).

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(rt): add redis + realtime subscriber/processor to docker-compose"
```

---

## Task 9: Run all unit tests

- [ ] **Step 1: Run full test suite**

```bash
venv/Scripts/python.exe -m pytest tests/ -v
```

Expected:
```
tests/realtime/test_auth.py          4 passed
tests/realtime/test_watchlist.py     4 passed
tests/realtime/test_session_guard.py 8 passed
tests/realtime/test_processor.py     6 passed
================================ 22 passed ================================
```

- [ ] **Step 2: Fix any failures before proceeding**

---

## Task 10: Live smoke test (manual — requires market hours)

**Context:** This test requires DNSE credentials and must run during trading hours (Mon–Fri 08:45–15:10). It validates the full data flow end-to-end.

**Prerequisite:** Redis must be running locally (`docker compose up redis -d` or local Redis).

- [ ] **Step 1: Start Redis locally**

```bash
docker compose up redis -d
```

Verify: `docker compose exec redis redis-cli ping` → `PONG`

- [ ] **Step 2: Run processor in background**

```bash
venv/Scripts/python.exe -m realtime.processor &
```

- [ ] **Step 3: Run subscriber for 5 minutes (during trading hours)**

```bash
venv/Scripts/python.exe -m realtime.subscriber
```

Expected logs:
```
[auth] Lấy JWT token từ DNSE...
[auth] OK — investorId=XXXXXX
[watchlist] Loaded 30 symbols from DB.
[subscriber] Kết nối MQTT thành công.
[subscriber] Subscribed 60 topics (30 symbols × 2 timeframes).
[processor] stream:ohlc:1m: upserted N rows.
```

- [ ] **Step 4: Verify data in Redis**

```bash
docker compose exec redis redis-cli XLEN stream:ohlc:1m
docker compose exec redis redis-cli XRANGE stream:ohlc:1m - + COUNT 3
```

Expected: At least some messages in the stream.

- [ ] **Step 5: Verify data in PostgreSQL**

```bash
psql -U postgres -d stockapp -c "
  SELECT symbol, resolution, COUNT(*) as candles, MIN(time) as first, MAX(time) as last
  FROM price_intraday
  GROUP BY symbol, resolution
  ORDER BY symbol, resolution
  LIMIT 10;
"
```

Expected: Rows with `resolution = 1` and `resolution = 5` for subscribed symbols.

- [ ] **Step 6: Final commit**

```bash
git add .
git commit -m "feat(rt): real-time pipeline smoke test passed — all components verified"
```

---

## Task 11: Final test run and branch push

- [ ] **Step 1: Run full test suite one more time**

```bash
venv/Scripts/python.exe -m pytest tests/ -v --tb=short
```

Expected: All 22 tests pass.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feature/realtime-pipeline
```

---

## Summary of what was built

| Component | File | Status |
|---|---|---|
| DB table | `db/migrations/007_price_intraday.sql` | ✅ |
| Config | `config/settings.py`, `config/constants.py` | ✅ |
| Auth | `realtime/auth.py` | ✅ |
| Watchlist | `realtime/watchlist.py` | ✅ |
| Session Guard | `realtime/session_guard.py` | ✅ |
| Processor | `realtime/processor.py` | ✅ |
| Subscriber | `realtime/subscriber.py` | ✅ |
| Docker | `docker-compose.yml` | ✅ |
| Tests | `tests/realtime/test_*.py` | ✅ 22 tests |
