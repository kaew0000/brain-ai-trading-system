# MIGRATION — Auto-rebuild stale dashboard (V16 §84)

## Required
None. Launchers (`run.bat`, `run_live.bat`, `run_paper.bat`, `run_testnet.bat`) pick this up on the next start. Requires Python on
PATH (already required to run the bot) and, for rebuilds, Node.js LTS.

## What you will notice
- After `git pull`, the next launcher start prints `[i] Dashboard build is build - rebuilding V16 dashboard...` (about 40 s; an
  `npm ci` first when dependencies changed, a few minutes) and then starts the bot. Press Ctrl+F5 in the browser once.
- When `dist` is up to date nothing is printed and startup is unchanged.

## New environment variable (optional)
    BRAIN_DASHBOARD_AUTOREBUILD=0     # skip the stale check (a MISSING dist is still built, as before)

## Behaviour changes
- `scripts/ensure_dashboard.bat` rebuilds when sources are newer than `dashboard_src\dist\index.html`, not only when `dist` is missing.
- A failed rebuild restores the previous `dist` instead of leaving none (which would serve the legacy fake-data demo).

## Manual equivalent
    cd dashboard_src && npm ci && npm run build

## Rollback
`git revert` the commit, or set `BRAIN_DASHBOARD_AUTOREBUILD=0`. Delete `%TEMP%\brain_dashboard_dist_backup` at any time.
