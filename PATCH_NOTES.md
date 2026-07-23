# PATCH NOTES — V16 Phase 4A: Ensemble Decision Engine (ConfidenceEngine Fusion)

Branch: `feature/ensemble-decision-engine-4a`
Base: `main` (post Phase 3A merge, "feat(execution): Phase 3A Strategy
Plugin System", 1533 passing)

## Summary

`agents/ceo_agent.py`'s `CEOAgent.decide()` previously took two separate
code paths: when a `confidence_result` was passed in, it **overrode**
the action/direction/confidence outright, and the agent layer's own
votes (`smc`, `futures`, `regime`, `risk`, `journal`) only appeared in
the `reasons` text — they never influenced the actual decision. Since
`main.py`'s live pipeline and `execution/portfolio_signal_provider.py`
both always pass a `confidence_result`, the "ensemble" vote was
effectively dead code in production outside the risk veto.

This phase fuses `ConfidenceEngine`'s opinion into the same weighted vote
as every other agent instead of letting it override the agent layer, and
adds an `agreement_score` that damps confidence when the agent layer is
split on direction. Per §25's "Next up" and CLAUDE.md's Priority 2, this
extends `agents/ceo_agent.py` rather than building a new module.

**Scoped in two sub-phases before writing code.** The original ask was
just "Ensemble Decision Engine." Reading `agents/ceo_agent.py`,
`decision/confidence_engine.py`, `ranking/confidence_fusion.py`, and
`journal/journal_v2.py` first split the work into: (A) fuse
ConfidenceEngine + add disagreement scoring — no new data dependency,
touches one file — and (B) weight agents by their real historical
win-rate — blocked on per-agent outcome attribution that doesn't exist
yet in the journal. Building (B) without (A)'s data would have been a
static placeholder with no real signal behind it. This phase is (A)
only; (B) is scoped as a follow-up in `docs/architecture.md` §26 "Next
up".

## Changes to existing modules

| File | Change |
|---|---|
| `agents/ceo_agent.py` | `WEIGHTS` gains `confidence_engine: 0.15`, rebalanced from `{smc:.30 futures:.25 regime:.20 risk:.15 journal:.10}` to `{smc:.25 futures:.20 regime:.15 risk:.15 journal:.10 confidence_engine:.15}`. `confidence_result` is now wrapped as an `AgentReport` and folded into the existing weighted vote loop instead of overriding it in a separate branch. New `agreement_score` field on `CEODecision` (weighted fraction of directional votes agreeing with the winning action), used to damp `confidence` when the agent layer disagrees. `score_breakdown` gains `journal` and `confidence_engine` keys (previously omitted). A ConfidenceEngine hard block (`blocked=True` / `action=="BLOCKED"`) still short-circuits to `BLOCKED` unconditionally, same precedence as the risk veto. |
| `docs/architecture.md` | +§26 (this phase). |
| `CLAUDE.md` | "Current Development Status" / "Current Priorities" updated — Phase 4A moved to Completed under Priority 2; Phase 4B recorded as the next scoped step. |

Neither `execution/strategy.py`, `execution/portfolio_signal_provider.py`,
`decision/confidence_engine.py`, nor `ranking/confidence_fusion.py` were
modified — this phase changes how `CEOAgent` consumes their output, not
the outputs themselves.

## Known limitation (documented, not hidden)

Confidence damping from `agreement_score` is applied once, using the
action/scores already computed from the undamped vote — it does not
re-run action selection after damping. A vote that just barely cleared
the 40-point action threshold can end up reported at a damped confidence
below 40 (e.g. 39.38 in the test suite). This is intentional: it reflects
"the agent layer is split, treat this as a weaker signal" rather than
flip-flopping the action itself based on its own after-the-fact damping.

## Testing

```
pytest tests/ -q   → 1539 passed, 0 failed  (1533 baseline + 6 new)
ruff check .        → clean
```

6 new tests in `tests/test_ceo_ensemble_fusion.py`, using hand-built
`FakeAgent` stubs (not `build_agent_layer`'s real engines) for
deterministic weighted-vote math: agent layer outvoting ConfidenceEngine,
agents and ConfidenceEngine agreeing, agreement-score + damping math
checked to 2 decimal places, unanimous vote has zero damping, hard-block
passthrough regardless of agent votes, and risk veto still winning over a
directional fused result.
