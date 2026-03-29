"""
Chạy migration SQL files theo thứ tự — chỉ những file chưa được apply.

Cách dùng:
    python -m db.migrate
    python db/migrate.py

Tracking:
    Bảng `schema_migrations` được tạo tự động trong DB để ghi lại
    các file đã chạy. Mỗi file chỉ chạy đúng một lần.
"""
import hashlib
import sys
from pathlib import Path

import psycopg2
import psycopg2.extras

# Cho phép chạy trực tiếp từ thư mục gốc
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from utils.logger import logger

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# DDL cho bảng tracking — chạy trước mọi migration
_CREATE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    TEXT        PRIMARY KEY,
    checksum    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def _split_sql(sql: str) -> list[str]:
    """
    Split SQL into individual statements, respecting:
      - -- line comments  (semicolons inside ignored)
      - $$ dollar-quoted blocks (semicolons inside ignored)
    """
    statements: list[str] = []
    current: list[str] = []
    dollar_quote: str | None = None  # e.g. "$$" or "$tag$"
    i = 0

    while i < len(sql):
        ch = sql[i]

        # ── Inside a dollar-quoted block ──────────────────────────────
        if dollar_quote is not None:
            current.append(ch)
            if sql[i:i + len(dollar_quote)] == dollar_quote:
                # Consume the closing tag
                current.append(sql[i + 1:i + len(dollar_quote)])
                i += len(dollar_quote)
                dollar_quote = None
            else:
                i += 1
            continue

        # ── Line comment ──────────────────────────────────────────────
        if ch == "-" and sql[i:i + 2] == "--":
            # Skip to end of line
            while i < len(sql) and sql[i] != "\n":
                i += 1
            continue

        # ── Detect start of dollar-quote ──────────────────────────────
        if ch == "$":
            end = sql.find("$", i + 1)
            if end != -1:
                tag = sql[i:end + 1]  # e.g. "$$" or "$body$"
                dollar_quote = tag
                current.append(sql[i:end + 1])
                i = end + 1
                continue

        # ── Statement terminator ──────────────────────────────────────
        if ch == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
            continue

        current.append(ch)
        i += 1

    # Trailing statement without semicolon
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)

    return statements


def _checksum(sql: str) -> str:
    """MD5 của nội dung file — dùng để phát hiện file migration bị sửa sau khi apply."""
    return hashlib.md5(sql.encode()).hexdigest()


def _get_applied(cursor) -> dict[str, str]:
    """Trả về {filename: checksum} của các migrations đã chạy."""
    cursor.execute("SELECT filename, checksum FROM schema_migrations ORDER BY filename")
    return {row[0]: row[1] for row in cursor.fetchall()}


def _mark_applied(cursor, filename: str, checksum: str) -> None:
    cursor.execute(
        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)",
        (filename, checksum),
    )


def run_migrations() -> None:
    """Chỉ thực thi các file *.sql chưa được apply, theo thứ tự tên file."""
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

    # Đảm bảo bảng tracking tồn tại trước khi làm bất cứ điều gì
    cursor.execute(_CREATE_TRACKING_TABLE)

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        logger.warning(f"Không tìm thấy file SQL trong {MIGRATIONS_DIR}")
        cursor.close()
        conn.close()
        return

    applied = _get_applied(cursor)
    pending = [f for f in migration_files if f.name not in applied]

    if not pending:
        logger.info("Không có migration mới. DB đã up-to-date.")
        cursor.close()
        conn.close()
        return

    logger.info(
        f"{len(applied)} migration đã apply, "
        f"{len(pending)}/{len(migration_files)} migration mới cần chạy."
    )

    # Cảnh báo nếu file đã apply bị sửa nội dung
    for f in migration_files:
        if f.name in applied:
            sql = f.read_text(encoding="utf-8")
            if _checksum(sql) != applied[f.name]:
                logger.warning(
                    f"  ⚠ {f.name} đã bị sửa sau khi apply "
                    f"(checksum không khớp) — bỏ qua."
                )

    for sql_file in pending:
        logger.info(f"▶ Chạy migration: {sql_file.name}")
        try:
            sql = sql_file.read_text(encoding="utf-8")
            # Execute one statement at a time so TimescaleDB DDL (continuous
            # aggregates) doesn't hit "cannot run inside a transaction block".
            statements = _split_sql(sql)
            for stmt in statements:
                cursor.execute(stmt)
            _mark_applied(cursor, sql_file.name, _checksum(sql))
            logger.success(f"  ✓ {sql_file.name}")
        except Exception as e:
            logger.error(f"  ✗ {sql_file.name} — Lỗi: {e}")
            cursor.close()
            conn.close()
            sys.exit(1)

    cursor.close()
    conn.close()
    logger.success(f"{len(pending)} migration đã chạy thành công.")


if __name__ == "__main__":
    run_migrations()
