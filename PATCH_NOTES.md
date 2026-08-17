# PATCH NOTES — V16 Phase 4C: Automatic Migration Runner

Branch: `feature/db-migration-auto-runner`
Base: `main` @ `8920cd7` (merge of PR #65, Train Monitor Dashboard Tab)

## Scope note

Requested directly: "ระบบมีปัญหาเมื่อรันใช้งานจริง ... ตรวจสอบและแก้ไขปัญหาด้าน
database ของระบบ ให้อัพเกรด database ให้ใช้งานกับระบบได้ครบทุกส่วนของระบบล่าสุด"
(production system has problems; inspect and fix database issues; upgrade
the database so it works with every part of the latest system).

Track A only (`.py`). Zero `dashboard_src/` changes. Additive only — no
existing writer, table, or migration script modified.

A second, unrelated symptom was also reported in the same message
("refresh the dashboard and it forces a re-login"). Inspected
(`dashboard_src/src/lib/api.ts`, `dashboard_src/src/stores/index.ts`,
`api/auth.py`) and confirmed this is a deliberate design choice — the
bearer JWT is held in memory only, never `localStorage`/`sessionStorage`,
specifically so a page reload can't be used to exfiltrate a stolen
session token via XSS. It is unrelated to the database and is **not**
addressed by this phase; tracked separately, pending owner decision on
priority.

## Root cause (inspected before writing anything)

`database/db.py::_apply_schema()` only ever runs `CREATE TABLE IF NOT
EXISTS ...`, which is a no-op against a table that already exists. The
W14-2D-1 phase added a `execution_lane TEXT NOT NULL CHECK(...)` column
to `trades` / `signals` / `agent_decisions` / `feature_rows` /
`ml_predictions` / `order_timeline_history`, and shipped a correct,
idempotent migration for it
(`database/migrations/migration_001_execution_lane_backfill.py`) — but
**nothing in the codebase ever called it**. Confirmed by grep: the only
references to that module, outside itself, were its own tests. Its own
package docstring even says so explicitly: "Nothing in database/db.py
invokes these automatically — an operator ... runs them explicitly."

Effect on an operator who pulls new code and restarts against an
existing database file created before W14-2D-1: the file is silently
left on the old schema, and the first write from `TradeJournalV2` (e.g.
`save_trade()`, whose `INSERT` statement includes `execution_lane` with
no fallback) raises
`sqlite3.OperationalError: no such column: execution_lane`. This matches
the previously-known issue with `monitor_open_trades()` /
`daily_report()` in `main.py`.

## What changed

### Added
- `database/migrations/runner.py` — new, small, ordered registry module.
  `run_pending_migrations(db_path=None)` runs every registered migration,
  in order, against `db_path` (defaults to `database.db.get_db_path()`).
  Currently registers exactly one migration
  (`001_execution_lane_backfill`) — future migrations are added by
  importing them and appending one `(id, migrate)` tuple to
  `_MIGRATIONS`; nothing else in this module or its call site needs to
  change.
  - Idempotent as a whole (relies on `migration_001`'s own idempotency,
    already covered by `tests/test_execution_lane_contract.py`) — safe
    to call on every process boot.
  - Raises on the first migration that fails; never continues startup
    past a migration whose outcome is unknown. This is intentional:
    starting live trading against a database in an unknown schema state
    is worse than refusing to start.
  - Standalone CLI: `python -m database.migrations.runner [db_path]` —
    lets an operator apply pending migrations against a real production
    file by hand, without booting the whole system, either as an
    immediate fix before redeploying or as a diagnostic.
- `tests/test_migration_runner.py` — 7 new tests covering the registry
  itself (non-empty, well-formed), `run_pending_migrations()` against a
  simulated legacy pre-W14-2D-1 file, idempotency across repeated calls
  (simulating repeated boots), a brand-new/empty file (no-op, not an
  error), default `db_path` resolution via `database.db.get_db_path()`,
  and failure propagation (a broken migration raises and halts before
  any later migration runs — never swallowed).
  - Deliberately does **not** re-test `migration_001`'s own internal
    correctness (rebuild-with-backfill, CHECK/NOT NULL enforcement) —
    already covered by
    `tests/test_execution_lane_contract.py::TestHistoricalMigrationBackfill`.
    Duplicating those assertions here would be two tests guarding the
    same behavior.

### Changed
- `main.py::build_system()` — new step `[0/9] Database Schema
  Migrations …` calls `run_pending_migrations()` before any other
  component in this function opens a connection to the database file
  (the `TradeJournal()`/`TradeJournalV2()` construction at `[6/9]` was
  previously the earliest that happened). One new import
  (`from database.migrations.runner import run_pending_migrations`), one
  new call, zero lines removed, zero existing steps renumbered or
  reordered.

## Verification

- `pytest tests/`: 2590 passed (2583 baseline + 7 new), 45 deselected
  (integration marker), same 3 pre-existing failures as baseline
  (`tests/test_dashboard_serving.py` — require a `dashboard_src/dist/`
  build not present in this environment; unrelated to this phase, fail
  identically before this branch existed).
- `ruff check . --exclude dashboard_src --exclude dashboard`: clean,
  before and after.
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80`:
  clean, no hits on either new file.
- `python3 -c "import main"`: OK, before and after.
- Manual end-to-end sanity check against a simulated legacy database
  file (old `trades` schema, no `execution_lane`): first call migrates
  and backfills the existing row to `LIVE`; second call is a clean
  `already_migrated` no-op. Matches the automated test coverage above.
- Independent second-clone verification: see delivery message.

## What this does not fix

- The dashboard refresh/re-login issue — separate, frontend+backend
  session-persistence design, not a database problem. See Scope note
  above.
- `analytics/trade_journal.py` (legacy `TradeJournal` V1) still opens
  its own raw `sqlite3.connect()`, bypassing `database/db.py`'s WAL /
  busy-timeout / write-lock protections. Still instantiated in
  `main.py` and used for one read path
  (`monitor_open_trades()`'s `journal.get_open_trades()` call in the
  legacy single-symbol loop). Flagged during this phase's inspection,
  left untouched — out of scope for a database-migration phase, and
  fixing it means deciding whether to retire V1 entirely or route it
  through `database/db.py`, which needs an explicit decision, not a
  silent change.
- `world/readers/base.py::SQLiteSource` also opens a raw connection
  with no `busy_timeout` set. Same category, lower severity (read-only,
  well-isolated). Also flagged, not fixed here.
- Does not add a formal schema-version table (e.g. `PRAGMA
  user_version` tracking) — `_MIGRATIONS`'s ordered-list-plus-per-table
  idempotency-check approach was kept because it matches the existing,
  already-tested pattern in `migration_001` exactly; a version-table
  approach would be a bigger, separate design decision.
