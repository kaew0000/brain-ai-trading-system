# MIGRATION — LifecycleControl Unauthorized-State Visibility Fix

## Do you need to do anything?

**No code/config migration.** This is a pure frontend (`dashboard_src/`)
visual fix — no API changes, no schema changes, no new environment
variables, no backend touched.

**You do need to rebuild the dashboard bundle** for the change to
reach the browser: `cd dashboard_src && npm run build`, then redeploy
the built `dist/` the same way your `run.bat`/`run_live.bat` /
FastAPI static-file serving already does. If your dashboard is served
via a pre-built `dashboard/` directory checked into the repo (as
implied by the project's own `ruff`/`vulture` excludes), copy the new
`dist/` output over it as usual — nothing in this patch changes how
that directory is produced or served.

## What actually changed, mechanically

Before: an unauthenticated viewer saw a real but visually-inert
button — label `…`, muted gray, `cursor-wait` — with a native browser
tooltip ("Login as OPERATOR to control the bot") as the only hint it
did anything.

After: the same button shows a clearly distinct blue "LOGIN" state
whenever `role` is not at least `OPERATOR`. Clicking it does exactly
what it already did (opens the login modal) — only the visible
label/color changed.

## Rollback

Revert `dashboard_src/src/components/commander/LifecycleControl.tsx`
and `dashboard_src/src/lib/lifecycleControl.ts` to their `main`
versions, and delete
`dashboard_src/src/lib/tests/lifecycleButtonDisplay.test.ts`. Nothing
else references `lifecycleButtonDisplay` or the `login` tone —
private to these two files.

## What this does not fix

- Does not touch `api/auth.py`'s "every route needs credentials"
  posture — that is deliberate design (see that file's own docstring),
  not a bug.
- Does not address the separate `no such column: execution_lane`
  error seen in the same session's log
  (`journal/journal_v2.py::get_open_trades` /
  `get_daily_stats`) — that is a pre-existing production database
  (`brain_bot_v13.db`) that predates the already-merged W14-2D-1
  schema change and has not yet had
  `database/migrations/migration_001_execution_lane_backfill.py` run
  against it. That is an **operational step you run once**, not a code
  change — see the accompanying chat reply for the exact command.
