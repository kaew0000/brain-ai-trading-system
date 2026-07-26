# MIGRATION — V16 Phase 4B Step 3B: CEO Decision Context + Multi-Symbol Signal Integration

## Do you need to do anything?

**No.** This phase adds new, unused-by-default capability. No existing
caller's behavior changes:

- `PortfolioSignalProvider.get_signal()` — identical signature, return
  type, and behavior to before this phase.
- `CEOAgent.decide()` — completely untouched.
- Nothing in `main.py` was changed. `ExecutionScheduler`'s
  `signal_provider` is still a bare `PortfolioSignalProvider` — CEOAgent
  is not yet part of the live multi-symbol trading loop.
- No `.env` / settings changes, no schema changes.

## What's new, if you want to use it

```python
from agents.multi_symbol_adapter import MultiSymbolCEOAdapter
from agents import build_agent_layer   # or construct CEOAgent directly

agent_layer = build_agent_layer(risk_engine=risk_engine, journal=journal_v2)
adapter = MultiSymbolCEOAdapter(signal_provider=portfolio_signal_provider,
                                 ceo_agent=agent_layer["ceo"])

decision = adapter.decide("ETHUSDT")   # -> CEODecision | None
```

`decide()` reuses `PortfolioSignalProvider`'s already-computed
`market_context`/`confidence_result` — it does not call
`MarketContextBuilder` or `ConfidenceEngine` a second time. Never
raises: returns `None` for a symbol with no usable signal this cycle,
or if anything in the pipeline fails.

## What this phase does NOT do

- Does not wire `MultiSymbolCEOAdapter` into `main.py`'s live
  `ExecutionScheduler` — that's the natural next phase.
- Does not fix cross-symbol HMM contamination on
  `PortfolioSignalProvider`'s `RegimeEngine` usage (Step 3A's per-symbol
  model capability exists; this caller still doesn't pass `symbol=`) —
  documented, not fixed, since that would be an execution-behavior
  change.
- Does not make `portfolio_state`/`existing_positions`/`risk_snapshot`
  on `CEODecisionContext` affect any decision — they're plumbing for a
  future phase.
- Does not touch execution, journal, portfolio-allocation, or
  trade-attribution logic in any way.

## Roadmap note

See `docs/architecture.md` §30 "Next up" for the precise remaining
gaps (live wiring, the HMM symbol-passing fix, per-symbol sub-agent
state, Phase 4C) — each scoped as its own future phase rather than
folded into this one.
