"""
Stream Processor — đọc từ Redis Streams và upsert vào PostgreSQL.

Chạy:
  python -m realtime.processor
"""
import os
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
_CONSUMER_NAME = f"worker-{socket.gethostname()}-{os.getpid()}"
_BATCH_SIZE    = 100
_BLOCK_MS      = 5000
_AUTOCLAIM_MS  = 30 * 60 * 1000   # 30 minutes in ms
_TABLE         = "price_intraday"
_CONFLICT_KEYS = CONFLICT_KEYS[_TABLE]

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
    Chuyển đổi raw Redis Stream message dict thành DB row dict.
    Hàm pure — không có I/O. Tất cả values từ Redis đều là string.
    """
    return {
        "symbol":     str(msg["symbol"]).upper(),
        "time":       msg["time"],
        "resolution": int(msg["resolution"]),
        "open":       int(round(float(msg["open"]))),
        "high":       int(round(float(msg["high"]))),
        "low":        int(round(float(msg["low"]))),
        "close":      int(round(float(msg["close"]))),
        "volume":     int(float(msg.get("volume") or 0)),
        "source":     "dnse_mdds",
        "fetched_at": datetime.now(tz=timezone.utc),
    }


# ── StreamProcessor ────────────────────────────────────────────────────────────

class StreamProcessor:
    """Đọc messages từ Redis Streams, validate, transform, upsert PostgreSQL."""

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
        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT,  self._shutdown)
        logger.info(f"[processor] Bắt đầu — consumer: {_CONSUMER_NAME}")

        while self._running:
            try:
                for stream in _STREAMS:
                    self._autoclaim_pending(stream)
                self._read_and_process()
            except redis_lib.ConnectionError as exc:
                logger.error(f"[processor] Redis mất kết nối: {exc}. Retry sau 5s...")
                time.sleep(5)
            except Exception as exc:
                logger.exception(f"[processor] Lỗi không xác định: {exc}")
                time.sleep(1)

        logger.info("[processor] Đã dừng.")

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
            if messages:
                self._process_batch(stream_name, messages)

    def _process_batch(self, stream_name: str, messages: list) -> None:
        rows, ack_ids = [], []
        for msg_id, msg_data in messages:
            if not _validate_message(msg_data):
                logger.warning(f"[processor] Invalid message {msg_id}: {msg_data}")
                ack_ids.append(msg_id)
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
