"""Decorator retry dùng tenacity, tuân theo cấu hình trong settings."""
import functools
from typing import Callable, Type

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from utils.logger import logger


def vnstock_retry(
    attempts: int | None = None,
    wait_min: float | None = None,
    wait_max: float | None = None,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    Decorator retry cho vnstock API calls với exponential backoff.

    Nếu không truyền tham số, lấy giá trị từ settings.
    Ví dụ:
        @vnstock_retry()
        def fetch_data(symbol): ...

        @vnstock_retry(attempts=5, wait_min=2, wait_max=30)
        def fetch_heavy_data(symbol): ...
    """
    from config.settings import settings

    _attempts = attempts if attempts is not None else settings.retry_attempts
    _wait_min = wait_min if wait_min is not None else settings.retry_wait_min
    _wait_max = wait_max if wait_max is not None else settings.retry_wait_max

    def decorator(func: Callable) -> Callable:
        @retry(
            stop=stop_after_attempt(_attempts),
            wait=wait_exponential(multiplier=1, min=_wait_min, max=_wait_max),
            retry=retry_if_exception_type(exceptions),
            before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
            reraise=True,
        )
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        return wrapper

    return decorator
