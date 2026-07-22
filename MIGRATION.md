# MIGRATION — V16 Phase 2F: Execution Scheduler + Multi-Symbol Signals

## Do you need to do anything?

**No code changes required for existing callers.** Every existing
single-symbol call site is unaffected:

- `data/binance_provider.py`'s 7 modified methods all default the new
  `symbol=` parameter to `self.symbol` — call them exactly as before
  and nothing changes.
- `intelligence/market_context_builder.py`'s `build()` defaults the new
  `symbol=` parameter to `settings.SYMBOL` — same.
- `main.py`'s single-symbol trading loop (`run_trading_cycle()`,
  `monitor_open_trades()`, etc.) is byte-for-byte unchanged.
- `config/settings.py`'s three new `SCHEDULER_*` settings all default
  to off/safe values — no `.env` change required to deploy.

## If you want to turn the Scheduler on

It's off by default. To enable it:

```bash
# .env
SCANNER_ENABLED=true      # required — the Scheduler needs the Market
                           # Scanner for candidates; if this is false,
                           # SCHEDULER_ENABLED is logged and skipped,
                           # not a hard startup error
SCHEDULER_ENABLED=true
SCHEDULER_INTERVAL_SECONDS=60      # optional, default shown
SCHEDULER_CANDIDATE_LIMIT=20       # optional, default shown
```

Restart the bot. On startup you should see:

```
ExecutionScheduler ready | interval=60s candidate_limit=20
ExecutionScheduler started | interval=60s
```

If you instead see `SCHEDULER_ENABLED=true but SCANNER_ENABLED=false —
... Not starting.`, set `SCANNER_ENABLED=true` too.

**Read the scope boundary before relying on this in production**: the
Scheduler's `PortfolioState` starts empty every time the process
starts and is built up only from its own executions this run — it does
not yet know about positions opened before it started, by the legacy
single-symbol loop, or manually on the exchange. See
`docs/architecture.md` §24 and `PATCH_NOTES.md`'s "Scope boundary"
section for the full explanation. This is real, documented follow-up
work, not a hidden gap — treat the Scheduler as additive/experimental
until reconciliation-fed state construction lands.

## If you want to use `PortfolioSignalProvider` or `ExecutionScheduler`
directly (outside main.py's bootstrap)

```python
from data.binance_provider import BinanceDataProvider
from execution.execution_orchestrator import ExecutionOrchestrator
from execution.execution_factory import build_execution_engine
from execution.execution_scheduler import ExecutionScheduler
from execution.portfolio_signal_provider import PortfolioSignalProvider
from portfolio.portfolio_manager import PortfolioManager
from ranking.opportunity_ranker import OpportunityRanker
from risk.risk_engine import RiskEngine
# ... plus a MarketScanner and a journal for RiskEngine — see main.py's
# build_system() for the exact construction this all mirrors.

data_provider = BinanceDataProvider()
signal_provider = PortfolioSignalProvider(data_provider=data_provider)
portfolio_manager = PortfolioManager()
orchestrator = ExecutionOrchestrator(
    execution_engine=build_execution_engine(data_provider=data_provider),
    portfolio_manager=portfolio_manager,
    signal_provider=signal_provider,
)
scheduler = ExecutionScheduler(
    opportunity_ranker=OpportunityRanker(market_scanner),
    portfolio_manager=portfolio_manager,
    risk_engine=risk_engine,
    execution_orchestrator=orchestrator,
    data_provider=data_provider,
)
scheduler.start()   # or scheduler.run_once() for a single synchronous cycle
```

`run_once()` is public specifically so it can be driven synchronously
(e.g. from a script, a test, or a manual "run one cycle now" button)
without touching threading at all.

## Data fetching: new capability, not a new requirement

`BinanceDataProvider.get_market_data_for(symbol)` reuses the SAME
`market_client`/circuit breaker your existing single `BinanceDataProvider`
instance already has — it does not open a second connection or need
separate credentials. If you're calling it directly for a symbol not in
`settings.symbol_list`, it will still work (Binance's API takes the
symbol per-request, not per-client) but won't be pre-warmed the way
`ExecutionCoordinator.initialize()` pre-warms leverage/margin for
`settings.symbol_list` at boot.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `SCHEDULER_ENABLED` | `false` | Turns the Execution Scheduler on. Requires `SCANNER_ENABLED=true`. |
| `SCHEDULER_INTERVAL_SECONDS` | `60` | Seconds between scheduler cycles. |
| `SCHEDULER_CANDIDATE_LIMIT` | `20` | Max candidates considered per cycle (separate from `RANKER_TOP_N`, which controls what the ranker persists/logs). |

## Database

No schema change. Nothing in this phase persists anything new.

## What is explicitly NOT part of this migration

- No reconciliation-fed `PortfolioState` (see scope boundary above).
- No execution-outcome persistence.
- No dashboard panel for the Scheduler or the existing
  `/api/execution/*` endpoints.
- No changes to `RiskEngine`, `CapitalManager`, `PortfolioManager`,
  `SectorEngine`, `ExecutionOrchestrator`, `ExecutionCoordinator`, or
  any Phase 2A-2E dataclass — every one of these is called exactly as
  already built and tested.

## Rollback (code)

This entire phase lives in two new files
(`execution/portfolio_signal_provider.py`,
`execution/execution_scheduler.py`) plus additive-only edits to three
existing ones (`data/binance_provider.py`: 7 methods gained an optional
parameter + one new method appended; `intelligence/market_context_builder.py`:
one method gained an optional parameter; `config/settings.py`: three
new fields appended) and one new guarded block in `main.py` (fully
inert unless `SCHEDULER_ENABLED=true`). Reverting the single commit on
`feature/execution-scheduler-multi-symbol-signals` — or simply not
merging the branch, or leaving `SCHEDULER_ENABLED=false` — fully
removes/disables it with zero impact on any earlier phase's
functionality, since nothing they already shipped was modified.
