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


def _split_sql(sql: str) -> list[str]:
    """
    Split SQL into individual statements, respecting:
      - -- line comments  (semicolons inside ignored)
      - $$ dollar-quoted blocks (semicolons inside ignored)
    """
    statements: list[str] = []
    current: list[str] = []
    in_line_comment = False
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
            # Execute one statement at a time so TimescaleDB DDL (continuous
            # aggregates) doesn't hit "cannot run inside a transaction block".
            statements = _split_sql(sql)
            for stmt in statements:
                cursor.execute(stmt)
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
