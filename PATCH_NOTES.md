# PATCH NOTES — V16 Phase 4B Step 3B: CEO Decision Context + Multi-Symbol Signal Integration

Branch: `feature/phase4b-step3b-ceo-context`
Base: `main` (post Phase 4B Step 3A merge, PR #13, 1626 passing)

## Summary

Builds the missing bridge between the multi-symbol signal pipeline
(`PortfolioSignalProvider`) and `CEOAgent` — reusing the existing
pipeline's already-computed `market_context`/`confidence_result`
instead of recalculating market analysis. No execution, journal,
portfolio-allocation, or trade-attribution behavior changes; this phase
prepares integration only.

## Discovery — read before writing any code

1. `CEOAgent.decide()` already takes a plain `market_context` dict and
   runs its 6 sub-agents against it directly — none of them call
   MarketContextBuilder/ConfidenceEngine/RegimeEngine/SMCEngine/
   VolumeEngine themselves. "No duplicate computation" was only ever at
   risk from new glue code between `PortfolioSignalProvider` and
   `CEOAgent`, which is exactly what Part B's `get_signal_with_context()`
   removes the risk from.
2. Step 3A's per-symbol HMM capability (`RegimeEngine.classify(df, symbol=)`)
   is NOT yet wired into `PortfolioSignalProvider` — that phase's own
   comment says wiring a real caller was explicitly out of scope for
   it. `PortfolioSignalProvider` still calls `classify(ohlcv["h1"])`
   with no `symbol=`, so cross-symbol HMM contamination — the exact
   issue Step 3A exists to fix — is still live on the multi-symbol path
   today. **Not fixed in this phase either** — would be an execution-
   behavior change, explicitly out of scope here.
3. `TraderAgent` is registered but isn't a `CEOAgent.WEIGHTS` key —
   pre-existing, unrelated, noted only for the record while confirming
   "preserve existing vote logic" actually holds.
4. Sub-agents hold small amounts of per-instance state between calls
   (`RegimeAnalyst._prev_regime`, `BaseAgent._memory`/`_last`). Fine for
   one CEOAgent per symbol (today). A future phase reusing one shared
   CEOAgent across many symbols in a loop needs a decision here first —
   not addressed by this phase's adapter, which doesn't itself create
   that sharing pattern.

## New modules

| File | Purpose |
|---|---|
| `agents/decision_context.py` | Part A. `CEODecisionContext` — frozen dataclass (symbol, market_context, confidence_result, portfolio_state, existing_positions, risk_snapshot). Last three: plumbing for a future phase, not consumed here. |
| `agents/multi_symbol_adapter.py` | Part D. `MultiSymbolCEOAdapter(signal_provider, ceo_agent).decide(symbol)` — the full bridge, ends at `CEODecision`. Imports nothing from execution/, portfolio/portfolio_manager.py, or journal/. |

## Changes to existing modules (all additive)

| File | Change |
|---|---|
| `execution/portfolio_signal_provider.py` | Part B. `+SignalWithContext`, `+get_signal_with_context()`. `_compute_signal` replaced by `_compute_signal_with_context`, shared by both public methods — ONE computation path. `get_signal()`'s behavior is unchanged (12/12 pre-existing tests pass unmodified). |
| `agents/ceo_agent.py` | Part C. `+decide_from_context(context)` — thin wrapper calling the existing `decide()` unchanged. No vote/score/weight/confidence logic touched. |
| `agents/__init__.py` | `+CEODecisionContext`, `+MultiSymbolCEOAdapter` exports. |

`execution/execution_orchestrator.py`, `portfolio/portfolio_manager.py`,
`execution/trade_manager.py`, `journal/`, `journal/trade_attribution.py`,
`risk/risk_engine.py` — **not modified**.

## Compatibility analysis

`get_signal()`: same signature/return type/behavior. `CEOAgent.decide()`:
untouched. `CEODecision`/`AgentReport`: untouched. No settings/schema
changes, no new required dependencies for any existing caller.

## Testing

```
pytest tests/ -q   → 1652 passed, 0 failed  (1626 baseline + 26 new)
ruff check .        → clean
```

26 new tests in `tests/test_multi_symbol_ceo_integration.py`: context
construction/immutability, `get_signal_with_context()` parity +
no-duplicate-computation, `decide_from_context()` regression parity,
adapter single/multi-symbol behavior + error paths, full-pipeline
duplicate-computation spies (BTCUSDT/ETHUSDT, each engine called
exactly once per symbol).

## Benchmark

`MultiSymbolCEOAdapter.decide()` timed over N symbols (warm-up run
first, excluding one-time HMM fit cost):

```
n= 5   per_symbol= 93.2ms
n=10   per_symbol= 91.8ms
n=20   per_symbol= 97.4ms
n=40   per_symbol=100.7ms
```

Flat per-symbol cost from n=5 to n=40 — linear total complexity, no
quadratic blowup. The adapter itself adds O(1) work per symbol beyond
`get_signal_with_context()` (one dict construction, one
`decide_from_context()` call).

## Scope boundary

CEOAgent is still NOT invoked anywhere in the live V16 multi-symbol
path — `main.py`'s scheduler bootstrap still uses a bare
`PortfolioSignalProvider`. This phase built the bridge; wiring it in is
future work, per this phase's own "prepares integration only" brief.
Cross-symbol HMM contamination (Discovery #2) remains unfixed. No
Dynamic Weight Learning, journal, or attribution changes.
