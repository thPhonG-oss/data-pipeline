"""
Tests for TimescaleDB migration SQL logic.
These are unit tests that validate SQL content and structure —
they do NOT connect to a real DB.
"""
import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "db" / "migrations"


def _read(name: str) -> str:
    return (MIGRATIONS_DIR / name).read_text(encoding="utf-8")


def test_009_enables_timescaledb_extension():
    sql = _read("009_timescaledb_setup.sql")
    assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in sql


def test_009_drops_id_column():
    sql = _read("009_timescaledb_setup.sql")
    # Must have DROP COLUMN and id together on the same line (co-located)
    assert any(
        "DROP COLUMN" in line and "id" in line
        for line in sql.splitlines()
    ), "Expected 'DROP COLUMN ... id' on a single line"


def test_009_creates_hypertable_price_intraday():
    sql = _read("009_timescaledb_setup.sql")
    # create_hypertable call must reference price_intraday and 'time' in the same block
    assert re.search(
        r"create_hypertable\s*\(\s*'price_intraday'\s*,\s*'time'", sql
    ), "Expected create_hypertable('price_intraday', 'time', ...)"


def test_009_adds_retention_policy_180_days():
    sql = _read("009_timescaledb_setup.sql")
    # Retention policy must name the table and the interval explicitly
    assert "add_retention_policy" in sql
    assert "'price_intraday'" in sql
    assert "180 days" in sql   # documents the accepted 1m/5m compromise


def test_009_adds_compression_policy():
    sql = _read("009_timescaledb_setup.sql")
    assert "timescaledb.compress" in sql
    assert "add_compression_policy" in sql
    assert "'price_intraday'" in sql


def test_009_primary_key_is_idempotent():
    sql = _read("009_timescaledb_setup.sql")
    # ADD PRIMARY KEY must be wrapped in a DO block for idempotency
    assert "DO $$" in sql or "DO $block$" in sql, (
        "ADD PRIMARY KEY must be wrapped in a DO block to be idempotent"
    )
    assert "ADD PRIMARY KEY" in sql


def test_009_primary_key_time_is_leading_column():
    sql = _read("009_timescaledb_setup.sql")
    # time must be the leading PK column for optimal TimescaleDB chunk pruning
    assert re.search(r"ADD PRIMARY KEY\s*\(\s*time\b", sql), (
        "PK must start with 'time' as leading column for TimescaleDB partitioning"
    )
