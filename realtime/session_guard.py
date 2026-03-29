"""Session guard — kiểm tra giờ giao dịch HoSE/HNX."""

import zoneinfo
from datetime import datetime, time

_TZ = zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")
_SESSION_START = time(7, 0)  # Khởi động sớm để kết nối MQTT trước ATO
_SESSION_END = time(15, 10)  # Đóng 10 phút sau ATC


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

    if now.weekday() >= 5:  # Thứ 7 = 5, Chủ Nhật = 6
        return False

    current_time = now.time().replace(tzinfo=None)
    return _SESSION_START <= current_time <= _SESSION_END
