# PATCH NOTES — V16 Phase 4B Proper: Dynamic Per-Agent Weighting

Base: `main` + Phase 4B Step 1 (per-agent outcome attribution, this same
session — see `docs/architecture.md §27`)

## Summary

architecture.md §27 "Next up" scoped this as: "actually using
`get_agent_performance()` to adjust `CEOAgent.WEIGHTS`". `CEOAgent.decide()`
can now blend each agent's static weight toward its measured win-rate —
gated **off by default** via `DYNAMIC_AGENT_WEIGHTS_ENABLED`, so nothing
changes for any existing deployment unless explicitly opted in.

## Changes to existing modules

| File | Change |
|---|---|
| `config/settings.py` | 4 new flags, all inert by default: `DYNAMIC_AGENT_WEIGHTS_ENABLED` (bool, `False`), `DYNAMIC_WEIGHT_MIN_SAMPLES` (int, `20`), `DYNAMIC_WEIGHT_BLEND` (float, `0.3`), `DYNAMIC_WEIGHT_REFRESH_SECONDS` (int, `300`). |
| `agents/ceo_agent.py` | `CEOAgent.__init__` gains optional `journal=None`. New `_get_agent_performance_cached()` (TTL-cached `journal.get_agent_performance()`) and `_effective_weights(reports)` (blends toward `win_rate`, floor-gated by sample count, always renormalizes to sum 1.0, falls back to static `WEIGHTS` on any error). `decide()` now uses the effective weights consistently across the vote, `agreement_score`, and `score_breakdown`. `CEODecision` gains `weights_used: dict`. |
| `agents/__init__.py` | `CEOAgent(...)` now also receives `journal=journal` (already threaded through `build_agent_layer()` for other agents). |
| `docs/architecture.md` | +§28. |
| `CLAUDE.md` | Phase 4B proper moved to Completed; Priority 2 rewritten — its only remaining open item is the execution_orchestrator.py journal gap. |

No changes to `journal/journal_v2.py`, `execution/execution_orchestrator.py`,
`decision/confidence_engine.py`, `main.py`, or any schema in this delivery.

## Safety properties (why this is safe to ship even before enabling it)

- **Off by default.** `DYNAMIC_AGENT_WEIGHTS_ENABLED=False` → `_effective_weights()`
  returns `self.WEIGHTS` unchanged, and doesn't even call the journal.
- **No journal configured** (`journal=None`, still the default anywhere
  `CEOAgent(...)` is constructed without the kwarg, e.g. existing tests) →
  same fallback.
- **Any exception** fetching performance (journal down, bad data, etc.) →
  same fallback, logged as a warning, decision cycle continues normally.
- **Per-agent sample floor** — an agent with fewer than
  `DYNAMIC_WEIGHT_MIN_SAMPLES` closed, direction-matching trades keeps its
  static weight untouched, so a brand-new or rarely-triggered agent is
  never blended off a handful of noisy trades.
- **Bounded multiplier** — win-rate maps to a `[0.5, 1.5]` multiplier
  scaled by `DYNAMIC_WEIGHT_BLEND`, so no agent can be zeroed out or made
  to dominate the vote outright, even at 0% or 100% measured win-rate.
- **Always renormalized to sum to 1.0** — preserves the existing
  `long_score`/`short_score >= 40` action threshold's meaning regardless
  of whether blending is active.

## Known limitation (carried over from Phase 4B Step 1, still applies)

Only reflects trades from the legacy single-symbol `main.py` pipeline —
`execution/execution_orchestrator.py` (V16 multi-symbol path) still
doesn't write to the journal at all, so enabling dynamic weighting today
would only ever be informed by single-symbol history. See
`docs/architecture.md §28` "Next up".

## Testing

```
pytest tests/ -q   → 1556 passed, 0 failed  (1546 after §27 + 10 new)
ruff check .        → clean
```

10 new tests in `tests/test_dynamic_agent_weights.py`: disabled-by-default
(journal never even queried), no-journal fallback, exception-during-fetch
fallback, below-sample-floor fallback for that agent, weights always sum
to 1.0, win-rate blending widens the weight ratio by the expected factor,
zero-win-rate agent never zeroed out, TTL cache avoids repeated journal
queries, `weights_used` present in `to_dict()`.
