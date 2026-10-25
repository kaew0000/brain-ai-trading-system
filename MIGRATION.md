# MIGRATION — World live monitoring (V16 §82)

## Required
1. Rebuild the dashboard and restart the backend (a new thread starts with it):

       cd dashboard_src && npm ci && npm run build

   then Ctrl+F5 in the browser.

## New settings (optional; defaults shown, add to `.env` only to change)
    WORLD_SIM_TICK_INTERVAL_SECONDS=2.0   # 0 = legacy: one tick per LOOP_INTERVAL on the scheduler
    WORLD_TIMELINE_HISTORY_WINDOW=900     # ticks kept for Timeline replay (30 min at 2 s)

Lower tick interval = smoother movement and more frame requests; raise it on a slow machine.

## Behaviour changes
- World simulation ticks every 2 s on its own thread instead of once per trading cycle. Tick numbers no longer match
  trading cycles 1:1. Timeline replay now covers ~30 minutes (was ~8 hours at 60 s ticks); raise
  `WORLD_TIMELINE_HISTORY_WINDOW` for longer (about 4 KB of memory per tick).
- Office tab shows a System Pulse strip and the scene updates live.
- New read-only endpoint `GET /api/world/ticker`.

## Checking it works
`GET /api/world/ticker` should report `"status":"ok"`; the backend log shows `WorldSimulationTicker started (interval=2.0s)`.
If it shows `disabled`, the interval is 0 or the ticker failed to start (see the log line starting
`WorldSimulationTicker failed to start`): the old scheduled tick is then used.

## Rollback
Set `WORLD_SIM_TICK_INTERVAL_SECONDS=0` for the old tick behaviour without reverting code, or `git revert` the commit.
