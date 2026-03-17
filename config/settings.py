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
    vnstock_api_key: str = "vnstock_d3a641fe0794fe26c1e910bf0cc6ebe8"

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
