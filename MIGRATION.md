# MIGRATION — Train Monitor Dashboard Tab

## Do you need to do anything?

**No backend/config migration.** Purely additive frontend
(`dashboard_src/`) change: one new page, one new route, one new nav
entry, one new type, one new small pure helper. No API changes, no
schema changes, no new environment variables, no existing route or
component modified.

**You do need to rebuild the dashboard** for the new tab to appear:
`cd dashboard_src && npm run build`, then redeploy the built `dist/`
the same way you already do (see the previous patch's MIGRATION notes
for the same step — nothing about that process changed here either).

## What actually changed, mechanically

Before: `GET /api/ml/models` existed on the backend and was even
already wired into the frontend API client (`api.mlModels()`), but no
page ever called it — the per-version training history (win rate,
profit factor, training rows, active/retired) was only visible by
querying the API directly or reading the SQLite `model_registry` table
by hand.

After: a new "Train Monitor" tab in the left nav (`/train`) shows that
history per model type, plus the already-live status/performance data
`SystemHealth.tsx` already partially surfaces, plus a session-local
"rows added since you opened this tab" counter.

## Rollback

Revert `App.tsx` and `components/layout/Layout.tsx` to their `main`
versions, and delete `pages/TrainMonitor.tsx`,
`lib/trainMonitor.ts`, and `lib/tests/trainMonitor.test.ts`. The one
addition to `types/api.ts` (`MLModelsData`) is inert if left in place
(nothing else imports it) but can be reverted too for a fully clean
rollback.

## What this does not fix

- Does not change what `/api/ml/models`, `/api/ml/status`, or
  `/api/ml/performance` return, or how often the ML advisor itself
  runs — this page only visualizes what already exists.
- Does not add a computed "training health" verdict (ALIVE/STALE) —
  see `PATCH_NOTES.md`'s "Why no invented training-is-healthy verdict"
  section for why that was deliberately left out rather than guessed.
- Does not touch the separate `execution_lane` migration or the
  `LifecycleControl` visibility fix from the prior patch — both
  unrelated, already delivered separately (PR #64, already merged).

## Note on this branch's rebase

This branch was originally built on `main @ a88bb5b`. By the time it
was ready, PR #64 (`fix/lifecycle-control-unauth-visibility`) had
already merged to `main` (now at `ece01c9`), which is why GitHub
reported "Can't automatically merge" on the compare/PR view — both
phases independently rewrote `CHANGELOG.md`/`PATCH_NOTES.md`/
`MIGRATION.md`. This branch has been rebased onto current `main` and
re-verified (tests/build/independent-clone) — see `PATCH_NOTES.md`'s
Branch/Base line for the exact resolution. No code file conflicted.
