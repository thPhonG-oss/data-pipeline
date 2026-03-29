"""SQLAlchemy engine, session factory và kiểm tra kết nối."""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import settings

# ── Engine ────────────────────────────────────────────────────────────────────
engine = create_engine(
    settings.database_url,
    pool_size=settings.max_workers + 2,
    max_overflow=settings.max_workers,
    pool_pre_ping=True,  # Kiểm tra connection trước khi dùng
    echo=False,
)

# ── Session factory ───────────────────────────────────────────────────────────
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


# ── Base class cho ORM models ─────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


# ── Context manager tiện lợi ──────────────────────────────────────────────────
@contextmanager
def get_session() -> Generator[Session, None, None]:
    """
    Dùng làm context manager:
        with get_session() as session:
            session.query(...)
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ── Health check ──────────────────────────────────────────────────────────────
def check_connection() -> bool:
    """Kiểm tra kết nối PostgreSQL. Trả về True nếu thành công."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
