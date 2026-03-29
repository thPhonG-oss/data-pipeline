import zoneinfo
from datetime import datetime

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
    # Monday 06:59 — too early (SESSION_START = 07:00)
    (datetime(2026, 3, 23, 6, 59, tzinfo=_TZ),  False),
    # Monday 15:11 — too late
    (datetime(2026, 3, 23, 15, 11, tzinfo=_TZ), False),
    # Monday 07:00 — start of window (inclusive)
    (datetime(2026, 3, 23, 7, 0, tzinfo=_TZ),   True),
    # Monday 15:10 — end of window (inclusive)
    (datetime(2026, 3, 23, 15, 10, tzinfo=_TZ), True),
])
def test_is_trading_hours(dt, expected):
    assert is_trading_hours(dt) == expected
