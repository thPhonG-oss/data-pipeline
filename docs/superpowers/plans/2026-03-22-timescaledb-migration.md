# TimescaleDB Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `price_intraday` and `price_history` tables from plain PostgreSQL to TimescaleDB hypertables, with automatic retention, compression, and continuous aggregates for 5m/1H/1D OHLC rollups.

**Architecture:** Replace `postgres:16-alpine` Docker image with `timescale/timescaledb:latest-pg16`; add SQL migrations to enable the extension, convert both price tables to hypertables, and define continuous aggregates chained 1m→5m→1H→1D. Application code (`processor.py`, `PostgresLoader`) requires minimal changes — only the `id` surrogate key is removed since hypertables use the time column as the partition key.

**Tech Stack:** TimescaleDB 2.x (pg16), PostgreSQL 16, psycopg2, SQLAlchemy, pytest, Docker Compose.

---

## Pre-flight: Key facts about the codebase

- Migration files live in `db/migrations/`, named `NNN_*.sql`, run by `db/migrate.py` in alphabetical order.
- `db/migrate.py` runs with `autocommit=True` — each SQL file executes as its own transaction. This is correct for TimescaleDB DDL.
- **`docker-entrypoint-initdb.d` auto-run path:** `docker-compose.yml` mounts `./db/migrations` into `/docker-entrypoint-initdb.d`. On a **fresh Docker volume**, PostgreSQL auto-runs ALL SQL files at container init time (alphabetical order) — `python -m db.migrate` is NOT needed in that case. Migrations 009–011 will run automatically via this path as long as the container uses the TimescaleDB image. This is safe because all DDL is idempotent (`IF NOT EXISTS`, `if_not_exists => TRUE`).
- `PostgresLoader` uses `INSERT ... ON CONFLICT DO UPDATE` with `index_elements=conflict_columns`. TimescaleDB supports this **only when the conflict target includes the partition column** (`time` for `price_intraday`, `date` for `price_history`). Both tables already satisfy this.
- `CONFLICT_KEYS["price_intraday"] = ["symbol", "time", "resolution"]` — `time` is the partition column ✓
- `CONFLICT_KEYS["price_history"] = ["symbol", "date", "source"]` — `date` is the partition column ✓
- `SERVER_GENERATED_COLS = {"id", "duration_ms", "created_at"}` — `id` is excluded from INSERT/UPDATE by the loader via `_resolve_update_columns()`. After migration drops `id` from the table, the reflected schema simply has no `id` column — the loader continues to work without any changes.
- `_transform_message()` in `processor.py` returns a dict with keys `{symbol, time, resolution, open, high, low, close, volume, source, fetched_at}` — no `id`. Removing `id` from the table is completely transparent to all application code.
- **`price_history.date` column type is `DATE`** (not TIMESTAMPTZ). TimescaleDB `create_hypertable` on a `DATE` column requires `chunk_time_interval` as an **integer (number of days)**, not an `INTERVAL`. Use `90` for ~3 months.
- **`ADD PRIMARY KEY` idempotency:** Migrations must be safe to re-run (someone may run `python -m db.migrate` after adding a future migration). Wrap `ADD PRIMARY KEY` in a `DO $$ BEGIN ... EXCEPTION ... END $$` block.
- Tests live in `tests/`, run with `pytest` from project root.
- All tests must pass: `pytest tests/ -v`

---

## File Map

| Action | File |
|--------|------|
| Modify | `docker-compose.yml` — change postgres image |
| Create | `db/migrations/009_timescaledb_setup.sql` — enable extension, convert `price_intraday` to hypertable, retention, compression |
| Create | `db/migrations/010_timescaledb_price_history.sql` — convert `price_history` to hypertable |
| Create | `db/migrations/011_continuous_aggregates.sql` — cagg_ohlc_5m, cagg_ohlc_1h, cagg_ohlc_1d with refresh policies |
| Create | `db/check_timescale.py` — CLI health-check script |
| Create | `tests/db/test_timescale_migrations.py` — unit tests for migration SQL logic |
| Create | `tests/db/__init__.py` — package marker |

---

## Task 1: Update Docker image to TimescaleDB

**Files:**
- Modify: `docker-compose.yml:8`

- [ ] **Step 1: Read current docker-compose.yml**

  Confirm `postgres:16-alpine` on line 8 (the `image:` field under the `postgres:` service).

- [ ] **Step 2: Replace the image**

  Change:
  ```yaml
  image: postgres:16-alpine
  ```
  To:
  ```yaml
  image: timescale/timescaledb:latest-pg16
  ```

- [ ] **Step 3: Verify the file looks correct**

  The `postgres` service in `docker-compose.yml` should now read:
  ```yaml
  postgres:
    image: timescale/timescaledb:latest-pg16
    container_name: stockapp_db
    restart: unless-stopped
    ...
  ```

  **Important:** Do NOT change anything else. All other settings (volumes, env vars, healthcheck) stay identical.

- [ ] **Step 4: Commit**

  ```bash
  git add docker-compose.yml
  git commit -m "chore: switch postgres image to timescale/timescaledb:latest-pg16"
  ```

---

## Task 2: Migration 009 — Enable TimescaleDB + `price_intraday` hypertable

**Files:**
- Create: `db/migrations/009_timescaledb_setup.sql`

**What this migration does:**
1. Enables the TimescaleDB extension.
2. Drops the `id` surrogate key from `price_intraday` (it conflicts with hypertable's partitioning model).
3. Promotes the existing UNIQUE constraint `(symbol, time, resolution)` to PRIMARY KEY — idempotent via `DO $$ BEGIN ... EXCEPTION ... END $$`.
4. Converts the table to a hypertable partitioned by `time` with 1-week chunks.
5. Sets a 180-day retention policy (covers both 1m and 5m; compression makes 1m data beyond 30 days negligible — known spec compromise, see note below).
6. Enables columnar compression on chunks older than 7 days.

**Note on retention compromise:** The spec states 1m=30 days, 5m=180 days. TimescaleDB `add_retention_policy` operates at the table level and cannot filter by `resolution` column. Options: (a) use 180 days for both (chosen here — 1m data compresses to ~10% size, low cost), or (b) split into two tables (`price_intraday_1m`, `price_intraday_5m`). Option (a) is chosen to avoid breaking the existing schema; this is an accepted trade-off.

- [ ] **Step 1: Write the failing test**

  Create `tests/db/__init__.py` (empty) and `tests/db/test_timescale_migrations.py`:

  ```python
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
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  pytest tests/db/test_timescale_migrations.py -v
  ```

  Expected: 6 tests FAIL with `FileNotFoundError` (file doesn't exist yet).

- [ ] **Step 3: Create `db/migrations/009_timescaledb_setup.sql`**

  ```sql
  -- ============================================================
  -- Migration 009: Kích hoạt TimescaleDB + chuyển price_intraday
  -- thành hypertable với retention và compression.
  -- Tất cả DDL đều idempotent — an toàn khi chạy lại.
  -- ============================================================

  -- Bước 1: Kích hoạt extension TimescaleDB
  CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

  -- Bước 2: Bỏ cột id (surrogate key không cần thiết cho hypertable)
  -- PostgresLoader loại id qua SERVER_GENERATED_COLS; _transform_message không sinh id.
  ALTER TABLE price_intraday DROP COLUMN IF EXISTS id;

  -- Bước 3: Bỏ UNIQUE constraint cũ, promote lên PRIMARY KEY (idempotent)
  -- TimescaleDB yêu cầu PK phải bao gồm partition column (time ✓)
  ALTER TABLE price_intraday DROP CONSTRAINT IF EXISTS uq_price_intraday;
  DO $$
  BEGIN
      IF NOT EXISTS (
          SELECT 1 FROM pg_constraint
          WHERE conname = 'price_intraday_pkey' AND contype = 'p'
      ) THEN
          ALTER TABLE price_intraday ADD PRIMARY KEY (symbol, time, resolution);
      END IF;
  END $$;

  -- Bước 4: Convert sang hypertable, partition theo 'time', chunk = 1 tuần
  -- migrate_data => TRUE cho phép chuyển đổi khi bảng đã có dữ liệu
  SELECT create_hypertable(
      'price_intraday',
      'time',
      chunk_time_interval => INTERVAL '1 week',
      if_not_exists        => TRUE,
      migrate_data         => TRUE
  );

  -- Bước 5: Retention policy 180 ngày
  -- Ghi chú: TimescaleDB không hỗ trợ retention theo giá trị cột (resolution).
  -- Chọn 180 ngày (= yêu cầu 5m); 1m data sau 30 ngày được nén ~90% — chấp nhận được.
  SELECT add_retention_policy('price_intraday', INTERVAL '180 days', if_not_exists => TRUE);

  -- Bước 6: Bật columnar compression, segment theo symbol+resolution
  ALTER TABLE price_intraday SET (
      timescaledb.compress,
      timescaledb.compress_orderby   = 'time DESC',
      timescaledb.compress_segmentby = 'symbol, resolution'
  );

  -- Tự động nén chunks cũ hơn 7 ngày
  SELECT add_compression_policy('price_intraday', INTERVAL '7 days', if_not_exists => TRUE);
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "test_009" -v
  ```

  Expected: All 6 PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add db/migrations/009_timescaledb_setup.sql tests/db/__init__.py tests/db/test_timescale_migrations.py
  git commit -m "feat: migration 009 — enable timescaledb, convert price_intraday to hypertable"
  ```

---

## Task 3: Migration 010 — `price_history` hypertable

**Files:**
- Create: `db/migrations/010_timescaledb_price_history.sql`

**What this migration does:**
Converts `price_history` (EOD daily data) to a hypertable partitioned by `date` with ~3-month chunks. No retention policy (keep all historical data). Compression on chunks older than 90 days.

**Critical:** `price_history.date` is `DATE` type. TimescaleDB requires `chunk_time_interval` to be an **integer (number of days)** for `DATE` columns — `INTERVAL '3 months'` will fail. Use `90` (integer) instead.

- [ ] **Step 1: Write the failing tests**

  Add to `tests/db/test_timescale_migrations.py`:

  ```python
  def test_010_drops_id_column_price_history():
      sql = _read("010_timescaledb_price_history.sql")
      assert any(
          "DROP COLUMN" in line and "id" in line
          for line in sql.splitlines()
      ), "Expected 'DROP COLUMN ... id' on a single line"


  def test_010_creates_hypertable_price_history():
      sql = _read("010_timescaledb_price_history.sql")
      # Must reference price_history and 'date' together
      assert re.search(
          r"create_hypertable\s*\(\s*'price_history'\s*,\s*'date'", sql
      ), "Expected create_hypertable('price_history', 'date', ...)"


  def test_010_chunk_interval_is_integer_not_interval():
      sql = _read("010_timescaledb_price_history.sql")
      # DATE columns require integer days, not INTERVAL — this is a TimescaleDB constraint
      # chunk_time_interval must be set to an integer (e.g. 90), not INTERVAL '3 months'
      assert "chunk_time_interval => 90" in sql, (
          "price_history.date is a DATE column: chunk_time_interval must be integer (90), "
          "not INTERVAL — see TimescaleDB docs"
      )


  def test_010_primary_key_is_idempotent():
      sql = _read("010_timescaledb_price_history.sql")
      assert "DO $$" in sql or "DO $block$" in sql
      assert "ADD PRIMARY KEY" in sql


  def test_010_adds_compression_policy():
      sql = _read("010_timescaledb_price_history.sql")
      assert "timescaledb.compress" in sql
      assert "add_compression_policy" in sql
      assert "'price_history'" in sql
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "test_010" -v
  ```

  Expected: 5 tests FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create `db/migrations/010_timescaledb_price_history.sql`**

  ```sql
  -- ============================================================
  -- Migration 010: Chuyển price_history thành hypertable.
  -- Không có retention policy (giữ toàn bộ lịch sử).
  -- Compression sau 90 ngày (dữ liệu EOD ít thay đổi).
  -- Tất cả DDL đều idempotent — an toàn khi chạy lại.
  -- ============================================================

  -- Bước 1: Bỏ cột id
  ALTER TABLE price_history DROP COLUMN IF EXISTS id;

  -- Bước 2: Bỏ UNIQUE constraint cũ, promote lên PRIMARY KEY (idempotent)
  ALTER TABLE price_history DROP CONSTRAINT IF EXISTS uq_price_history;
  DO $$
  BEGIN
      IF NOT EXISTS (
          SELECT 1 FROM pg_constraint
          WHERE conname = 'price_history_pkey' AND contype = 'p'
      ) THEN
          ALTER TABLE price_history ADD PRIMARY KEY (symbol, date, source);
      END IF;
  END $$;

  -- Bước 3: Convert sang hypertable, partition theo 'date', chunk = 90 ngày
  -- QUAN TRỌNG: price_history.date là kiểu DATE (không phải TIMESTAMPTZ).
  -- TimescaleDB yêu cầu chunk_time_interval là INTEGER (số ngày) cho cột DATE.
  -- Dùng 90 (ngày) thay vì INTERVAL '3 months' — INTERVAL sẽ báo lỗi với DATE.
  SELECT create_hypertable(
      'price_history',
      'date',
      chunk_time_interval => 90,
      if_not_exists        => TRUE,
      migrate_data         => TRUE
  );

  -- Bước 4: Bật columnar compression, segment theo symbol + source
  ALTER TABLE price_history SET (
      timescaledb.compress,
      timescaledb.compress_orderby   = 'date DESC',
      timescaledb.compress_segmentby = 'symbol, source'
  );

  -- Tự động nén chunks cũ hơn 90 ngày
  SELECT add_compression_policy('price_history', INTERVAL '90 days', if_not_exists => TRUE);
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "test_010" -v
  ```

  Expected: All 5 PASS.

- [ ] **Step 5: Run all tests so far (no regressions)**

  ```bash
  pytest tests/ -v
  ```

  Expected: All tests PASS.

- [ ] **Step 6: Commit**

  ```bash
  git add db/migrations/010_timescaledb_price_history.sql tests/db/test_timescale_migrations.py
  git commit -m "feat: migration 010 — convert price_history to hypertable with compression"
  ```

---

## Task 4: Migration 011 — Continuous Aggregates (5m / 1H / 1D)

**Files:**
- Create: `db/migrations/011_continuous_aggregates.sql`

**What this migration does:**
Creates a chain of continuous aggregates from raw 1m intraday data:
- `cagg_ohlc_5m` — 5-minute candles rolled up from 1m data (`resolution = 1`)
- `cagg_ohlc_1h` — hourly candles from 5m aggregate
- `cagg_ohlc_1d` — daily candles from 1h aggregate

Each aggregate has a refresh policy to stay up-to-date automatically.

**TimescaleDB functions used:**
- `time_bucket(interval, time)` — groups timestamps into fixed-size buckets
- `first(value, time)` — value at the earliest time in the bucket (= open price)
- `last(value, time)` — value at the latest time in the bucket (= close price)
- `add_continuous_aggregate_policy(...)` — auto-refresh on schedule

**Note on hierarchical CAggs:** TimescaleDB 2.9+ supports creating continuous aggregates on top of other continuous aggregates. The `timescale/timescaledb:latest-pg16` image ships 2.x and supports this.

**Critical — `materialized_only` for hierarchical sources:** A CAgg that is used as the **source** for another CAgg must set `materialized_only = TRUE`. If it stays `FALSE`, the child CAgg cannot compose with the parent's real-time (non-materialized) region and will fail or produce incorrect results. Only the leaf CAgg (`cagg_ohlc_1d`) keeps `FALSE` to allow real-time reads for the current trading day.

- [ ] **Step 1: Write the failing tests**

  Add to `tests/db/test_timescale_migrations.py`:

  ```python
  def test_011_creates_cagg_5m_from_price_intraday():
      sql = _read("011_continuous_aggregates.sql")
      # cagg_ohlc_5m must query price_intraday (not another cagg) with resolution=1 filter
      assert "cagg_ohlc_5m" in sql
      assert "timescaledb.continuous" in sql
      assert re.search(r"FROM\s+price_intraday", sql), "cagg_ohlc_5m must query FROM price_intraday"
      assert re.search(r"resolution\s*=\s*1", sql), "Must filter WHERE resolution = 1 (1m candles only)"


  def test_011_creates_cagg_1h_from_cagg_5m():
      sql = _read("011_continuous_aggregates.sql")
      # cagg_ohlc_1h must query cagg_ohlc_5m (hierarchical CAgg chain)
      assert "cagg_ohlc_1h" in sql
      assert re.search(r"FROM\s+cagg_ohlc_5m", sql), "cagg_ohlc_1h must query FROM cagg_ohlc_5m"


  def test_011_creates_cagg_1d_from_cagg_1h():
      sql = _read("011_continuous_aggregates.sql")
      assert "cagg_ohlc_1d" in sql
      assert re.search(r"FROM\s+cagg_ohlc_1h", sql), "cagg_ohlc_1d must query FROM cagg_ohlc_1h"


  def test_011_adds_refresh_policies_for_all_three():
      sql = _read("011_continuous_aggregates.sql")
      # Each of the 3 aggregates must have its own refresh policy
      count = sql.count("add_continuous_aggregate_policy")
      assert count >= 3, f"Expected >= 3 refresh policies, found {count}"


  def test_011_uses_first_last_with_two_args():
      sql = _read("011_continuous_aggregates.sql")
      # first(value, time) and last(value, time) — TimescaleDB syntax requires 2 arguments
      assert re.search(r"first\(\w+\s*,\s*\w+\)", sql), "first() must have 2 args: first(value, time)"
      assert re.search(r"last\(\w+\s*,\s*\w+\)", sql), "last() must have 2 args: last(value, time)"


  def test_011_source_caggs_use_materialized_only_true():
      sql = _read("011_continuous_aggregates.sql")
      # cagg_ohlc_5m and cagg_ohlc_1h must set materialized_only=TRUE because
      # they are used as sources for hierarchical CAggs — required by TimescaleDB 2.x
      # Only the leaf cagg_ohlc_1d can use FALSE (for real-time reads)
      assert sql.count("materialized_only = TRUE") >= 2, (
          "cagg_ohlc_5m and cagg_ohlc_1h must set materialized_only = TRUE "
          "(required for hierarchical CAgg sources in TimescaleDB 2.x)"
      )
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "test_011" -v
  ```

  Expected: All 5 FAIL with `FileNotFoundError`.

- [ ] **Step 3: Create `db/migrations/011_continuous_aggregates.sql`**

  ```sql
  -- ============================================================
  -- Migration 011: Continuous Aggregates cho dữ liệu intraday
  -- Chuỗi: 1m (raw) → 5m → 1H → 1D
  -- Dùng TimescaleDB hierarchical CAggs (yêu cầu v2.9+)
  -- ============================================================

  -- ── Aggregate 1: cagg_ohlc_5m (từ price_intraday 1m) ────────────────────────
  -- materialized_only = TRUE: bắt buộc vì cagg_ohlc_1h sẽ query view này
  CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_ohlc_5m
  WITH (timescaledb.continuous, timescaledb.materialized_only = TRUE) AS
  SELECT
      symbol,
      time_bucket('5 minutes'::interval, time)  AS bucket,
      5                                          AS resolution,
      first(open,  time)                         AS open,
      max(high)                                  AS high,
      min(low)                                   AS low,
      last(close,  time)                         AS close,
      sum(volume)                                AS volume
  FROM price_intraday
  WHERE resolution = 1
  GROUP BY symbol, time_bucket('5 minutes'::interval, time);

  -- Refresh tự động: cập nhật dữ liệu từ 10 phút trước đến hiện tại, mỗi 1 phút
  SELECT add_continuous_aggregate_policy(
      'cagg_ohlc_5m',
      start_offset  => INTERVAL '10 minutes',
      end_offset    => INTERVAL '1 minute',
      schedule_interval => INTERVAL '1 minute',
      if_not_exists => TRUE
  );

  -- ── Aggregate 2: cagg_ohlc_1h (từ cagg_ohlc_5m) ────────────────────────────
  -- materialized_only = TRUE: bắt buộc vì cagg_ohlc_1d sẽ query view này
  CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_ohlc_1h
  WITH (timescaledb.continuous, timescaledb.materialized_only = TRUE) AS
  SELECT
      symbol,
      time_bucket('1 hour'::interval, bucket)   AS bucket,
      60                                         AS resolution,
      first(open,  bucket)                       AS open,
      max(high)                                  AS high,
      min(low)                                   AS low,
      last(close,  bucket)                       AS close,
      sum(volume)                                AS volume
  FROM cagg_ohlc_5m
  GROUP BY symbol, time_bucket('1 hour'::interval, bucket);

  -- Refresh mỗi 5 phút, nhìn lại 2 giờ
  SELECT add_continuous_aggregate_policy(
      'cagg_ohlc_1h',
      start_offset  => INTERVAL '2 hours',
      end_offset    => INTERVAL '5 minutes',
      schedule_interval => INTERVAL '5 minutes',
      if_not_exists => TRUE
  );

  -- ── Aggregate 3: cagg_ohlc_1d (từ cagg_ohlc_1h) ────────────────────────────
  -- materialized_only = FALSE: CAgg lá, cho phép real-time reads phiên hôm nay
  CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_ohlc_1d
  WITH (timescaledb.continuous, timescaledb.materialized_only = FALSE) AS
  SELECT
      symbol,
      time_bucket('1 day'::interval, bucket)    AS bucket,
      1440                                       AS resolution,
      first(open,  bucket)                       AS open,
      max(high)                                  AS high,
      min(low)                                   AS low,
      last(close,  bucket)                       AS close,
      sum(volume)                                AS volume
  FROM cagg_ohlc_1h
  GROUP BY symbol, time_bucket('1 day'::interval, bucket);

  -- Refresh mỗi 15 phút, nhìn lại 2 ngày
  SELECT add_continuous_aggregate_policy(
      'cagg_ohlc_1d',
      start_offset  => INTERVAL '2 days',
      end_offset    => INTERVAL '15 minutes',
      schedule_interval => INTERVAL '15 minutes',
      if_not_exists => TRUE
  );
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "test_011" -v
  ```

  Expected: All 5 PASS.

- [ ] **Step 5: Run full test suite (no regressions)**

  ```bash
  pytest tests/ -v
  ```

  Expected: All tests PASS.

- [ ] **Step 6: Commit**

  ```bash
  git add db/migrations/011_continuous_aggregates.sql tests/db/test_timescale_migrations.py
  git commit -m "feat: migration 011 — continuous aggregates cagg_ohlc 5m/1h/1d"
  ```

---

## Task 5: Health-check script `db/check_timescale.py`

**Files:**
- Create: `db/check_timescale.py`

**What this does:**
A standalone CLI script that connects to the DB and verifies:
1. TimescaleDB extension is installed and active
2. `price_intraday` and `price_history` are registered hypertables
3. Retention and compression policies are set
4. Continuous aggregates exist

Run after applying migrations to confirm everything is wired up correctly.

- [ ] **Step 1: Write the failing test**

  Add to `tests/db/test_timescale_migrations.py`:

  ```python
  def test_check_timescale_script_exists():
      script = Path(__file__).parent.parent.parent / "db" / "check_timescale.py"
      assert script.exists(), "db/check_timescale.py not found"


  def test_check_timescale_imports_are_correct():
      script = (Path(__file__).parent.parent.parent / "db" / "check_timescale.py").read_text()
      assert "timescaledb_information" in script   # queries TimescaleDB catalog
      assert "hypertables" in script
      assert "policy_retention" in script       # retention policy jobs
      assert "policy_compression" in script     # compression policy jobs
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "check_timescale" -v
  ```

  Expected: Both FAIL.

- [ ] **Step 3: Create `db/check_timescale.py`**

  ```python
  """
  Kiểm tra trạng thái TimescaleDB sau khi chạy migrations.

  Cách dùng:
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
      Kết nối DB và kiểm tra toàn bộ cấu hình TimescaleDB.
      Trả về True nếu tất cả đều OK.
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
          logger.error(f"Không thể kết nối PostgreSQL: {e}")
          return False

      ok = True
      cur = conn.cursor()

      # 1. Extension
      cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb';")
      row = cur.fetchone()
      if row:
          logger.success(f"✓ TimescaleDB extension: v{row[0]}")
      else:
          logger.error("✗ TimescaleDB extension chưa được cài đặt")
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
              logger.success(f"✓ Hypertable '{tbl}': {hypertables[tbl]} chunks")
          else:
              logger.error(f"✗ '{tbl}' chưa phải hypertable")
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
          logger.success("✓ Retention policy: price_intraday")
      else:
          logger.warning("⚠ Retention policy chưa có cho price_intraday")

      # 4. Compression policies (check via jobs table, not compression_settings view)
      # timescaledb_information.compression_settings returns one row per column —
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
              logger.success(f"✓ Compression policy: {tbl}")
          else:
              logger.warning(f"⚠ Compression policy chưa có cho {tbl}")

      # 5. Continuous aggregates
      cur.execute("""
          SELECT view_name, materialization_hypertable_name
          FROM timescaledb_information.continuous_aggregates
          ORDER BY view_name;
      """)
      caggs = {r[0] for r in cur.fetchall()}
      for cagg in ["cagg_ohlc_5m", "cagg_ohlc_1h", "cagg_ohlc_1d"]:
          if cagg in caggs:
              logger.success(f"✓ Continuous aggregate: {cagg}")
          else:
              logger.error(f"✗ Continuous aggregate '{cagg}' chưa tồn tại")
              ok = False

      cur.close()
      conn.close()

      if ok:
          logger.success("\n✅ Tất cả TimescaleDB checks PASSED")
      else:
          logger.error("\n❌ Một số checks FAILED — xem log ở trên")

      return ok


  if __name__ == "__main__":
      success = check_timescale()
      sys.exit(0 if success else 1)
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```bash
  pytest tests/db/test_timescale_migrations.py -k "check_timescale" -v
  ```

  Expected: Both PASS.

- [ ] **Step 5: Run full test suite**

  ```bash
  pytest tests/ -v
  ```

  Expected: All tests PASS.

- [ ] **Step 6: Commit**

  ```bash
  git add db/check_timescale.py tests/db/test_timescale_migrations.py
  git commit -m "feat: add db/check_timescale.py health-check script for TimescaleDB"
  ```

---

## Task 6: End-to-end verification (apply migrations to live DB)

**Files:** None (verification only)

This task verifies the migrations actually work on a running TimescaleDB instance.

- [ ] **Step 1: Pull new Docker image**

  ```bash
  cd C:\Users\PHONG\Desktop\data-pipeline
  docker compose pull postgres
  ```

  Expected output: `Pulling postgres ... done` (downloads `timescale/timescaledb:latest-pg16`).

- [ ] **Step 2: Recreate the postgres container**

  **⚠ WARNING:** If `postgres_data` volume already has data from `postgres:16-alpine`, it's incompatible with the new image. Options:
  - **Fresh start (no existing data worth keeping):** `docker compose down -v && docker compose up -d postgres`
  - **Existing data to preserve:** Export first with `pg_dump`, then `docker compose down -v`, then `docker compose up -d postgres`, then restore.

  For a fresh start:
  ```bash
  docker compose down -v
  docker compose up -d postgres
  docker compose exec postgres pg_isready -U postgres
  ```

  Expected: `localhost:5432 - accepting connections`

- [ ] **Step 3: Run all migrations**

  ```bash
  python -m db.migrate
  ```

  Expected: Each migration file logged as `✓`, ending with `Tất cả migrations đã chạy thành công.`

  Key lines to look for:
  ```
  ▶ Chạy migration: 009_timescaledb_setup.sql
    ✓ 009_timescaledb_setup.sql
  ▶ Chạy migration: 010_timescaledb_price_history.sql
    ✓ 010_timescaledb_price_history.sql
  ▶ Chạy migration: 011_continuous_aggregates.sql
    ✓ 011_continuous_aggregates.sql
  ```

- [ ] **Step 4: Run health-check script**

  ```bash
  python -m db.check_timescale
  ```

  Expected output:
  ```
  ✓ TimescaleDB extension: v2.x.x
  ✓ Hypertable 'price_history': 0 chunks
  ✓ Hypertable 'price_intraday': 0 chunks
  ✓ Retention policy: price_intraday
  ✓ Compression policy: price_intraday
  ✓ Compression policy: price_history
  ✓ Continuous aggregate: cagg_ohlc_1d
  ✓ Continuous aggregate: cagg_ohlc_1h
  ✓ Continuous aggregate: cagg_ohlc_5m
  ✅ Tất cả TimescaleDB checks PASSED
  ```

- [ ] **Step 5: Run full test suite one final time**

  ```bash
  pytest tests/ -v
  ```

  Expected: All tests PASS.

- [ ] **Step 6: Final commit**

  ```bash
  git add .
  git commit -m "chore: verify timescaledb migration end-to-end — all checks pass"
  ```

---

## Appendix: How to query continuous aggregates

After migrations are applied and real-time data starts flowing, query the aggregates like normal views:

```sql
-- Nến 5m của HPG trong 1 giờ gần nhất
SELECT bucket, open, high, low, close, volume
FROM cagg_ohlc_5m
WHERE symbol = 'HPG'
  AND bucket >= NOW() - INTERVAL '1 hour'
ORDER BY bucket DESC;

-- Nến 1H của VCB hôm nay
SELECT bucket, open, high, low, close, volume
FROM cagg_ohlc_1h
WHERE symbol = 'VCB'
  AND bucket >= CURRENT_DATE
ORDER BY bucket;

-- Nến 1D của toàn bộ VN30 (so sánh với price_history)
SELECT symbol, bucket AS date, open, high, low, close, volume
FROM cagg_ohlc_1d
WHERE bucket >= '2026-01-01'
ORDER BY symbol, bucket;
```
