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


def test_010_drops_id_column_price_history():
    sql = _read("010_timescaledb_price_history.sql")
    assert any(
        "DROP COLUMN" in line and "id" in line
        for line in sql.splitlines()
    ), "Expected 'DROP COLUMN ... id' on a single line"


def test_010_creates_hypertable_price_history():
    sql = _read("010_timescaledb_price_history.sql")
    assert re.search(
        r"create_hypertable\s*\(\s*'price_history'\s*,\s*'date'", sql
    ), "Expected create_hypertable('price_history', 'date', ...)"


def test_010_chunk_interval_is_integer_not_interval():
    sql = _read("010_timescaledb_price_history.sql")
    assert "chunk_time_interval => 90" in sql, (
        "price_history.date is a DATE column: chunk_time_interval must be integer (90), "
        "not INTERVAL — see TimescaleDB docs"
    )


def test_010_primary_key_is_idempotent():
    sql = _read("010_timescaledb_price_history.sql")
    assert "DO $$" in sql or "DO $block$" in sql
    assert "ADD PRIMARY KEY" in sql


def test_010_primary_key_date_is_leading_column():
    sql = _read("010_timescaledb_price_history.sql")
    assert re.search(r"ADD PRIMARY KEY\s*\(\s*date\b", sql), (
        "PK must start with 'date' as leading column for TimescaleDB partitioning"
    )


def test_010_adds_compression_policy():
    sql = _read("010_timescaledb_price_history.sql")
    assert "timescaledb.compress" in sql
    assert "add_compression_policy" in sql
    assert "'price_history'" in sql


def test_011_creates_cagg_5m_from_price_intraday():
    sql = _read("011_continuous_aggregates.sql")
    assert "cagg_ohlc_5m" in sql
    assert "timescaledb.continuous" in sql
    assert re.search(r"FROM\s+price_intraday", sql), "cagg_ohlc_5m must query FROM price_intraday"
    assert re.search(r"resolution\s*=\s*1", sql), "Must filter WHERE resolution = 1 (1m candles only)"


def test_011_creates_cagg_1h_from_cagg_5m():
    sql = _read("011_continuous_aggregates.sql")
    assert "cagg_ohlc_1h" in sql
    assert re.search(r"FROM\s+cagg_ohlc_5m", sql), "cagg_ohlc_1h must query FROM cagg_ohlc_5m"


def test_011_creates_cagg_1d_from_cagg_1h():
    sql = _read("011_continuous_aggregates.sql")
    assert "cagg_ohlc_1d" in sql
    assert re.search(r"FROM\s+cagg_ohlc_1h", sql), "cagg_ohlc_1d must query FROM cagg_ohlc_1h"


def test_011_adds_refresh_policies_for_all_three():
    sql = _read("011_continuous_aggregates.sql")
    count = sql.count("add_continuous_aggregate_policy")
    assert count >= 3, f"Expected >= 3 refresh policies, found {count}"


def test_011_uses_first_last_with_two_args():
    sql = _read("011_continuous_aggregates.sql")
    assert re.search(r"first\(\w+\s*,\s*\w+\)", sql), "first() must have 2 args: first(value, time)"
    assert re.search(r"last\(\w+\s*,\s*\w+\)", sql), "last() must have 2 args: last(value, time)"


def test_011_source_caggs_use_materialized_only_true():
    sql = _read("011_continuous_aggregates.sql")
    assert sql.count("materialized_only = TRUE") >= 2, (
        "cagg_ohlc_5m and cagg_ohlc_1h must set materialized_only = TRUE "
        "(required for hierarchical CAgg sources in TimescaleDB 2.x)"
    )
