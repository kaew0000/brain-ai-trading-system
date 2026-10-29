# MIGRATION — Daily stats use the UTC day (V16 §91)

## Required
None. No config, schema or data migration.

## What you will notice
- On a host whose timezone is not UTC (e.g. Asia/Bangkok), `get_daily_stats()` / `get_today_pnl()` called without `day=` now report the UTC day. The
  dashboard "today" figures and the printed daily report roll over at 00:00 UTC (07:00 Bangkok) instead of local midnight.
- The daily-loss limit (`MAX_DAILY_LOSS`) now counts the same UTC day the rest of `RiskEngine` uses. Previously, 00:00-07:00 Bangkok, losses booked
  earlier that UTC day could be invisible to the gate.
- On a UTC host nothing changes.

## Rollback
`git revert` the commit. No data was modified.
