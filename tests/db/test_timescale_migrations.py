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


# ── Migration 001: extensions ─────────────────────────────────────────────────


def test_001_enables_timescaledb_extension():
    sql = _read("001_extensions.sql")
    assert "CREATE EXTENSION IF NOT EXISTS timescaledb" in sql


# ── Migration 007: TimescaleDB hypertables, retention, compression, CAggs ─────


def test_007_creates_hypertable_price_intraday():
    sql = _read("007_timescaledb.sql")
    assert re.search(r"create_hypertable\s*\(\s*'price_intraday'\s*,\s*'time'", sql), (
        "Expected create_hypertable('price_intraday', 'time', ...)"
    )


def test_007_adds_retention_policy_180_days():
    sql = _read("007_timescaledb.sql")
    assert "add_retention_policy" in sql
    assert "'price_intraday'" in sql
    assert "180 days" in sql


def test_007_adds_compression_policy_price_intraday():
    sql = _read("007_timescaledb.sql")
    assert "timescaledb.compress" in sql
    assert "add_compression_policy" in sql
    assert "'price_intraday'" in sql


def test_007_creates_hypertable_price_history():
    sql = _read("007_timescaledb.sql")
    assert re.search(r"create_hypertable\s*\(\s*'price_history'\s*,\s*'date'", sql), (
        "Expected create_hypertable('price_history', 'date', ...)"
    )


def test_007_chunk_interval_price_history_is_90_days():
    sql = _read("007_timescaledb.sql")
    # TimescaleDB 2.x interprets bare integer as microseconds, not days.
    # Must use INTERVAL '90 days' to get correct 90-day chunks.
    assert "INTERVAL '90 days'" in sql, (
        "chunk_time_interval must be INTERVAL '90 days' — bare integer 90 is "
        "interpreted as 90 microseconds in TimescaleDB 2.x"
    )


def test_007_adds_compression_policy_price_history():
    sql = _read("007_timescaledb.sql")
    assert "'price_history'" in sql
    assert "add_compression_policy" in sql


def test_007_creates_cagg_5m_from_price_intraday():
    sql = _read("007_timescaledb.sql")
    assert "cagg_ohlc_5m" in sql
    assert "timescaledb.continuous" in sql
    assert re.search(r"FROM\s+price_intraday", sql), "cagg_ohlc_5m must query FROM price_intraday"
    assert re.search(r"resolution\s*=\s*1", sql), (
        "Must filter WHERE resolution = 1 (1m candles only)"
    )


def test_007_creates_cagg_1h_from_cagg_5m():
    sql = _read("007_timescaledb.sql")
    assert "cagg_ohlc_1h" in sql
    assert re.search(r"FROM\s+cagg_ohlc_5m", sql), "cagg_ohlc_1h must query FROM cagg_ohlc_5m"


def test_007_creates_cagg_1d_from_cagg_1h():
    sql = _read("007_timescaledb.sql")
    assert "cagg_ohlc_1d" in sql
    assert re.search(r"FROM\s+cagg_ohlc_1h", sql), "cagg_ohlc_1d must query FROM cagg_ohlc_1h"


def test_007_adds_refresh_policies_for_all_three():
    sql = _read("007_timescaledb.sql")
    count = sql.count("add_continuous_aggregate_policy")
    assert count >= 3, f"Expected >= 3 refresh policies, found {count}"


def test_007_uses_first_last_with_two_args():
    sql = _read("007_timescaledb.sql")
    assert re.search(r"first\(\w+\s*,\s*\w+\)", sql), "first() must have 2 args: first(value, time)"
    assert re.search(r"last\(\w+\s*,\s*\w+\)", sql), "last() must have 2 args: last(value, time)"


def test_007_source_caggs_use_materialized_only_true():
    sql = _read("007_timescaledb.sql")
    assert sql.count("materialized_only = TRUE") >= 2, (
        "cagg_ohlc_5m and cagg_ohlc_1h must set materialized_only = TRUE "
        "(required for hierarchical CAgg sources in TimescaleDB 2.x)"
    )


# ── Migration 006: price tables have composite PK (no id column) ──────────────


def test_006_price_intraday_has_composite_pk():
    sql = _read("006_price_tables.sql")
    # Tables must be created with composite PK — no serial id column needed
    assert re.search(r"PRIMARY KEY\s*\(\s*time\b", sql), (
        "price_intraday PK must start with 'time' for TimescaleDB partitioning"
    )


def test_006_price_history_has_composite_pk():
    sql = _read("006_price_tables.sql")
    assert re.search(r"PRIMARY KEY\s*\(\s*date\b", sql), (
        "price_history PK must start with 'date' for TimescaleDB partitioning"
    )


# ── Utility script ─────────────────────────────────────────────────────────────


def test_check_timescale_script_exists():
    script = Path(__file__).parent.parent.parent / "db" / "check_timescale.py"
    assert script.exists(), "db/check_timescale.py not found"


def test_check_timescale_imports_are_correct():
    script = (Path(__file__).parent.parent.parent / "db" / "check_timescale.py").read_text(
        encoding="utf-8"
    )
    assert "timescaledb_information" in script  # queries TimescaleDB catalog
    assert "hypertables" in script
    assert "policy_retention" in script  # retention policy jobs
    assert "policy_compression" in script  # compression policy jobs
