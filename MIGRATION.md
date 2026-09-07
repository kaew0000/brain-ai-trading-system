# MIGRATION — Fix: report() Silently Consuming the One-Shot Risk Override (V16 BUG-LIVE-RISK-06)

## Do you need to do anything?

**No action required to get the fix.** No new settings, no `.env`
changes, no config migration. Restart the bot after this branch is
merged and the fix is active immediately.

## What changes in behavior after this restart

- Arming a one-shot override via the dashboard/API
  (`override_next_trade_despite_streak()` /
  `POST /api/system/risk_override_next_trade`) now reliably survives
  until the **next actual trade decision** — checking the dashboard,
  asking Commander "show risk," or simply waiting through normal
  per-cycle telemetry no longer burns it early.
- `RiskEngine.report()`'s returned dict is unchanged in shape (same
  keys as before) — `consecutive_loss_override_armed` and
  `consecutive_loss_override_reason` now stay `True`/populated across
  repeated `report()` calls instead of flipping to cleared after the
  first one.
- The real trade gate (`main.py`'s per-cycle `rsk.can_trade(balance)`,
  `portfolio/capital_manager.py`'s Gate 0) behaves exactly as before —
  still consumes the override on the first real check, still
  genuinely one-shot.
- No behavior change at all if you have never used
  `override_next_trade_despite_streak()` / the dashboard's "override
  next trade" control — this only changes what happens while an
  override is armed.

## Rollback

Revert this branch and restart. `RiskEngine.can_trade()` and
`RiskEngine.report()` return to their previous coupled behavior
(`report()` consumes the override as a side effect) — no data
migration either direction, since no persisted state format changed.

## Note for whoever merges the sibling branch

`fix/risk-override-persists-across-restart` (commit `61cea14`) touches
the same methods in `risk/risk_engine.py` and will conflict with this
branch textually. See PATCH_NOTES.md's "Known follow-up" section for
details before merging both.
