import io
import sys
from pathlib import Path

from loguru import logger as _logger

# Đảm bảo stdout dùng UTF-8 trên Windows (tránh lỗi encode tiếng Việt)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def setup_logger(log_level: str = "INFO", log_dir: str = "logs") -> None:
    """Cấu hình loguru: ghi ra stdout và file xoay theo ngày."""
    _logger.remove()

    # Console — màu sắc, dễ đọc khi dev
    _logger.add(
        sys.stdout,
        level=log_level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
    )

    # File — xoay lúc 00:00, giữ 30 ngày, nén zip
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    _logger.add(
        Path(log_dir) / "pipeline_{time:YYYY-MM-DD}.log",
        level="DEBUG",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        encoding="utf-8",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} — {message}",
    )


# Khởi tạo logger với giá trị mặc định; sẽ được gọi lại với settings thực
# khi ứng dụng chạy (xem db/connection.py hoặc main.py)
try:
    from config.settings import settings

    setup_logger(settings.log_level, settings.log_dir)
except Exception:
    setup_logger()

logger = _logger
