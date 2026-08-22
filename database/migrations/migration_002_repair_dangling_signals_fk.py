"""database/migrations/002_repair_dangling_signals_fk.py

fix/journal-signals-fk-migration-repair — one-time, explicitly-invoked
repair for a database that already suffered the dangling-FK corruption
from an earlier run of the OLD buggy migration_001 (before this phase
reordered `_LANE_TABLES` and added the automatic repair pass — see
migration_001_execution_lane_backfill.py's module docstring and
docs/architecture.md for the full root-cause writeup).

Why this script exists separately from migration_001
------------------------------------------------------
migration_001's `migrate()` now runs the same repair pass
automatically, every time, as its own last step (docs/architecture.md
§43 or thereabouts) — and migration_001 is already registered in
database/migrations/runner.py's automatic every-boot sequence. So for
most purposes, simply importing this phase's bundle and restarting the
bot is enough; nothing further needs to be run by hand.

This script exists for the case that matters here specifically because
this targets **live trade history**: an operator who wants to inspect
or repair the database BEFORE trusting the automatic boot-time path —
e.g. to see exactly what's dangling on the real file, on demand,
without booting the whole system, or to repair a scratch COPY first
and verify it independently (see the Safety section of this phase's
originating brief). It is intentionally NOT registered in runner.py's
_MIGRATIONS list — that automatic path has no way to honor a
dry-run/--apply gate, and this script's whole purpose is to put a
human-confirmed gate in front of a repair that touches live financial
data, rather than assume the always-on automatic path is enough by
itself.

Reuses migration_001's `_read_schema_sql`, `_find_dangling_fk_tables`,
and `_repair_dangling_fks` directly — no logic is reimplemented here.

Idempotent
----------
Safe to run zero, one, or many times: `_repair_dangling_fks` is itself
a detect-before-fix, no-op-when-clean pass (see its docstring in
migration_001_execution_lane_backfill.py).

Usage
-----
    # Default: report only, writes nothing.
    python -m database.migrations.migration_002_repair_dangling_signals_fk <db_path>

    # Actually apply the repair.
    python -m database.migrations.migration_002_repair_dangling_signals_fk <db_path> --apply

Strongly recommended: run --dry-run (the default) against the real
file first, then run --apply against a **scratch copy** and verify
independently, before ever running --apply against the real live file.
See this phase's MIGRATION.md for the full recommended sequence.
"""
from __future__ import annotations

import argparse
import sqlite3

from database.migrations.migration_001_execution_lane_backfill import (
    _find_dangling_fk_tables,
    _read_schema_sql,
    _repair_dangling_fks,
)


def repair(db_path: str, apply: bool = False) -> dict:
    """Detect (and, if apply=True, fix) dangling signal_id-style FKs on
    db_path. Returns a report dict:
        {"db_path": ..., "mode": "dry_run" | "apply",
         "dangling_before": [...table names...],
         "repairs": [...per-table results, empty if dry_run...]}

    dry_run (apply=False, the default): opens the connection, detects,
    reports, writes NOTHING — not even a transaction is started.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        dangling_before = _find_dangling_fk_tables(conn)
        if not apply:
            return {
                "db_path": db_path,
                "mode": "dry_run",
                "dangling_before": dangling_before,
                "repairs": [],
            }
        sql_text = _read_schema_sql()
        repairs = _repair_dangling_fks(conn, sql_text)
        return {
            "db_path": db_path,
            "mode": "apply",
            "dangling_before": dangling_before,
            "repairs": repairs,
        }
    finally:
        conn.close()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Detect and (optionally) repair dangling signal_id-style "
            "foreign keys left by the pre-fix migration_001 ordering bug."
        )
    )
    parser.add_argument("db_path", help="Path to the SQLite database file.")
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help=(
            "Actually write the repair. Without this flag, only reports "
            "what would be repaired — writes nothing. Default: dry-run."
        ),
    )
    args = parser.parse_args()

    report = repair(args.db_path, apply=args.apply)

    print(f"== migration_002_repair_dangling_signals_fk ({report['mode']}) ==")
    print(f"  db_path: {report['db_path']}")
    if not report["dangling_before"]:
        print("  No dangling foreign keys found. Nothing to do.")
        return 0

    print(f"  Dangling FK found on: {report['dangling_before']}")
    if report["mode"] == "dry_run":
        print(
            "  DRY RUN — nothing written. Re-run with --apply to repair "
            "(recommended: first against a scratch COPY of this file, "
            "verified independently, before ever running --apply against "
            "the real live database)."
        )
    else:
        print("  Repaired:")
        for r in report["repairs"]:
            print(f"    {r['table']:<24} {r['status']:<20} rows={r.get('rows', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
