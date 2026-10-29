# PATCH NOTES — Daily stats use the UTC day (V16 §91)

Branch: `fix/risk-daily-stats-utc-day`
Base: `main` @ `7f7d0f8` (PR #131 merged)
Commit: `fix(risk): daily stats use the UTC day, not the host local date (V16 §91)` (exactly one)

## Root cause (verified)
1. `journal/journal_v2.py::get_daily_stats()` defaulted `day` to `date.today()` (host local date); the query is `date(timestamp)=?` over timestamps
   stored as UTC ISO strings (`datetime.now(timezone.utc)`), which SQLite evaluates in UTC.
2. `RiskEngine.check_daily_loss()` -> `journal.get_today_pnl(execution_lane=...)` -> `get_daily_stats()`. On a UTC+7 host between 00:00 and 07:00
   local, "today" (local) is one day ahead of the UTC day, so the current UTC day's losses were not counted by the daily-loss gate.
3. `RiskEngine._reset_if_new_day()` already used the UTC day, so the gate disagreed with itself. The legacy `analytics/trade_journal.py` had the same default.

## Changes (additive, minimal)
- `journal/journal_v2.py`: new `_utc_today_iso()`; `get_daily_stats()` defaults to it; unused `date` import removed.
- `analytics/trade_journal.py`: same default (UTC date); unused `date` import removed.
- `tests/test_daily_stats_utc_day_boundary.py` (new, 4 tests): fake clock (2026-10-28 20:00 UTC == 2026-10-29 03:00 Bangkok). 3 fail on old code, all pass now.
- Docs: `docs/architecture.md` §91, `CHANGELOG.md`, `docs/ROADMAP.md` (item closed), this file, `MIGRATION.md`.

## Not changed
- `RiskEngine`, execution layer, config, DB schema, lane scoping, explicit `day=` behaviour.
- The day filter is still the trade's open `timestamp` (not close time) - pre-existing, out of scope.
