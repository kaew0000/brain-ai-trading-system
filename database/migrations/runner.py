"""database/migrations/runner.py — V16 Phase 4C: Automatic Migration Runner

Root cause
----------
database/db.py::_apply_schema() only ever executes `CREATE TABLE IF NOT
EXISTS ...` against a database file, which is a no-op for tables that
already exist. So a schema change to an already-populated table (e.g.
W14-2D-1's `execution_lane TEXT NOT NULL CHECK(...)` column, added to
`trades` / `signals` / `agent_decisions` / `feature_rows` /
`ml_predictions` / `order_timeline_history`) never reaches an
operator's existing database file — only brand-new files get it, via
_apply_schema() reading the current schema_v13.sql.

database/migrations/migration_001_execution_lane_backfill.py already
solves this correctly (idempotent, rebuilds each affected table from
schema_v13.sql's own CREATE TABLE statement, backfills historical rows
to 'LIVE'). The gap was invocation: nothing in this codebase ever
called it. `database/migrations/__init__.py`'s own docstring says as
much — "an operator (or a bundled startup check) runs them explicitly"
— and no such startup check existed. An operator who pulled new code
and restarted got a database silently out of sync with what the new
code expects; the first write to an unmigrated table raised
sqlite3.OperationalError: no such column: execution_lane (see
monitor_open_trades() / daily_report() in main.py).

Fix
---
This module is the single, ordered registry of every migration under
database/migrations/. run_pending_migrations() runs each one, in
order, against the resolved database path (database.db.get_db_path()
by default) every time the system boots — see main.py::build_system()'s
call site, step [0/9]. Every migration in this registry is required to
be idempotent (already true for migration_001), which is what makes
"run on every boot" safe rather than wasted work: an already-migrated
database sees every step return a *_already_* status and nothing
changes.

Adding a future migration: implement it the same way migration_001
is built (a `migrate(db_path) -> dict` function, idempotent, raises on
real failure), import it below, and append `(id_string, migrate)` to
_MIGRATIONS. Nothing else changes.

Failure handling
-----------------
A migration failure is raised, not swallowed — see build_system()'s
call site. Live trading must not start against a database whose schema
state is unknown; failing loudly at boot, before Layer 1 initializes,
is safer than letting the first write fail deep inside the trading
loop.

CLI
---
    python -m database.migrations.runner [db_path]

Runs every registered migration against db_path (or
database.db.get_db_path() if omitted) and prints a per-table summary.
Safe to run by hand at any time, against a stopped OR running system's
database file — this is exactly what main.py now does automatically on
every boot; manual invocation is a "do it right now, without booting
the whole system" convenience (e.g. to fix an existing production file
before redeploying new code).
"""
from __future__ import annotations

import sys
from typing import Callable

from database.db import get_db_path
from database.migrations.migration_001_execution_lane_backfill import (
    migrate as _migrate_001,
)
from utils.logger import get_logger

logger = get_logger("database.migrations.runner")

# Ordered registry — append future migrations here, oldest first.
# Each entry is (short_id, migrate_callable). migrate_callable must be
# `(db_path: str) -> dict`, idempotent, and must raise on real failure
# (never swallow an error into a "status" field).
_MIGRATIONS: list[tuple[str, Callable[[str], dict]]] = [
    ("001_execution_lane_backfill", _migrate_001),
]


def run_pending_migrations(db_path: str | None = None) -> list[dict]:
    """Run every registered migration, in order, against db_path.

    Defaults to database.db.get_db_path() — the same file
    TradeJournalV2 / database.db.ManagedConn write to — so calling this
    with no arguments migrates the database the rest of the system is
    about to use.

    Idempotent as a whole: safe to call on every process boot. Raises
    on the first migration that fails; never continues past a
    migration whose outcome is unknown.
    """
    path = db_path or get_db_path()
    reports: list[dict] = []
    for name, fn in _MIGRATIONS:
        logger.info(f"[migrations] running {name} against {path} …")
        try:
            report = fn(path)
        except Exception:
            logger.critical(
                f"[migrations] {name} FAILED against {path} — refusing to "
                f"continue startup with a database in an unknown schema "
                f"state. Fix the underlying error, then restart.",
                exc_info=True,
            )
            raise
        reports.append({"migration": name, "db_path": path, "report": report})
        logger.info(f"[migrations] {name} → {report}")
    return reports


def _main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    reports = run_pending_migrations(path)
    for r in reports:
        print(f"== {r['migration']} ({r['db_path']}) ==")
        for t in r["report"].get("tables", [r["report"]]):
            if isinstance(t, dict) and "table" in t:
                print(f"  {t['table']:<24} {t['status']:<20} backfilled_rows={t.get('backfilled_rows', 0)}")
            else:
                print(f"  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
