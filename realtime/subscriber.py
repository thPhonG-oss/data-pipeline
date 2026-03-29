"""
MQTT Subscriber — kết nối DNSE MDDS, nhận OHLC, push vào Redis Streams.

Chạy:
  python -m realtime.subscriber

Vòng lặp sống:
  1. Auth DNSE → JWT + investorId
  2. Kết nối MQTT broker
  3. Subscribe OHLC topics cho watchlist
  4. Nhận messages → XADD Redis Streams (all values stringified)
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

_BROKER_HOST = "datafeed-lts-krx.dnse.com.vn"
_BROKER_PORT = 443
_KEEPALIVE = 1200
_QOS = 1
_TOPIC_PATTERN = "plaintext/quotes/krx/mdds/v2/ohlc/stock/{resolution}/{symbol}"

_STREAM_MAP = {1: "stream:ohlc:1m", 5: "stream:ohlc:5m"}
_STREAM_MAXLEN = 500_000

_JWT_REFRESH_INTERVAL = 7 * 3600  # seconds

_BACKOFF = [1, 5, 30, 300]


class MQTTSubscriber:
    """
    Kết nối DNSE MDDS qua MQTT over WSS, nhận OHLC candle messages,
    push vào Redis Streams để processor tiêu thụ.
    """

    def __init__(self) -> None:
        self._auth = DNSEAuthManager(
            username=settings.dnse_username, password=settings.dnse_password
        )
        self._watchlist = WatchlistManager(watchlist_str=settings.realtime_watchlist)
        self._resolutions = [
            int(r.strip()) for r in settings.realtime_resolutions.split(",") if r.strip()
        ]
        self._redis = redis_lib.Redis(
            host=settings.redis_host, port=settings.redis_port, decode_responses=True
        )
        self._client: mqtt.Client | None = None
        self._running = False
        self._connected = False

    # ── Public ────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Vòng lặp chính — chạy đến khi nhận SIGTERM/SIGINT."""
        self._running = True
        signal.signal(signal.SIGTERM, self._shutdown)
        signal.signal(signal.SIGINT, self._shutdown)

        self._schedule_jwt_refresh()
        backoff_idx = 0

        while self._running:
            try:
                self._connect_and_loop()
                backoff_idx = 0
            except Exception as exc:
                delay = _BACKOFF[min(backoff_idx, len(_BACKOFF) - 1)]
                logger.error(f"[subscriber] Lỗi: {exc}. Reconnect sau {delay}s...")
                backoff_idx += 1
                time.sleep(delay)

        logger.info("[subscriber] Đã dừng.")

    # ── MQTT lifecycle ────────────────────────────────────────────────────

    def _connect_and_loop(self) -> None:
        token = self._auth.get_token()
        investor_id = self._auth.get_investor_id()
        client_id = f"dnse-ohlc-sub-{uuid.uuid4().hex[:8]}"

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

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        self._client = client
        logger.info(f"[subscriber] Kết nối MQTT broker ({_BROKER_HOST}:{_BROKER_PORT})...")
        client.connect(_BROKER_HOST, _BROKER_PORT, keepalive=_KEEPALIVE)
        client.loop_forever()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if not reason_code.is_failure:
            logger.info("[subscriber] Kết nối MQTT thành công.")
            self._connected = True
            self._subscribe_all(client)
        else:
            logger.error(f"[subscriber] Kết nối MQTT thất bại — {reason_code}")

    def _on_disconnect(
        self, client, userdata, disconnect_flags, reason_code, properties=None
    ) -> None:
        self._connected = False
        if self._running:
            logger.warning(f"[subscriber] Mất kết nối MQTT ({reason_code}). Sẽ reconnect...")

    def _on_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            resolution_str = str(payload.get("resolution", ""))
            try:
                resolution = int(resolution_str)
            except (ValueError, TypeError):
                return

            stream = _STREAM_MAP.get(resolution)
            if stream is None:
                return

            # Redis requires string values; add received_at for latency monitoring
            payload["received_at"] = str(int(time.time() * 1000))
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
            logger.info(
                f"[subscriber] Subscribed {len(topics)} topics ({len(symbols)} symbols × {len(self._resolutions)} timeframes)."
            )

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
                    self._client.disconnect()

        t = threading.Thread(target=_refresh_loop, daemon=True, name="jwt-refresh")
        t.start()

    def _shutdown(self, signum, frame) -> None:
        logger.info("[subscriber] Nhận tín hiệu dừng...")
        self._running = False
        if self._client:
            self._client.disconnect()


if __name__ == "__main__":
    import sys

    from realtime.session_guard import is_trading_hours

    if not is_trading_hours():
        logger.info("[subscriber] Ngoài giờ giao dịch — không khởi động.")
        sys.exit(0)

    MQTTSubscriber().run()
