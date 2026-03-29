"""
Bootstrap script — chạy MỘT LẦN DUY NHẤT trên DB đang chạy.

Dùng khi:
  - DB đã có schema từ docker-entrypoint-initdb.d (7 files 001–007)
  - Bảng schema_migrations chưa tồn tại
  - Muốn chuyển sang dùng migrate.py có tracking mà không re-run lại

Script này sẽ:
  1. Tạo bảng schema_migrations
  2. Đăng ký tất cả file *.sql hiện có với applied_at = NOW()
     (giả định tất cả đã được chạy qua docker-entrypoint-initdb.d)

Cách dùng:
    python db/migrate_bootstrap.py

SAU KHI CHẠY: dùng `python -m db.migrate` cho tất cả các lần tiếp theo.
"""

import hashlib
import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings
from utils.logger import logger

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def bootstrap() -> None:
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
        logger.error(f"Không thể kết nối: {e}")
        sys.exit(1)

    conn.autocommit = True
    cursor = conn.cursor()

    # Kiểm tra xem bảng đã tồn tại chưa
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = 'schema_migrations'
        )
    """)
    already_exists = cursor.fetchone()[0]

    if already_exists:
        cursor.execute("SELECT COUNT(*) FROM schema_migrations")
        count = cursor.fetchone()[0]
        logger.info(f"Bảng schema_migrations đã tồn tại với {count} records — bỏ qua bootstrap.")
        cursor.close()
        conn.close()
        return

    # Tạo bảng tracking
    cursor.execute("""
        CREATE TABLE schema_migrations (
            filename    TEXT        PRIMARY KEY,
            checksum    TEXT        NOT NULL,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    logger.info("Đã tạo bảng schema_migrations.")

    # Đăng ký tất cả file hiện có
    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for f in migration_files:
        sql = f.read_text(encoding="utf-8")
        checksum = hashlib.md5(sql.encode()).hexdigest()
        cursor.execute(
            "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
            (f.name, checksum),
        )
        logger.success(f"  ✓ Đã đăng ký: {f.name}")

    cursor.close()
    conn.close()
    logger.success(
        f"Bootstrap hoàn tất — {len(migration_files)} migrations đã được đánh dấu là applied.\n"
        "Từ nay dùng `python -m db.migrate` cho các migration mới."
    )


if __name__ == "__main__":
    bootstrap()
