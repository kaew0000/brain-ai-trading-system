"""database/migrations/001_execution_lane_backfill.py

W14-2D-1 — Execution-Lane Data Model: explicit migration for EXISTING
database files created before this phase.

Why this exists
----------------
CREATE TABLE IF NOT EXISTS is a no-op against a table that already exists,
so database/db.py's normal idempotent schema-init path does NOT retrofit
the new `execution_lane NOT NULL CHECK(...)` column (or the new
`execution_events` table) onto an operator's existing, already-populated
database file. Fresh databases (new deployments, every test run using a
temp/`:memory:` path) get the target schema automatically the first time
`_apply_schema()` runs — this script is ONLY needed for a pre-existing
file.

What it does (approved decision, see docs/architecture.md's W14-2D-1
section)
--------------------------------------------------------------------------
For each of trades / signals / agent_decisions / feature_rows /
ml_predictions:
  1. If `execution_lane` already exists on the table: no-op for that table.
  2. Otherwise: rebuild the table using the EXACT target CREATE TABLE
     statement already present in database/schema_v13.sql (parsed from
     that file, not hand-duplicated here, so there is no drift risk
     between the migration and the live schema), copying every existing
     row across with execution_lane explicitly set to the literal string
     'LIVE' — NOT a SQL DEFAULT clause. Historical rows predate any
     dual-lane concept; the approved classification is that they are all
     real, LIVE data (see docs/architecture.md's W14-2D-1 section for the
     full rationale).

For `execution_events` (brand new, no historical data possible): a plain
CREATE TABLE IF NOT EXISTS is sufficient and safe to re-run.

`order_timeline_history` is migrated the same way but its target schema
lives in execution/order_timeline.py's _SCHEMA_SQL, not schema_v13.sql —
handled by a second, smaller helper below.

Safety
------
- Runs inside a single transaction per table; foreign_keys is turned OFF
  for the duration of each table's rebuild (SQLite's own recommended
  pattern for `ALTER TABLE`-by-rebuild) and restored after.
- Idempotent: safe to run against an already-migrated database (each
  table's presence check makes every step a no-op the second time).
- Never touches rows' actual field values (result, pnl, etc.) — only adds
  the new column and copies every other column through unchanged.

Usage
-----
    python -m database.migrations.migration_001_execution_lane_backfill <db_path>

Or, from other code:
    from database.migrations.migration_001_execution_lane_backfill import migrate
    report = migrate("/path/to/brain_bot.db")
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema_v13.sql")

_LANE_TABLES = ("trades", "signals", "agent_decisions", "feature_rows", "ml_predictions")

_BACKFILL_LANE = "LIVE"  # approved decision — see module docstring


def _read_schema_sql() -> str:
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _extract_create_table(sql_text: str, table: str) -> str:
    pattern = re.compile(rf"CREATE TABLE IF NOT EXISTS {table}\s*\(.*?\n\);", re.DOTALL)
    m = pattern.search(sql_text)
    if not m:
        raise RuntimeError(f"001_execution_lane_backfill: could not find CREATE TABLE for '{table}' in schema_v13.sql")
    return m.group(0)


def _extract_indexes(sql_text: str, table: str) -> list[str]:
    pattern = re.compile(rf"CREATE INDEX IF NOT EXISTS \S+\s+ON {table}\([^)]*\);")
    return pattern.findall(sql_text)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def _rebuild_table_with_lane(
    conn: sqlite3.Connection, table: str, create_sql: str, index_sqls: list[str]
) -> dict:
    """Rebuild `table` so it matches `create_sql` (which already includes
    the execution_lane column), backfilling every existing row's
    execution_lane to _BACKFILL_LANE. Returns a small report dict."""
    if not _table_exists(conn, table):
        # Nothing to migrate — a brand-new DB will get the target schema
        # directly from _apply_schema() on first use. Not an error.
        return {"table": table, "status": "no_existing_table", "backfilled_rows": 0}

    if _has_column(conn, table, "execution_lane"):
        return {"table": table, "status": "already_migrated", "backfilled_rows": 0}

    old_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    old_cols_csv = ", ".join(old_cols)
    tmp_name = f"{table}_pre_w14_2d_1"

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute(f"ALTER TABLE {table} RENAME TO {tmp_name}")
        conn.execute(create_sql)  # creates `table` fresh, target schema incl. execution_lane
        conn.execute(
            f"INSERT INTO {table} ({old_cols_csv}, execution_lane) "
            f"SELECT {old_cols_csv}, ? FROM {tmp_name}",
            (_BACKFILL_LANE,),
        )
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        conn.execute(f"DROP TABLE {tmp_name}")
        for idx_sql in index_sqls:
            conn.execute(idx_sql)
        # Defensive: keep AUTOINCREMENT high-water mark correct after the
        # explicit-id INSERT above (SQLite tracks this from rowid inserts
        # even without AUTOINCREMENT, but this makes the intent explicit).
        max_id_row = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()
        max_id = max_id_row[0] if max_id_row and max_id_row[0] is not None else 0
        conn.execute(
            "UPDATE sqlite_sequence SET seq=? WHERE name=? AND seq<?",
            (max_id, table, max_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")

    return {"table": table, "status": "migrated", "backfilled_rows": n}


def _ensure_execution_events(conn: sqlite3.Connection, sql_text: str) -> dict:
    already = _table_exists(conn, "execution_events")
    create_sql = _extract_create_table(sql_text, "execution_events")
    index_sqls = _extract_indexes(sql_text, "execution_events")
    conn.executescript(create_sql + "\n" + "\n".join(index_sqls))
    conn.commit()
    return {"table": "execution_events", "status": "already_existed" if already else "created"}


def _migrate_order_timeline_history(conn: sqlite3.Connection) -> dict:
    """order_timeline_history's schema lives in execution/order_timeline.py
    (_SCHEMA_SQL), not schema_v13.sql — separate table, separate source of
    truth, so it needs its own small rebuild step."""
    table = "order_timeline_history"
    if not _table_exists(conn, table):
        return {"table": table, "status": "no_existing_table", "backfilled_rows": 0}
    if _has_column(conn, table, "execution_lane"):
        return {"table": table, "status": "already_migrated", "backfilled_rows": 0}

    create_sql = (
        "CREATE TABLE order_timeline_history (\n"
        "    id           INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "    timestamp    TEXT    NOT NULL,\n"
        "    symbol       TEXT    NOT NULL,\n"
        "    trade_id     INTEGER,\n"
        "    order_id     TEXT,\n"
        "    state_before TEXT,\n"
        "    state_after  TEXT    NOT NULL,\n"
        "    source       TEXT    NOT NULL,\n"
        "    reason       TEXT,\n"
        "    execution_lane TEXT  NOT NULL CHECK(execution_lane IN ('LIVE','TRAINING','PAPER'))\n"
        ");"
    )
    index_sqls = [
        "CREATE INDEX IF NOT EXISTS idx_order_timeline_symbol ON order_timeline_history(symbol, id);",
        "CREATE INDEX IF NOT EXISTS idx_order_timeline_lane ON order_timeline_history(execution_lane);",
    ]
    return _rebuild_table_with_lane(conn, table, create_sql, index_sqls)


def migrate(db_path: str) -> dict:
    """Idempotent. Safe to run zero, one, or many times against the same
    file. Returns a report dict: {"tables": [...per-table results...]}."""
    sql_text = _read_schema_sql()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        results = []
        for table in _LANE_TABLES:
            create_sql = _extract_create_table(sql_text, table)
            index_sqls = _extract_indexes(sql_text, table)
            results.append(_rebuild_table_with_lane(conn, table, create_sql, index_sqls))
        results.append(_migrate_order_timeline_history(conn))
        results.append(_ensure_execution_events(conn, sql_text))
        return {"db_path": db_path, "tables": results}
    finally:
        conn.close()


def _main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m database.migrations.migration_001_execution_lane_backfill <db_path>")
        return 2
    report = migrate(sys.argv[1])
    for t in report["tables"]:
        print(f"  {t['table']:<24} {t['status']:<20} backfilled_rows={t.get('backfilled_rows', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
