"""
Chạy tất cả migration SQL files theo thứ tự.

Cách dùng:
    python -m db.migrate
    python db/migrate.py
"""
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# Cho phép chạy trực tiếp từ thư mục gốc
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from utils.logger import logger

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def run_migrations() -> None:
    """Thực thi tất cả *.sql trong thư mục migrations theo thứ tự tên file."""
    logger.info(f"Kết nối PostgreSQL: {settings.db_host}:{settings.db_port}/{settings.db_name}")

    try:
        conn = psycopg2.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
        )
    except psycopg2.OperationalError as e:
        logger.error(f"Không thể kết nối PostgreSQL: {e}")
        sys.exit(1)

    conn.autocommit = True
    cursor = conn.cursor()

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        logger.warning(f"Không tìm thấy file SQL trong {MIGRATIONS_DIR}")
        return

    for sql_file in migration_files:
        logger.info(f"▶ Chạy migration: {sql_file.name}")
        try:
            sql = sql_file.read_text(encoding="utf-8")
            cursor.execute(sql)
            logger.success(f"  ✓ {sql_file.name}")
        except Exception as e:
            logger.error(f"  ✗ {sql_file.name} — Lỗi: {e}")
            cursor.close()
            conn.close()
            sys.exit(1)

    cursor.close()
    conn.close()
    logger.success("Tất cả migrations đã chạy thành công.")


if __name__ == "__main__":
    run_migrations()
