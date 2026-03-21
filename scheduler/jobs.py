"""Đăng ký và cấu hình tất cả APScheduler jobs."""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from utils.logger import logger


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


def build_scheduler() -> BlockingScheduler:
    """
    Tạo và cấu hình BlockingScheduler với 5 jobs theo lịch:

    | Job              | Lịch                          |
    |------------------|-------------------------------|
    | sync_listing     | Chủ Nhật 01:00                |
    | sync_financials  | Ngày 1 và 15 hàng tháng 03:00 |
    | sync_company     | Thứ Hai 02:00                 |
    | sync_ratios      | Hàng ngày 18:30               |
    | sync_prices      | Thứ 2–6 lúc 19:00             |
    | alert_check      | Hàng giờ :00                  |
    """
    # Import lazy để tránh circular import và chỉ load khi scheduler thực sự chạy
    import jobs.sync_listing    as listing_job
    import jobs.sync_financials as financials_job
    import jobs.sync_company    as company_job
    import jobs.sync_ratios     as ratios_job
    import jobs.sync_prices     as prices_job
    from utils.alert_checker import check_and_alert

    scheduler = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")

    scheduler.add_job(
        _safe_run(listing_job.run, "sync_listing"),
        CronTrigger.from_crontab(settings.cron_sync_listing, timezone="Asia/Ho_Chi_Minh"),
        id="sync_listing",
        name="Đồng bộ danh mục mã & ngành ICB",
        misfire_grace_time=3600,   # Bỏ qua nếu trễ hơn 1 giờ
    )

    scheduler.add_job(
        _safe_run(financials_job.run, "sync_financials"),
        CronTrigger.from_crontab(settings.cron_sync_financials, timezone="Asia/Ho_Chi_Minh"),
        id="sync_financials",
        name="Đồng bộ báo cáo tài chính",
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
        _safe_run(ratios_job.run, "sync_ratios"),
        CronTrigger.from_crontab(settings.cron_sync_ratios, timezone="Asia/Ho_Chi_Minh"),
        id="sync_ratios",
        name="Đồng bộ ratio_summary (sau đóng cửa)",
        misfire_grace_time=1800,   # Bỏ qua nếu trễ hơn 30 phút
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
        misfire_grace_time=300,    # Bỏ qua nếu trễ hơn 5 phút
    )

    return scheduler
