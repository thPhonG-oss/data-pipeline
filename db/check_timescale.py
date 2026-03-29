"""
Check TimescaleDB status after running migrations.

Usage:
    python -m db.check_timescale
    python db/check_timescale.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2

from config.settings import settings
from utils.logger import logger


def check_timescale() -> bool:
    """
    Connect to DB and verify all TimescaleDB configuration.
    Returns True if everything is OK.
    """
    try:
        conn = psycopg2.connect(
            host=settings.db_host,
            port=settings.db_port,
            dbname=settings.db_name,
            user=settings.db_user,
            password=settings.db_password,
        )
    except psycopg2.OperationalError as e:
        logger.error(f"Cannot connect to PostgreSQL: {e}")
        return False

    ok = True
    try:
        cur = conn.cursor()

        # 1. Extension
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';")
        row = cur.fetchone()
        if row:
            logger.success(f"OK TimescaleDB extension: v{row[0]}")
        else:
            logger.error("FAIL TimescaleDB extension not installed")
            ok = False

        # 2. Hypertables
        cur.execute("""
            SELECT hypertable_name, num_chunks
            FROM timescaledb_information.hypertables
            ORDER BY hypertable_name;
        """)
        hypertables = {r[0]: r[1] for r in cur.fetchall()}
        for tbl in ["price_intraday", "price_history"]:
            if tbl in hypertables:
                logger.success(f"OK Hypertable '{tbl}': {hypertables[tbl]} chunks")
            else:
                logger.error(f"FAIL '{tbl}' is not a hypertable")
                ok = False

        # 3. Retention policies
        cur.execute("""
            SELECT hypertable_name, config
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_retention'
            ORDER BY hypertable_name;
        """)
        retention = {r[0] for r in cur.fetchall()}
        if "price_intraday" in retention:
            logger.success("OK Retention policy: price_intraday")
        else:
            logger.warning("WARN No retention policy for price_intraday")
            ok = False

        # 4. Compression policies (check via jobs table, not compression_settings view)
        # timescaledb_information.compression_settings returns one row per column --
        # checking policy_compression jobs is more precise for policy verification.
        cur.execute("""
            SELECT hypertable_name
            FROM timescaledb_information.jobs
            WHERE proc_name = 'policy_compression'
            ORDER BY hypertable_name;
        """)
        compressed = {r[0] for r in cur.fetchall()}
        for tbl in ["price_intraday", "price_history"]:
            if tbl in compressed:
                logger.success(f"OK Compression policy: {tbl}")
            else:
                logger.warning(f"WARN No compression policy for {tbl}")
                ok = False

        # 5. Continuous aggregates
        cur.execute("""
            SELECT view_name, materialization_hypertable_name
            FROM timescaledb_information.continuous_aggregates
            ORDER BY view_name;
        """)
        caggs = {r[0] for r in cur.fetchall()}
        for cagg in ["cagg_ohlc_5m", "cagg_ohlc_1h", "cagg_ohlc_1d"]:
            if cagg in caggs:
                logger.success(f"OK Continuous aggregate: {cagg}")
            else:
                logger.error(f"FAIL Continuous aggregate '{cagg}' does not exist")
                ok = False

        cur.close()
    finally:
        conn.close()

    if ok:
        logger.success("All TimescaleDB checks PASSED")
    else:
        logger.error("Some checks FAILED -- see log above")

    return ok


if __name__ == "__main__":
    success = check_timescale()
    sys.exit(0 if success else 1)
