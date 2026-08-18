# MIGRATION — V16 Phase 4C: Automatic Migration Runner

## Do you need to do anything?

**Recommended: yes, once, right now — don't wait for a redeploy.**
This phase makes future migrations apply automatically on every boot,
but the *existing* production database file on your machine won't get
today's fix until the process restarts on this new code. If you want
the schema fixed immediately, without waiting to redeploy, run this by
hand first:

```
python -m database.migrations.runner /path/to/your/brain_bot_v13.db
```

(Path is whatever `DATABASE_PATH` resolves to in your `.env` — default
is `brain_bot_v13.db` in the working directory. If unset, falls back to
`JOURNAL_DB_PATH`, default `brain_bot_journal.db` — check which one
your deployment actually uses before running this.)

Either way — manually now, or automatically on next boot once this
branch is merged and deployed — this is **safe to run against your real
production file**: idempotent, wraps each table rebuild in its own
transaction with rollback on error, and only ever adds the
`execution_lane` column + backfills existing rows to `'LIVE'` (approved
classification: all historical data predates the dual-lane concept and
was real money — see `docs/architecture.md`'s W14-2D-1 section). It
never touches `result`, `pnl`, or any other existing column's values.

**Back up the database file first anyway** — standard practice before
any schema change to a live-money production database, independent of
how well-tested the migration is.

No new environment variables. No code outside `main.py` and
`database/migrations/` touched.

## What actually changed, mechanically

Before: `database/migrations/migration_001_execution_lane_backfill.py`
existed and was correct, but nothing ever called it. An operator's
existing database file silently stayed on the pre-W14-2D-1 schema after
pulling new code, and the first write to `trades` / `signals` /
`agent_decisions` / `feature_rows` / `ml_predictions` /
`order_timeline_history` raised `sqlite3.OperationalError: no such
column: execution_lane`.

After: `main.py::build_system()` calls
`database.migrations.runner.run_pending_migrations()` as its very first
step, before any other component opens the database file. On an
unmigrated file, this transparently applies `migration_001` (and any
future migration added to the registry) before the trading engine,
journal, or API server ever touch it. On an already-migrated file, it's
a fast no-op every boot — nothing to remember, nothing to run by hand
going forward.

## Rollback

Revert `main.py`'s one new import line and the `[0/9]` block in
`build_system()`. Delete `database/migrations/runner.py` and
`tests/test_migration_runner.py`. `migration_001_execution_lane_backfill.py`
itself is untouched and unaffected either way — this phase only adds a
caller for it.

Rolling back does **not** un-migrate a database file that already had
`migration_001` applied (by this phase's automatic runner, or by hand)
— that migration is itself one-way by design (adds a NOT NULL column
and backfills it; there is no stored "old" value to restore). This
matches `migration_001`'s own pre-existing behavior, unchanged by this
phase.

## What this does not fix

- The dashboard refresh/re-login issue — unrelated, separate root
  cause (frontend + `api/auth.py` session design), not touched here.
  See `PATCH_NOTES.md`'s Scope note.
- Legacy `TradeJournal` V1's raw `sqlite3.connect()` usage
  (`analytics/trade_journal.py`) and `world/readers/base.py`'s
  `SQLiteSource` — both flagged during this phase's inspection as
  bypassing `database/db.py`'s WAL/lock protections, both left
  untouched. See `PATCH_NOTES.md`'s "What this does not fix" for the
  full detail and why.
- Does not change what any migration actually does to the schema —
  purely wires up automatic invocation of migrations that already
  existed (or will exist in the future).
