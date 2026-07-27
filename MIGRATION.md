# MIGRATION — V16 Phase 4B Step 3C: Live CEO Agent Integration into Multi-Symbol Decision Pipeline

## Do you need to do anything?

**No code changes required for existing callers.** `CEO_MULTI_SYMBOL_ENABLED`
defaults `False` — a fresh checkout behaves identically to before this
phase. `MultiSymbolCEOAdapter.decide()` produces the same output as
before (now delegates internally to the new `decide_with_signal()`, but
that's an implementation detail — verified byte-identical for identical
input). `RegimeEngine.classify()`'s `symbol=` parameter already
defaulted to `None`.

## If you want to turn CEO gating on

It's off by default. To enable it:

```bash
# .env
SCHEDULER_ENABLED=true          # required (Phase 2F) — CEO gating only
SCANNER_ENABLED=true            #   applies inside the Execution Scheduler
CEO_MULTI_SYMBOL_ENABLED=true
```

Restart the bot. On startup, if wiring succeeds you'll see:

```
CEOGatedSignalProvider ready | enabled_override=None
ExecutionScheduler: CEO Agent gating ENABLED
```

If instead you see:

```
CEO_MULTI_SYMBOL_ENABLED=true but strategy 'X' has no get_signal_with_context()
— CEO gating not applied for this strategy.
```

your `STRATEGY_NAME` (see `config/settings.py`) is set to something
other than the default `PortfolioSignalProvider`-based strategy — only
strategies that expose `get_signal_with_context()` can be CEO-gated.
The bot keeps running normally with CEO gating simply not applied.

**Read `docs/architecture.md` §31 before relying on this in
production** — specifically, CEO can only confirm or veto a trade the
existing pipeline already priced; it never independently invents one.
A `LONG` CEODecision against a `SHORT`-priced signal (or no priced
signal at all) always results in no trade, not a CEO-directed one.

## Journal / dashboard

Once enabled, every CEO ruling (confirmed, vetoed, or blocked) is
recorded via the existing `journal_v2.save_agent_decision()` — no new
table, no schema change. Query it directly:

```bash
curl http://localhost:8000/api/ceo-decisions
curl http://localhost:8000/api/ceo-decisions?symbol=BTCUSDT&limit=20
```

Empty `"data": []` is the expected, correct response until either CEO
gating is enabled or the scheduler has actually run a cycle — not an
error.

## If you want to use `CEOGatedSignalProvider` or `CEOAgentSymbolCache`
directly (outside main.py's bootstrap)

```python
from execution.portfolio_signal_provider import PortfolioSignalProvider
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher

signal_provider = PortfolioSignalProvider(data_provider=data_provider)  # or your existing instance
ceo_agent_cache = CEOAgentSymbolCache(risk_engine=risk_engine, journal=journal_v2)
dispatcher = MultiSymbolCEODispatcher(signal_provider=signal_provider, ceo_agent_cache=ceo_agent_cache)
gated_provider = CEOGatedSignalProvider(
    signal_provider=signal_provider,
    ceo_adapter=dispatcher,
    journal=journal_v2,        # optional — omit to skip journaling
    enabled=True,               # omit to read settings.CEO_MULTI_SYMBOL_ENABLED live instead
)

orchestrator = ExecutionOrchestrator(
    execution_engine=trade_manager,
    portfolio_manager=portfolio_manager,
    signal_provider=gated_provider,   # exactly where a bare PortfolioSignalProvider would go
)
```

`ExecutionOrchestrator` needs no changes and no awareness that
`gated_provider` wraps a CEO pipeline underneath — that's the whole
point of Part A's design.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `CEO_MULTI_SYMBOL_ENABLED` | `false` | Gates `ExecutionScheduler`'s signal provider through `CEOAgent`. Requires the active strategy to expose `get_signal_with_context()` (the default). |

## Database

No schema change. `journal_v2`'s existing `agent_decisions` table
(Phase 4B Step 1) already had everything this phase needed.

## What is explicitly NOT part of this migration

- No trade-level agent attribution wiring for CEO-confirmed executions
  (see PATCH_NOTES.md's "Known limitations" — `ExecutionOrchestrator`
  changes were out of scope for this phase).
- No dashboard UI panel for `/api/ceo-decisions`.
- No changes to `PortfolioManager`, `TradeManager`, `TradeJournalV2`,
  `ExecutionOrchestrator`, `ExecutionCoordinator`, `RiskEngine`, or
  `CEOAgent.decide()`'s own behavior.

## Rollback (code)

This entire phase lives in two new files
(`execution/ceo_gated_signal_provider.py`, `agents/ceo_symbol_cache.py`)
plus additive-only edits to four existing ones
(`agents/multi_symbol_adapter.py`: one new method appended, `decide()`
refactored to delegate to it with identical output;
`execution/portfolio_signal_provider.py`: one call site gained a
`symbol=` argument; `config/settings.py`: one new field;
`api/app.py`: one new endpoint) and one new guarded block in `main.py`
(fully inert unless `CEO_MULTI_SYMBOL_ENABLED=true` AND the active
strategy supports it). Reverting the single commit on
`feature/phase4b-step3c-live-ceo-integration` — or simply leaving
`CEO_MULTI_SYMBOL_ENABLED=false` — fully removes/disables it with zero
impact on any earlier phase's functionality.
