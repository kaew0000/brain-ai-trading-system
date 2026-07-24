# PATCH NOTES — V16 Phase 4B Step 2: Execution Attribution + Portfolio Integration

Branch: `feature/ensemble-learning-4b-step2`
Base: `main` (post Phase 4B proper merge, PR #11, 1556 passing)

## Summary

Wires `execution/execution_orchestrator.py` to the journal on both open
and close for the V16 multi-symbol path — the gap §27/§28 both flagged
as "still open" and "the single biggest gap standing between Phase 4B
and it actually mattering for V16's primary multi-symbol path." Adds a
reusable `record_trade_outcome()` API (`journal/trade_attribution.py`)
so callers never touch SQLite directly, and makes
`PortfolioManager.notify_position_closed()` the one place any current
or future closing path persists a completed trade's attribution.

## Discovery — read before writing any code

1. **Multi-symbol trades have no agent votes to attribute.**
   `execution/portfolio_signal_provider.py` never runs
   `agents/ceo_agent.py`'s CEOAgent — per-agent attribution is only
   real for the legacy single-symbol loop. `get_trade_attribution()`
   returns an honestly empty `agent_participation: []` for V16
   multi-symbol trades rather than fabricating votes.
2. **Only replacement-triggered closes exist today** for the
   multi-symbol path — no natural SL/TP close monitor exists anywhere.
   This phase wires the real path that exists.
3. **Paper mode (the default) has no `close_position()` at all** —
   confirmed by reading `paper/paper_execution.py`. Close-side
   attribution needs testnet/live mode to observe end-to-end.
4. **Fees aren't computable anywhere in this codebase today** —
   Binance commission needs a separate API call nothing here makes.
   The field exists on the API for a future caller; every current call
   site passes `fees=None` honestly. Slippage, by contrast, IS wired
   for real (fill price vs. requested price, direction-adjusted).

## New module

| File | Purpose |
|---|---|
| `journal/trade_attribution.py` | `record_trade_outcome(journal, trade_id, **fields)` — Task 5's reusable API, every field optional, covers open- and close-side calls with one function. `agent_attribution_from_ceo_decision(ceo_decision)` — Task 4's per-agent extraction using the real `CEOAgent.WEIGHTS` keys plus a `"ceo"` aggregate entry. |

## Changes to existing modules (all additive)

| File | Change |
|---|---|
| `journal/journal_v2.py` | +`save_execution_attribution()` (merges into `trades.extra_data`, no schema migration), +`get_trade_attribution()` (Task 1+4 combined read), +`get_ensemble_learning_dataset()` (Task 6/7 clean dataset export). |
| `portfolio/portfolio_models.py` | `PortfolioPosition` +`trade_id: int \| None = None`. |
| `execution/execution_orchestrator.py` | +optional `journal=None`. Open success: persists signal+trade+attribution, threads `trade_id` onto the position. Close success (replacement path): computes exit/pnl/result honestly, hands to `notify_position_closed()`. |
| `portfolio/portfolio_manager.py` | +optional `journal=None`. `notify_position_closed()` +10 new optional keyword-only params — every existing call site unchanged. Now the single place close-side attribution is persisted. |
| `main.py` | Scheduler bootstrap now passes `journal=journal_v2` into both `PortfolioManager(...)` and `ExecutionOrchestrator(...)` — without this the wiring above would exist but never activate. |

Neither `agents/ceo_agent.py`, `execution/portfolio_signal_provider.py`,
nor `execution/strategy.py` were modified.

## Known limitations (documented, not hidden)

- Multi-symbol trades' `agent_participation` is genuinely `[]` today —
  the agent layer doesn't run on that path (see "Discovery" #1).
- Natural SL/TP closes aren't detected for multi-symbol positions
  (see "Discovery" #2) — only replacement closes are wired.
- `fees` is always `None` (see "Discovery" #4).
- No weight-learning logic added — `get_ensemble_learning_dataset()`
  only reads/shapes existing data, groundwork for a future Phase 4C,
  not a replacement for §28's existing win-rate blend.

## Testing

```
pytest tests/ -q   → 1600 passed, 0 failed  (1556 baseline + 44 new)
ruff check .        → clean
```

44 new tests: `tests/test_execution_attribution.py` (27),
`tests/test_execution_orchestrator.py` (+11), `tests/test_portfolio_manager.py`
(+6). 3 pre-existing tests needed their `FakePortfolioManager` test
double updated to accept the new optional kwargs (not a behavior
change — the fake's signature needed to keep up with the real one).
