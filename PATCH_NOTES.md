# PATCH NOTES — V16 Phase 4B Step 3C: Live CEO Agent Integration into Multi-Symbol Decision Pipeline

Branch: `feature/phase4b-step3c-live-ceo-integration`
Base: `main` (post Phase 4B Step 3B merge, 1652 passing)

## Summary

Wires the already-built CEO pipeline (§27-30: `CEOAgent`,
`MultiSymbolCEOAdapter`, `CEODecisionContext`, `SignalWithContext`,
per-symbol HMM models) into `ExecutionScheduler`'s production signal
path for the first time. `CEOAgent` was fully built and tested but
never actually consulted for a live trading decision before this
phase — `agents/multi_symbol_adapter.py`'s own docstring explicitly
called this "deferred to a future phase." This is that phase.

## Two real corrections made to the requesting brief before writing any code

1. **No `REJECT` action exists.** The brief's decision-mapping table
   listed `REJECT` as a possible `CEOAgent` action. Reading
   `agents/ceo_agent.py`'s `decide()`/`decide_from_context()` directly
   confirms the only four possible actions are `LONG`, `SHORT`, `WAIT`,
   `BLOCKED`. Used `BLOCKED` for the brief's "cancel candidate" case.
2. **The per-symbol `RegimeEngine` capability existed but was never
   activated.** The brief said to "activate the Phase 4B Step 3A
   capability" as if it were a simple flip — checking
   `execution/portfolio_signal_provider.py` showed it never passed
   `symbol=` into `regime_engine.classify()` at all, despite
   `RegimeEngine.classify(df, symbol=None)` already supporting it. Real,
   verified one-line gap, not a done item.

## A risk the brief didn't mention, that had to be solved before any wiring made sense

`CEOAgent`'s six sub-agents hold per-instance state between calls —
`RegimeAnalyst._prev_regime`, every agent's `_memory`/`_last`. Sharing
one `CEOAgent` (and its sub-agents) across BTCUSDT/ETHUSDT/SOLUSDT in
a scheduler loop would silently corrupt regime-change detection and
signal continuity the moment a second symbol entered the loop.
`agents/multi_symbol_adapter.py`'s own module docstring had already
flagged and deferred this exact question. Solved with
`agents/ceo_symbol_cache.py` — one full agent layer per symbol via the
existing `build_agent_layer()` factory, cached the same way
`ExecutionCoordinator.get_manager()` caches per-symbol `TradeManager`.
Zero changes to `BaseAgent`, `RegimeAnalyst`, or any sub-agent class.

## New modules

| File | Purpose |
|---|---|
| `execution/ceo_gated_signal_provider.py` | `CEOGatedSignalProvider` + `map_ceo_decision_to_signal()` — Parts A/B/C/E. Drop-in `SignalProvider`, zero `ExecutionOrchestrator` changes. |
| `agents/ceo_symbol_cache.py` | `CEOAgentSymbolCache` + `MultiSymbolCEODispatcher` — the per-symbol state-isolation fix described above. |

## Changes to existing modules

| File | Change |
|---|---|
| `agents/multi_symbol_adapter.py` | `+decide_with_signal(symbol)` — same computation as the existing `decide()`, additionally returns the underlying priced `ExecutionSignal` so a caller needing both doesn't trigger a second `get_signal_with_context()` call (which would duplicate MarketContextBuilder/ConfidenceEngine/RegimeEngine computation). `decide()` now delegates to it; output unchanged for identical input (verified). |
| `execution/portfolio_signal_provider.py` | `regime_engine.classify()` now called with `symbol=symbol` — the Part D fix. |
| `api/app.py` | `+GET /api/ceo-decisions` (Part F) — reads `journal_v2.get_agent_decisions(agent="CEO_AGENT")`. Zero new persistence. |
| `config/settings.py` | `+CEO_MULTI_SYMBOL_ENABLED` (default `False`). |
| `main.py` | New guarded block after `signal_provider = build_strategy(...)`: if `CEO_MULTI_SYMBOL_ENABLED` and the selected strategy exposes `get_signal_with_context()`, wraps it in `CEOGatedSignalProvider`; otherwise logs and leaves it unwrapped (never crashes). Strategies without `get_signal_with_context()` (e.g. the legacy `smc_oi_regime` adapter) are explicitly not CEO-gateable — checked defensively via `hasattr()`, not assumed. |
| `docs/architecture.md` | New §31. §1-30 byte-for-byte untouched (diff-verified). |

**Nothing was removed or had its public signature changed.**
`PortfolioManager`, `TradeManager`, `TradeJournalV2`,
`ExecutionOrchestrator`, `ExecutionCoordinator`, `RiskEngine`, and
`CEOAgent.decide()`'s own behavior are all byte-for-byte unchanged —
matching the brief's explicit "DO NOT rewrite" constraints exactly.

## Decision mapping (Part B, centralized in one function)

| `CEODecision.action` | underlying priced signal | → execution decision |
|---|---|---|
| `BLOCKED` | any | `None` (hard veto) |
| `WAIT` | any | `None` (skip) |
| `LONG`/`SHORT` | `None` | `None` (nothing to confirm) |
| `LONG`/`SHORT` | agrees | the priced signal, unchanged |
| `LONG`/`SHORT` | disagrees | `None` (CEO vetoes) |

CEO can only confirm or veto an already-priced signal — `CEODecision`
carries no entry/stop-loss/take-profit of its own (confirmed by reading
the dataclass), so it structurally cannot invent an independent trade.

## Test results

```
pytest tests/ -q
1717 passed, 0 failed   (1652 baseline + 65 new)

ruff check .
All checks passed!   (two unused-import findings during development,
                       fixed before this count)
```

New test files: `test_ceo_gated_signal_provider.py` (26),
`test_ceo_symbol_cache.py` (11), `test_ceo_decisions_api.py` (9),
`test_phase4b_step3c_verification.py` (15, addressing every Part G
brief requirement individually). +4 in the existing
`test_multi_symbol_ceo_integration.py`.

Every Part G requirement verified with a dedicated, literal test:
- CEO disabled → byte-identical to the real `PortfolioSignalProvider`
  for every symbol tested, CEO pipeline never touched.
- CEO enabled → BTC/ETH/SOL get three distinct `CEOAgent` instances;
  state-leak directly disproven (mutate one, check the other).
- `MarketContextBuilder`/`ConfidenceEngine`/`RegimeEngine` each spied
  and confirmed called exactly once per symbol through the full gated
  path.
- HMM cache: BTC→ETH→BTC produces exactly 2 fitted models; repeat call
  reuses the same fitted model object.
- `BLOCKED`/`WAIT`/disagreement all proven to never produce a
  tradeable signal, even against a real, fully-priced `ExecutionSignal`.

## Benchmark

| n symbols | total | per-symbol | ratio to n=10 |
|---|---|---|---|
| 10  | 1.068s | 106.77ms | 1.00× |
| 25  | 2.654s | 106.16ms | 0.99× |
| 50  | 5.038s | 100.76ms | 0.94× |
| 100 | 10.138s | 101.38ms | 0.95× |

Per-symbol time stays flat across a 10× increase in symbol count —
linear scaling confirmed empirically. Cache size matched symbol count
exactly at every scale (zero duplicate `CEOAgent` construction).
Disabled-path benchmark at the same scales: ~101-113ms/symbol —
near-identical to enabled, confirming CEO gating's own overhead is
negligible against the already-dominant pipeline cost (not that CEO
gating does nothing).

## Compatibility report

- `CEO_MULTI_SYMBOL_ENABLED` defaults `False` — a fresh checkout's
  behavior is identical to before this phase existed.
- Every disabled-path test uses the REAL `PortfolioSignalProvider`
  (not a fake) and asserts byte-identical output.
- `MultiSymbolCEOAdapter.decide()`'s existing behavior is unchanged
  (now internally delegates to the new `decide_with_signal()`, verified
  to produce identical output for identical input).
- `RegimeEngine.classify()`'s `symbol=` parameter already defaulted to
  `None` before this phase; every existing caller omitting it is
  unaffected.
- No database schema change.
- No changes to any file under `dashboard_src/`/`dashboard/`.

## Known limitations / follow-up (documented, not hidden)

- **Trade-level agent attribution isn't wired for CEO-confirmed
  executions.** `journal/trade_attribution.py`'s
  `agent_attribution_from_ceo_decision()` (built for §29's execution
  attribution table) is not called anywhere by this phase — doing so
  would require `ExecutionOrchestrator` to know a `CEODecision`
  produced the signal it's executing, out of scope per the brief's own
  "DO NOT rewrite... Execution Engine" constraint. `CEOAgent`'s dynamic
  weighting (§28) still won't see real performance data from
  multi-symbol CEO-confirmed trades until this is built.
- No dashboard UI panel consumes the new `/api/ceo-decisions` endpoint
  yet — the endpoint exists, nothing renders it.
- Only strategies exposing `get_signal_with_context()` (the default
  `PortfolioSignalProvider`) can be CEO-gated — `STRATEGY_NAME="smc_oi_regime"`
  with `CEO_MULTI_SYMBOL_ENABLED=true` is logged and silently has no
  effect, by design.

See `MIGRATION.md` for upgrade/rollback notes.
