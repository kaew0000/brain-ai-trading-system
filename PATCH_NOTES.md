# PATCH NOTES — V16 Phase 2F: Execution Scheduler + Multi-Symbol Signals

Branch: `feature/execution-scheduler-multi-symbol-signals`
Base: `main` (post Bundle Manager + Phase 2E merge, 1478 passing)

## Summary

Completes the connection Phase 2E built but didn't wire up: a timer
loop that actually calls `PortfolioManager.decide()` then
`ExecutionOrchestrator.execute()` in production, fed by a real
multi-symbol signal generator. Both were named as "Next up" in
`docs/architecture.md` §23 and independently confirmed by `CLAUDE.md`'s
own priority list (Priority 5, directly after Portfolio Manager/Capital
Allocation/Correlation/Sector Engine — all already done).

**The hard part of this phase happened before writing any code.** The
design started from `execution/strategy.py`'s `SMC_OI_Regime_Strategy`
(the only existing per-symbol-shaped signal adapter) — but reading
`main.py`'s actual `run_trading_cycle()` showed the live single-symbol
bot never instantiates that class or the `BrainDecisionEngine` it
wraps. It uses a different pipeline: `RegimeEngine` -> `SMCEngine` ->
`VolumeEngine` -> `MarketContextBuilder` -> `ConfidenceEngine`. Building
this phase on the wrong pipeline would have produced signals that don't
match what the live bot actually does — caught by reading the real
code first, not assumed. See `docs/architecture.md` §24 for the full
writeup.

## New modules

| File | Purpose |
|---|---|
| `execution/portfolio_signal_provider.py` | `PortfolioSignalProvider` — the real `signal_provider` `ExecutionOrchestrator` (§23) was built to accept. Reuses the verified-live pipeline for an arbitrary symbol. Never raises. |
| `execution/execution_scheduler.py` | `ExecutionScheduler` — rank -> limit -> balance -> decide -> execute, on a timer. Threading mirrors `MarketScanner` exactly. |

## Changes to existing modules

| File | Change |
|---|---|
| `data/binance_provider.py` | `+symbol=` optional param on 7 methods (all default to `self.symbol` — zero behavior change for existing callers), `+get_market_data_for(symbol)`. |
| `intelligence/market_context_builder.py` | `+symbol=` optional param on `build()` — the one place a symbol was implicitly hardcoded in an otherwise fully stateless pipeline. |
| `config/settings.py` | `+SCHEDULER_ENABLED` (default `False`), `+SCHEDULER_INTERVAL_SECONDS` (60), `+SCHEDULER_CANDIDATE_LIMIT` (20). |
| `main.py` | New guarded bootstrap block (same shape as the existing `MarketScanner` block): builds `PortfolioSignalProvider`/`PortfolioManager`/`ExecutionOrchestrator`/`ExecutionScheduler` and starts it, only if `SCHEDULER_ENABLED=true` (requires `SCANNER_ENABLED` too — logged, not a hard error, if missing). Reuses the already-built `trade_manager`. `+execution_scheduler` key in the returned bootstrap dict. |
| `docs/architecture.md` | New §24. §1-23 byte-for-byte untouched (verified with `diff`, not asserted). |

**Nothing was removed or had its public signature changed.** Every
existing single-symbol call site — `run_trading_cycle()`,
`monitor_open_trades()`, every direct `dp.get_ohlcv()`/`get_mark_price()`
call, `context_builder.build()` without a `symbol=` argument — is
byte-for-byte unchanged in behavior.

## Two real bugs caught before merge, not written around

1. **A Python scoping bug that would have broken the pre-existing
   single-symbol execution path.** The first draft locally re-imported
   `build_execution_engine` inside the new bootstrap block — but that
   name is already imported at module level and used earlier in the
   *same function* (`build_system()`). Python treats any name assigned
   anywhere in a function body as local to the whole function, so the
   earlier, unrelated, already-working call would have silently started
   reading an unassigned local variable — but only once
   `SCHEDULER_ENABLED=true` was actually set, making it exactly the kind
   of bug that hides until someone flips a flag in production.
   `ruff check .`'s `F823` caught it before this was ever run. Fixed by
   removing the redundant local import.
2. **A design bug in the same block.** The first draft called
   `build_execution_engine()` a second time to get an execution engine
   for the new `ExecutionOrchestrator`, instead of reusing
   `trade_manager` (already built a few lines above in that same
   function). In paper mode this would have created a second,
   independent `PaperExecutionEngine` with its own separate balance; in
   testnet/live mode, a second `ExecutionCoordinator` with its own
   separate per-symbol `TradeManager` cache — silently splitting
   execution state into two disconnected halves of the same process.
   Fixed by passing the existing `trade_manager` through.

## Scope boundary

Does NOT build reconciliation-fed `PortfolioState` construction.
`system_health/reconciliation.py`'s actual code is a mismatch-detection
engine (exchange vs. bot vs. journal views), not a "build a
`PortfolioState` from real positions" utility — reading it confirmed
this rather than assuming it was already solved. `ExecutionScheduler`'s
`PortfolioState` starts empty each process start and is built up ONLY
from its own executions; a position opened before it started, by the
legacy single-symbol loop, or manually on the exchange, is NOT
reflected. This is real, scoped-out follow-up work, not a hidden gap —
see `docs/architecture.md` §24 "Next up".

Also does not: persist execution outcomes anywhere durable (carried
forward from §23, unchanged), build a dashboard panel for the new
scheduler/signal-provider, or change `RiskEngine`/`CapitalManager`/
`PortfolioManager`/`SectorEngine`/`ExecutionOrchestrator`/
`ExecutionCoordinator` — every one of those is called exactly as
already built and tested, never modified.

## Test results

```
pytest tests/ -q
1512 passed, 0 failed   (1478 baseline + 34 new)

ruff check .
All checks passed!   (one real F823 scoping bug + one design bug
                       (duplicate execution engine) + two unused-import
                       findings during development, all fixed before
                       this count)
```

New test files: `tests/test_portfolio_signal_provider.py` (12),
`tests/test_execution_scheduler.py` (22). `main.py`'s own new bootstrap
block is deliberately not directly unit-tested — matching the existing,
already-accepted precedent that `MarketScanner`'s identical bootstrap
block isn't either (needs real Binance clients to exercise
meaningfully; the safe-by-default posture is what's tested instead).

## Known limitations / follow-up (documented, not hidden)

- `ExecutionScheduler`'s `PortfolioState` is not reconciliation-fed (see
  "Scope boundary" above) — restarting the process loses track of
  positions it opened in a prior run until real reconciliation-fed
  state construction is built.
- No execution-outcome persistence yet (carried forward from §23).
- No dashboard panel for `ExecutionScheduler.to_dict()` or the
  already-existing `/api/execution/*` endpoints (§23).
- `SCHEDULER_ENABLED=true` with `SCANNER_ENABLED=false` is logged and
  silently skipped rather than started — by design (the Scheduler has
  nothing to rank without the scanner), but worth knowing if the
  scheduler doesn't seem to start.

See `MIGRATION.md` for upgrade/rollback notes.
