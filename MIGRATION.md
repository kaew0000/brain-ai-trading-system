# MIGRATION — Close Out V16 BUG-LIVE-RISK-06: Scheduler-Path Gate 0 + Restart Persistence

## Do you need to do anything?

**No `.env` changes required.** One thing happens automatically on
first use after this restart: a new `risk_engine_state` table is
created in the trade journal DB (lazy `CREATE TABLE IF NOT EXISTS`,
same pattern every other schema addition in this project uses) the
first time an override is armed, persisted, or checked. No manual
migration step, no downtime.

## What changes in behavior after this restart

- **Scheduler path** (currently dormant — `SCHEDULER_ENABLED=False`
  by default, so this has zero effect on today's live single-symbol
  trading): once the multi-symbol scheduler is turned on, arming an
  override via the dashboard now reliably waits for an actual order to
  be about to go out before being spent, instead of potentially being
  consumed by a portfolio pre-check that ends up selecting nothing.
- **Restart persistence** (this one is live-relevant today): arming a
  one-shot override and then restarting the bot before it gets used no
  longer silently discards it. On the next startup, `RiskEngine`
  restores it from the journal DB and logs `RISK OVERRIDE RESTORED
  from previous session`. It is still genuinely one-shot — the next
  real `can_trade()` call (or a manual `clear_consecutive_loss_
  override()`) still spends/clears it, exactly as before, just now
  surviving a restart in between.
- No change to `daily_loss` blocking, `manual_hold`, or any other risk
  gate behavior.

## Rollback

Revert this branch and restart. `CapitalManager.decide()`'s Gate 0
goes back to calling `can_trade()` directly, `ExecutionScheduler`
loses its own real-gate check, and `RiskEngine` stops
reading/writing `risk_engine_state`. The `risk_engine_state` table
itself is harmless to leave behind in the DB file if you roll back —
nothing reads it once this code is reverted.

## Closing the superseded branch

`fix/risk-override-persists-across-restart` (`61cea14`) is fully
superseded by this branch. No PR was ever opened for it, so nothing to
formally close on GitHub — just don't merge it; delete the branch
whenever convenient.
