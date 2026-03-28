from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ──────────────────────────────────────────────
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "stockapp"
    db_user: str = "postgres"
    db_password: str = "postgres"

    # ── Redis ─────────────────────────────────────────────────
    redis_host: str = "localhost"
    redis_port: int = 6379

    # ── Vnstock ───────────────────────────────────────────────
    vnstock_source: str = "vci"
    vnstock_api_key: str = ""

    # ── Pipeline ──────────────────────────────────────────────
    max_workers: int = 5
    request_delay: float = 0.3      # Giây nghỉ giữa các API request
    retry_attempts: int = 3
    retry_wait_min: float = 1.0     # Giây chờ tối thiểu khi retry
    retry_wait_max: float = 10.0    # Giây chờ tối đa khi retry
    db_chunk_size: int = 500        # Số dòng mỗi batch khi upsert

    # ── Logging ───────────────────────────────────────────────
    log_level: str = "INFO"
    log_dir: str = "logs"

    # ── Scheduler (cron expressions — chuẩn Unix 5-field) ────
    cron_sync_listing:    str = "0 1 * * 0"       # Chủ Nhật 01:00
    cron_sync_financials: str = "0 3 1,15 * *"    # Ngày 1 & 15 hàng tháng 03:00
    cron_sync_company:    str = "0 2 * * 1"        # Thứ Hai 02:00
    cron_sync_ratios:     str = "30 18 * * *"      # Hàng ngày 18:30
    cron_sync_prices:          str = "0 19 * * 1-5"   # Thứ 2–6 lúc 19:00 (sau đóng cửa)
    cron_alert_check:          str = "0 * * * *"      # Hàng giờ :00
    cron_realtime_start:       str = "0 7 * * 1-5"    # Thứ 2–6 lúc 07:00 (trước ATO)
    cron_realtime_stop:        str = "15 15 * * 1-5"  # Thứ 2–6 lúc 15:15 (sau ATC)
    realtime_enabled:          bool = True             # Tắt/bật realtime pipeline

    # ── DNSE ──────────────────────────────────────────────────
    dnse_username: str = ""   # Email hoặc SĐT đăng ký tài khoản DNSE
    dnse_password: str = ""   # Mật khẩu đăng nhập DNSE

    # ── Real-time pipeline ─────────────────────────────────────
    # CSV danh sách symbol, vd: "HPG,VCB,FPT". Rỗng = dùng VN30 từ DB.
    realtime_watchlist: str = ""
    # Timeframes cần subscribe, phân cách bằng dấu phẩy: "1,5"
    realtime_resolutions: str = "1,5"

    # ── Alert ─────────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    alert_fail_threshold: int = 3

    @computed_field
    @property
    def database_url(self) -> str:
        return (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()
