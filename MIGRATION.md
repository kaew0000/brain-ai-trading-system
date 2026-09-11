# MIGRATION — Multi-Symbol Reconciliation & Orphan Protection (V16 §62)

## Do you need to do anything?

**No, if `SCHEDULER_ENABLED=false` (the default).** `run()`'s
single-symbol behavior, and every existing `get_recent()`/`status()`/
`get_last_views()`/`get_orphan_hold()` call, are byte-for-byte
unchanged — confirmed by re-running all 69 pre-existing tests across
`test_reconciliation.py`, `test_recovery_engine.py`,
`test_ghost_reconciliation*.py`, and `test_close_orphaned_position.py`
unmodified.

## If you're running multi-symbol trading (`SCHEDULER_ENABLED=true`)

Position reconciliation now actually protects you across every symbol
you're trading, not just the configured default:

- Every 60s, each symbol with an open exchange position, open journal
  trade, or tracked portfolio-state entry gets its own independent
  reconciliation check — mismatches are detected, logged, and
  auto-recovered per symbol.
- An orphaned exchange position (real position, no journal record —
  e.g. from before this bot session) in **any** symbol now gets an
  automatic protective stop-loss and puts trading on hold, exactly like
  single-symbol mode already did for the one default symbol.
- If more than one symbol is simultaneously orphaned, each is tracked
  and protected independently. Trading only resumes once **every**
  orphan has been acknowledged.

### Acknowledging an orphan hold

```bash
# See what's currently held
curl -H "Authorization: Bearer $YOUR_API_KEY" \
  "http://<host>:<port>/api/system/reconciliation"
# -> look at "orphan_holds" (a list now, not just "orphan_hold")

# Acknowledge one specific symbol
curl -X POST -H "Authorization: Bearer $YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"symbol": "XRPUSDT"}' \
  "http://<host>:<port>/api/system/reconciliation/acknowledge"

# Or acknowledge everything at once (omit the body) -- same as before this patch
curl -X POST -H "Authorization: Bearer $YOUR_API_KEY" \
  "http://<host>:<port>/api/system/reconciliation/acknowledge"
```

### Still not covered

`run_ghost_reconciliation_check()` (`ORDER_RECONCILIATION_ENABLED`,
off by default even in single-symbol mode) remains single-symbol only
— not scheduled at all while `SCHEDULER_ENABLED=true`. If you rely on
this specific job, it needs its own follow-up fix first.

## Rollback

Revert this branch and restart. `run_position_reconciliation()` goes
back to calling `engine.run()` unconditionally regardless of
`SCHEDULER_ENABLED` — under scheduler mode this reverts to §60's
"not scheduled at all" state (safer than running with known-wrong
data), not the multi-symbol-aware behavior. No data migration either
direction.
