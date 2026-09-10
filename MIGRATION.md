# MIGRATION — Multi-Symbol Scheduler Safety (V16 §60)

## Do you need to do anything?

**No, if you keep running as today (single-symbol BTCUSDT loop).**
`SCHEDULER_ENABLED` defaults `False` — nothing in this patch changes
behavior until you deliberately turn it on. All 426 pre-existing tests
touching the changed functions pass unchanged, confirming this.

## To actually turn on multi-symbol auto-selection

This patch makes it *safe*; it does not turn it on. In your `.env`:

```bash
SCANNER_ENABLED=true      # required — ExecutionScheduler needs it for candidates
SCHEDULER_ENABLED=true    # the multi-symbol path itself
```

Restart the bot after setting these. What changes:

- The classic single-symbol BTCUSDT loop **stops running entirely**
  (not just "less relevant" — literally not scheduled). All new trade
  decisions come from the scanner + portfolio manager + scheduler
  instead, across every symbol passing `SCANNER_MIN_QUOTE_VOLUME`
  (default: $1,000,000 24h quote volume — already a sensible liquidity
  floor, no change needed there).
- `monitor_open_trades()` (every 30s) correctly tracks a position in
  *any* symbol, not just `settings.SYMBOL`.
- `run_position_reconciliation()` and `run_ghost_reconciliation_check()`
  **stop running** (logged as a warning at startup) — see
  PATCH_NOTES.md's "Known follow-up": running them with single-symbol
  data while genuinely multi-symbol would be actively dangerous
  (the recovery engine auto-clears what it thinks are "ghost"
  positions). This means: while in scheduler mode, an orphaned
  exchange position (opened outside the bot, e.g. manually or from a
  previous session) will **not** get an automatic protective stop-loss
  the way it would in single-symbol mode. Check positions manually if
  you suspect this could happen, until multi-symbol reconciliation is
  built.
- `settings.SYMBOL`/`LEVERAGE` still matter as the *default provider
  symbol* (used by anything that doesn't specify one) but no longer
  drive what actually gets traded.

### Recommended: test on Binance Testnet first

This is the first time this code path (`SCHEDULER_ENABLED=true`) will
run against a live account. Per this project's own tooling
(`BINANCE_TESTNET=true`), recommend at least one full day on testnet
before enabling on the live $20 account, purely because "never run in
production before" carries its own risk independent of anything fixed
in this patch.

## Rollback

Set `SCHEDULER_ENABLED=false` (or revert this branch) and restart.
The classic single-symbol loop resumes exactly as before;
`monitor_open_trades()` and reconciliation both fall back to their
pre-§60 single-symbol behavior automatically (the branch is keyed off
the same flag). No data migration either direction.
