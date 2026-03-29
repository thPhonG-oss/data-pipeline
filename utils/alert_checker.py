"""Kiểm tra pipeline_logs và gửi alert khi job thất bại liên tiếp."""

from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import text

from db.connection import engine
from utils.alert import send_telegram
from utils.logger import logger


def check_and_alert(threshold: int | None = None, window_hours: int = 24) -> None:
    """
    Gửi alert nếu bất kỳ job nào thất bại >= threshold lần trong window_hours giờ gần nhất.
    Không alert nếu Telegram chưa được cấu hình.
    """
    from config.settings import settings

    if threshold is None:
        threshold = settings.alert_fail_threshold

    since = datetime.now(tz=UTC) - timedelta(hours=window_hours)

    with engine.connect() as conn:
        rows = conn.execute(
            text("""
                SELECT job_name, COUNT(*) AS fail_count
                FROM pipeline_logs
                WHERE status = 'failed' AND started_at >= :since
                GROUP BY job_name
                HAVING COUNT(*) >= :threshold
                ORDER BY fail_count DESC
            """),
            {"since": since, "threshold": threshold},
        ).fetchall()

    if not rows:
        return

    lines = [f"*⚠️ Pipeline Alert* — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
    lines.append(f"Job thất bại ≥ {threshold} lần trong {window_hours}h qua:\n")
    for row in rows:
        lines.append(f"  • `{row.job_name}`: *{row.fail_count} lần*")
    lines.append("\nDữ liệu trên web app có thể không được cập nhật.")

    message = "\n".join(lines)
    logger.warning(f"[alert] Phát hiện job thất bại liên tiếp: {dict(rows)}")
    send_telegram(message)
