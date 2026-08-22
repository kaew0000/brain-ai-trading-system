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

# fix/journal-signals-fk-migration-repair: reordered so `signals` rebuilds
# BEFORE `trades`/`agent_decisions` (previously: trades, signals, ...).
#
# Why this ordering was the bug: SQLite's ALTER TABLE ... RENAME TO
# automatically rewrites the stored CREATE TABLE text of every OTHER
# table's foreign-key clauses that reference the renamed table. The old
# ordering rebuilt `trades` (fresh FK: REFERENCES signals(id)) BEFORE
# `signals` was renamed — so when `signals` was later renamed to
# `signals_pre_w14_2d_1` as part of ITS OWN rebuild, SQLite silently
# rewrote the already-freshly-rebuilt `trades` table's FK clause to
# REFERENCES "signals_pre_w14_2d_1"(id), a temp table that gets DROPped
# moments later — leaving `trades` permanently referencing a table that
# no longer exists. Empirically reproduced and confirmed against real
# SQLite before this fix (see tests/test_migration_001_fk_repair.py).
#
# Rebuilding `signals` FIRST means every later table's fresh FK clause
# (parsed straight from schema_v13.sql's current text) is written when
# `signals` already has its FINAL name — nothing renames it again after
# that point, so nothing triggers the auto-rewrite. Verified empirically
# this ordering alone is sufficient to prevent the `trades` case for any
# FRESH application of this migration to an old database from here on.
#
# This reordering is NOT a complete fix on its own, though, which is why
# _repair_dangling_fks() below still runs unconditionally at the end of
# migrate(): `ai_explanations` also has `signal_id REFERENCES
# signals(id)` (schema_v13.sql) but was never in this tuple at all, so
# no amount of reordering _LANE_TABLES touches it — if it already
# existed as a table at the moment `signals` was renamed on some
# database, the same auto-rewrite mechanism corrupted it identically,
# and reordering this tuple can't undo damage a migration already did on
# a database that already ran the old buggy version once. The repair
# pass detects and fixes both cases generically (any table, in or out of
# this tuple) rather than relying on ordering to prevent recurrence.
_LANE_TABLES = ("signals", "trades", "agent_decisions", "feature_rows", "ml_predictions")

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


def _rebuild_table(
    conn: sqlite3.Connection,
    table: str,
    create_sql: str,
    index_sqls: list[str],
    extra_column: str | None = None,
    extra_value: str | None = None,
) -> int:
    """Low-level ALTER-RENAME / recreate-from-`create_sql` / copy-data /
    drop-temp / recreate-indexes rebuild — the mechanics shared by both
    the execution_lane backfill (_rebuild_table_with_lane, which passes
    extra_column="execution_lane") and the dangling-FK repair pass
    (_repair_dangling_fks below, which passes neither: no column is
    being added, only the stored FK clause changes, as an automatic side
    effect of rebuilding fresh from create_sql while the table it
    references already has its final name).

    Extracted as its own function (fix/journal-signals-fk-migration-repair)
    so the two callers share one rebuild implementation instead of two
    near-identical copies. Returns the row count copied. Caller owns the
    `PRAGMA foreign_keys=OFF`/`=ON` and transaction/rollback around this
    — kept out of here so both callers can share one try/except/finally
    shape without this function needing to know which report dict shape
    its caller wants.
    """
    old_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    old_cols_csv = ", ".join(old_cols)
    tmp_name = f"{table}_pre_w14_2d_1"

    conn.execute(f"ALTER TABLE {table} RENAME TO {tmp_name}")
    conn.execute(create_sql)  # creates `table` fresh from current-correct SQL
    if extra_column is not None:
        conn.execute(
            f"INSERT INTO {table} ({old_cols_csv}, {extra_column}) "
            f"SELECT {old_cols_csv}, ? FROM {tmp_name}",
            (extra_value,),
        )
    else:
        conn.execute(
            f"INSERT INTO {table} ({old_cols_csv}) SELECT {old_cols_csv} FROM {tmp_name}"
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
    return n


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

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        n = _rebuild_table(
            conn, table, create_sql, index_sqls,
            extra_column="execution_lane", extra_value=_BACKFILL_LANE,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON")

    return {"table": table, "status": "migrated", "backfilled_rows": n}


_DANGLING_FK_SUFFIX = "_pre_w14_2d_1"  # this migration's own temp-rename suffix


def _find_dangling_fk_tables(conn: sqlite3.Connection) -> list[str]:
    """Generic detection for fix/journal-signals-fk-migration-repair:
    for every real user table, walk its foreign keys (PRAGMA
    foreign_key_list) and flag any whose referenced table name ends
    with this migration's own temp-rename suffix (`_pre_w14_2d_1`).
    Returns the names of tables with at least one such dangling
    reference.

    Deliberately NOT "any FK pointing at a table that doesn't
    currently exist" — that broader check was tried first and produces
    false positives: `trades.explanation_id REFERENCES
    ai_explanations(id)` looks identical to a genuine dangling
    reference whenever `ai_explanations` simply hasn't been created
    yet on a given database (e.g. CREATE TABLE IF NOT EXISTS for it
    hasn't run there yet — a normal, benign state, not a bug), which
    would make this pass "repair" trades on every single migrate()
    call rather than being a real no-op. A `_pre_w14_2d_1`-suffixed
    table is never a legitimate permanent reference target by this
    project's own convention — matching that suffix is the actual
    fingerprint of this specific bug's rename-triggered corruption,
    not a proxy for "table missing for any reason." Still doesn't
    hardcode specific table names like `trades` or `ai_explanations`
    — works for any table this migration's rebuild cycle corrupts,
    matching the project's stated goal of self-healing generically.
    """
    tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    ]
    dangling: list[str] = []
    for t in tables:
        for fk in conn.execute(f"PRAGMA foreign_key_list({t})").fetchall():
            ref_table = fk[2]  # 'table' column of PRAGMA foreign_key_list's output
            if ref_table and ref_table.endswith(_DANGLING_FK_SUFFIX):
                dangling.append(t)
                break
    return dangling


def _repair_dangling_fks(conn: sqlite3.Connection, sql_text: str) -> list[dict]:
    """Repair pass, run unconditionally at the end of migrate() (see call
    site below): rebuild any table _find_dangling_fk_tables() flags,
    recreating it from schema_v13.sql's CURRENT CREATE TABLE text (which
    already has a correct, un-corrupted FK clause) rather than from
    whatever stale text is presently stored for it. No column is added
    or removed — every existing column is copied straight through
    (_rebuild_table with no extra_column) — only the stored FK target
    changes, as a side effect of the table being freshly created while
    the table it references already has its final name.

    Iterates to a fixed point rather than a single pass: repairing one
    table can itself trigger the SAME SQLite auto-rewrite side effect on
    any OTHER table that references the one just repaired. Concretely:
    `trades.explanation_id REFERENCES ai_explanations(id)` — if
    `ai_explanations` is dangling and gets repaired (renamed, recreated,
    data copied, temp dropped), that rename corrupts `trades`'s
    already-correct `explanation_id` clause the exact same way `signals`
    being renamed originally corrupted `trades.signal_id`. Confirmed by
    running this function against a live reproduction before adding the
    loop — a single pass left `trades` freshly dangling immediately
    after fixing `ai_explanations`. Bounded to a small fixed number of
    passes (there is no reference cycle in schema_v13.sql — verified by
    inspection — so this always terminates in at most a couple of
    passes; the bound exists only as a defensive cap against an
    unanticipated future cycle, not because this is expected to need
    many iterations).

    A no-op (empty list) when nothing is dangling — safe to call on
    every migrate() run, matching this file's existing idempotency
    convention. Runs each repaired table in its own foreign_keys=OFF /
    transaction / rollback-on-exception block, mirroring
    _rebuild_table_with_lane's own pattern above (reused, not
    reinvented).
    """
    results: list[dict] = []
    max_passes = 10
    for _ in range(max_passes):
        targets = _find_dangling_fk_tables(conn)
        if not targets:
            break
        for table in targets:
            create_sql = _extract_create_table(sql_text, table)
            index_sqls = _extract_indexes(sql_text, table)
            conn.execute("PRAGMA foreign_keys=OFF")
            try:
                n = _rebuild_table(conn, table, create_sql, index_sqls)
                conn.commit()
                results.append({"table": table, "status": "fk_repaired", "rows": n})
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.execute("PRAGMA foreign_keys=ON")
    else:
        # Exhausted max_passes without reaching a fixed point — surface
        # this loudly rather than silently returning a partial repair.
        remaining = _find_dangling_fk_tables(conn)
        if remaining:
            raise RuntimeError(
                f"_repair_dangling_fks: still dangling after {max_passes} passes: "
                f"{remaining} — likely an unanticipated FK reference cycle; "
                f"investigate schema_v13.sql rather than raising max_passes."
            )
    return results


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
        # fix/journal-signals-fk-migration-repair: unconditional, generic
        # verification-and-repair pass — see _repair_dangling_fks'
        # docstring. Runs last so it repairs any table this migrate()
        # call itself might have left dangling (e.g. a first-ever run
        # against an old pre-W14-2D-1 database with an unlucky ordering
        # elsewhere), as well as any pre-existing corruption from a
        # previous run of the (now-fixed) buggy ordering.
        fk_repairs = _repair_dangling_fks(conn, sql_text)
        return {"db_path": db_path, "tables": results, "fk_repairs": fk_repairs}
    finally:
        conn.close()


def _main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m database.migrations.migration_001_execution_lane_backfill <db_path>")
        return 2
    report = migrate(sys.argv[1])
    for t in report["tables"]:
        print(f"  {t['table']:<24} {t['status']:<20} backfilled_rows={t.get('backfilled_rows', 0)}")
    fk_repairs = report.get("fk_repairs", [])
    if fk_repairs:
        print("  -- dangling FK repairs --")
        for r in fk_repairs:
            print(f"  {r['table']:<24} {r['status']:<20} rows={r.get('rows', 0)}")
    else:
        print("  -- dangling FK check: none found --")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
