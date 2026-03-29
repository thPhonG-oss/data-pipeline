"""Đăng ký và cấu hình tất cả APScheduler jobs."""

import threading

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from utils.logger import logger

# ── Realtime pipeline state ────────────────────────────────────────────────────
_subscriber_instance = None
_subscriber_thread: threading.Thread | None = None


def _safe_run(job_fn, job_name: str):
    """Bọc job trong try/except để lỗi của 1 job không crash scheduler."""

    def wrapper():
        try:
            logger.info(f"[scheduler] Kích hoạt job: {job_name}")
            job_fn()
            logger.success(f"[scheduler] Hoàn thành job: {job_name}")
        except Exception as exc:
            logger.error(f"[scheduler] Job '{job_name}' thất bại: {exc}")

    return wrapper


def _start_realtime_subscriber() -> None:
    """Khởi động MQTT subscriber trong background thread."""
    global _subscriber_instance, _subscriber_thread

    if _subscriber_thread and _subscriber_thread.is_alive():
        logger.info("[scheduler] Realtime subscriber đang chạy — bỏ qua.")
        return

    try:
        from realtime.subscriber import MQTTSubscriber

        _subscriber_instance = MQTTSubscriber()
        _subscriber_thread = threading.Thread(
            target=_subscriber_instance.run,
            daemon=True,
            name="realtime-subscriber",
        )
        _subscriber_thread.start()
        logger.info("[scheduler] Realtime subscriber đã khởi động.")
    except Exception as exc:
        logger.error(f"[scheduler] Không thể khởi động realtime subscriber: {exc}")


def _stop_realtime_subscriber() -> None:
    """Dừng MQTT subscriber sau giờ giao dịch."""
    global _subscriber_instance
    if _subscriber_instance is None:
        return
    try:
        _subscriber_instance._running = False
        if _subscriber_instance._client:
            _subscriber_instance._client.disconnect()
        logger.info("[scheduler] Realtime subscriber đã dừng.")
    except Exception as exc:
        logger.error(f"[scheduler] Lỗi khi dừng subscriber: {exc}")
    finally:
        _subscriber_instance = None


def _start_realtime_processor() -> None:
    """Khởi động stream processor trong background daemon thread."""
    try:
        from realtime.processor import StreamProcessor

        proc = StreamProcessor()
        t = threading.Thread(target=proc.run, daemon=True, name="realtime-processor")
        t.start()
        logger.info("[scheduler] Realtime processor đã khởi động.")
    except Exception as exc:
        logger.error(f"[scheduler] Không thể khởi động realtime processor: {exc}")


def build_scheduler() -> BlockingScheduler:
    """
    Tạo và cấu hình BlockingScheduler với tất cả jobs theo lịch:

    | Job                       | Lịch                          |
    |---------------------------|-------------------------------|
    | sync_listing              | Chủ Nhật 01:00                |
    | sync_hsx_company          | Chủ Nhật 01:30                |
    | sync_company              | Thứ Hai 02:00                 |
    | sync_financials_c         | Ngày 1 & 15 hàng tháng 04:00  |
    | sync_ratios               | Hàng ngày 18:30               |
    | sync_prices               | Thứ 2–6 lúc 19:00             |
    | alert_check               | Hàng giờ :00                  |
    | realtime_subscriber_start | Thứ 2–6 lúc 07:00 (nếu bật)  |
    | realtime_subscriber_stop  | Thứ 2–6 lúc 15:15 (nếu bật)  |
    """
    # Import lazy để tránh circular import và chỉ load khi scheduler thực sự chạy
    import jobs.sync_company as company_job
    import jobs.sync_financials_c as financials_c_job
    import jobs.sync_hsx_company as hsx_company_job
    import jobs.sync_listing as listing_job
    import jobs.sync_prices as prices_job
    import jobs.sync_ratios as ratios_job
    from utils.alert_checker import check_and_alert

    scheduler = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")

    scheduler.add_job(
        _safe_run(listing_job.run, "sync_listing"),
        CronTrigger.from_crontab(settings.cron_sync_listing, timezone="Asia/Ho_Chi_Minh"),
        id="sync_listing",
        name="Đồng bộ danh mục mã & ngành ICB",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _safe_run(hsx_company_job.run, "sync_hsx_company"),
        CronTrigger.from_crontab(settings.cron_sync_hsx_company, timezone="Asia/Ho_Chi_Minh"),
        id="sync_hsx_company",
        name="Enrich thông tin công ty HOSE từ HSX API",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _safe_run(company_job.run, "sync_company"),
        CronTrigger.from_crontab(settings.cron_sync_company, timezone="Asia/Ho_Chi_Minh"),
        id="sync_company",
        name="Đồng bộ thông tin doanh nghiệp",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _safe_run(financials_c_job.run, "sync_financials_c"),
        CronTrigger.from_crontab(settings.cron_sync_financials_c, timezone="Asia/Ho_Chi_Minh"),
        id="sync_financials_c",
        name="Đồng bộ BCTC + ratio (Approach C — 4 bảng riêng)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _safe_run(ratios_job.run, "sync_ratios"),
        CronTrigger.from_crontab(settings.cron_sync_ratios, timezone="Asia/Ho_Chi_Minh"),
        id="sync_ratios",
        name="Đồng bộ ratio_summary (sau đóng cửa)",
        misfire_grace_time=1800,
    )

    scheduler.add_job(
        _safe_run(prices_job.run, "sync_prices"),
        CronTrigger.from_crontab(settings.cron_sync_prices, timezone="Asia/Ho_Chi_Minh"),
        id="sync_prices",
        name="Đồng bộ giá lịch sử OHLCV (DNSE + VNDirect fallback)",
        misfire_grace_time=3600,
    )

    scheduler.add_job(
        _safe_run(check_and_alert, "alert_check"),
        CronTrigger.from_crontab(settings.cron_alert_check, timezone="Asia/Ho_Chi_Minh"),
        id="alert_check",
        name="Kiểm tra pipeline_logs, gửi alert Telegram nếu có sự cố",
        misfire_grace_time=300,
    )

    # ── Realtime pipeline (subscriber start/stop + processor always-on) ───────
    if settings.realtime_enabled:
        # Processor chạy 24/7 ngay khi scheduler boot
        _start_realtime_processor()

        scheduler.add_job(
            _start_realtime_subscriber,
            CronTrigger.from_crontab(settings.cron_realtime_start, timezone="Asia/Ho_Chi_Minh"),
            id="realtime_subscriber_start",
            name="Khởi động MQTT subscriber (trước ATO)",
            misfire_grace_time=1800,
        )

        scheduler.add_job(
            _stop_realtime_subscriber,
            CronTrigger.from_crontab(settings.cron_realtime_stop, timezone="Asia/Ho_Chi_Minh"),
            id="realtime_subscriber_stop",
            name="Dừng MQTT subscriber (sau ATC)",
            misfire_grace_time=1800,
        )

        logger.info(
            f"[scheduler] Realtime pipeline: bật. "
            f"Subscriber: {settings.cron_realtime_start} → {settings.cron_realtime_stop}"
        )
    else:
        logger.info("[scheduler] Realtime pipeline: tắt (REALTIME_ENABLED=false).")

    return scheduler
