# MIGRATION — V16 Phase 4B Step 2: Execution Attribution + Portfolio Integration

## Do you need to do anything?

**No code changes required for existing callers.** Existing behavior
is byte-for-byte unaffected:

- `ExecutionOrchestrator(...)` and `PortfolioManager(...)` both gained
  a new optional `journal=None` constructor param. Any existing
  construction site that doesn't pass it behaves exactly as before —
  attribution recording is entirely inert.
- `PortfolioManager.notify_position_closed(symbol)` — the exact
  pre-existing call shape — still works unchanged; all 10 new keyword
  params default to `None`.
- No `.env` change is required to deploy this phase.
- No database schema migration — execution-level attribution fields
  are merged into the existing `trades.extra_data` JSON column.

## If you want attribution actually recording

It's already wired in `main.py`'s scheduler bootstrap
(`journal=journal_v2` passed into both `PortfolioManager` and
`ExecutionOrchestrator`) — nothing further to configure. Read it back
with:

```python
journal.get_trade_attribution(trade_id)          # one trade, full detail
journal.get_ensemble_learning_dataset(limit=1000)  # bulk, for a future Phase 4C
```

## What "attribution" means for a trade taken today

- **Every trade** (legacy single-symbol AND V16 multi-symbol) gets
  real execution facts once closed: execution_id, order_id, entry/exit
  price, pnl, latency_seconds, and slippage (when the exchange
  response includes a fill price).
- **`fees` is always `None`** — not computable from any data this
  codebase currently fetches. See PATCH_NOTES.md "Known limitations".
- **`agent_participation` is only ever non-empty for legacy
  single-symbol trades** — V16 multi-symbol trades honestly show `[]`
  because `execution/portfolio_signal_provider.py` doesn't run the
  agent layer. This is not a bug in this phase's code.
- **Close-side attribution only fires for replacement-triggered
  closes** on the multi-symbol path today — a stop-loss or take-profit
  hit isn't detected by any code path yet (pre-existing gap, not
  introduced or fixed by this phase).
- **In default paper mode, close-side attribution can't be observed
  end-to-end** — `paper/paper_execution.py` has no `close_position()`.
  Use testnet/live to see the full open→close cycle.

## Adding a new attribution caller (for future phases)

```python
from journal.trade_attribution import record_trade_outcome

record_trade_outcome(
    journal, trade_id,
    result="WIN", exit_price=69000.0, pnl=200.0,   # close-side, or omit for open-side only
    execution_id="...", order_id="...",
    fees=None, slippage=None, latency_seconds=0.5,  # all optional
    agent_attribution=None,                          # list[dict] if you have real votes
)
```

Never raises — any storage failure is logged and reflected in the
return value.

## Roadmap note

This closes the "only remaining open item" CLAUDE.md's Priority 2
described for the Ensemble Decision Engine pillar. What's newly open
instead (see `docs/architecture.md` §29 "Next up"): a natural SL/TP
close monitor, making `PortfolioSignalProvider` agent-aware, and
Phase 4C itself (consuming `get_ensemble_learning_dataset()` — not
started, per Task 7).
