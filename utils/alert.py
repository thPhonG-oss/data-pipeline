"""Gửi cảnh báo qua Telegram khi pipeline gặp sự cố."""
import requests

from utils.logger import logger


def send_telegram(message: str) -> bool:
    """Gửi tin nhắn đến Telegram. Trả về True nếu thành công."""
    from config.settings import settings

    token = settings.telegram_bot_token
    chat_id = settings.telegram_chat_id

    if not token or not chat_id:
        logger.debug("[alert] Telegram chưa cấu hình, bỏ qua.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning(f"[alert] Gửi Telegram thất bại: {exc}")
        return False
