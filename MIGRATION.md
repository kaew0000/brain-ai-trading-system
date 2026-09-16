# MIGRATION — Multi-Symbol Order State & Ghost Reconciliation (V16 §66)

## Do you need to do anything?

**No, if `SCHEDULER_ENABLED=false` (the default).** Every code path
this patch touches under that flag is byte-for-byte unchanged —
confirmed by re-running all 120 pre-existing tests across every
affected file unmodified.

## If you're running multi-symbol trading (`SCHEDULER_ENABLED=true`)

Two things that previously silently returned wrong data (or nothing at
all) now work correctly:

- Any dashboard/API call to `GET /api/system/order-state?symbol=...`
  (or equivalent internal calls to `OrderStateManager.get_order_state()`)
  for a symbol other than `settings.SYMBOL` now returns **that
  symbol's** real state, not `settings.SYMBOL`'s state mislabeled with
  the symbol you asked for.
- If you have `ORDER_RECONCILIATION_ENABLED=true` (Track C3 Phase 2,
  still off by default even now), `run_ghost_reconciliation_check()`
  checks every actively-traded symbol each cycle, not just the default
  one. It was previously **not scheduled at all** while
  `SCHEDULER_ENABLED=true`, regardless of `ORDER_RECONCILIATION_ENABLED`
  — if you had both flags set, this job silently did nothing before
  this patch. It runs now.

No new `.env` settings — nothing to add, this closes an existing gap
rather than introducing a new opt-in.

## Rollback

Revert this branch and restart. `OrderStateManager.get_order_state()`
goes back to always reading `settings.SYMBOL`'s state regardless of
the `symbol` argument, and `run_ghost_reconciliation_check()` goes
back to not being scheduled at all under `SCHEDULER_ENABLED=true`. No
data migration either direction.
