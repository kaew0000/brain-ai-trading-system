# MIGRATION — V16 Phase 4B Proper: Dynamic Per-Agent Weighting

## Do you need to do anything?

**No.** `DYNAMIC_AGENT_WEIGHTS_ENABLED` defaults to `False` — `CEOAgent`
behaves exactly as it did before this phase until you explicitly opt in.
No schema, no config changes required to keep current behavior.

## How to enable it

Set in your `.env` / environment:

```
DYNAMIC_AGENT_WEIGHTS_ENABLED=true
```

Optional tuning (all have sensible defaults, shown below):

```
DYNAMIC_WEIGHT_MIN_SAMPLES=20        # min closed trades before an agent's win-rate is trusted
DYNAMIC_WEIGHT_BLEND=0.3             # 0=fully static, 1=fully performance-driven
DYNAMIC_WEIGHT_REFRESH_SECONDS=300   # how often the journal is re-queried
```

**Before enabling in production**, be aware: `get_agent_performance()`
(Phase 4B Step 1) only has data from trades taken through the legacy
single-symbol `main.py` pipeline. If your deployment trades primarily
through `execution/execution_orchestrator.py` (V16 multi-symbol path),
every agent will be below `DYNAMIC_WEIGHT_MIN_SAMPLES` indefinitely and
weights will stay static in practice — enabling the flag is harmless in
that case, just not yet useful. See `docs/architecture.md §28` "Next up".

## Behavior change once enabled

- `CEOAgent.decide()`'s weighted vote, `agreement_score`, and
  `score_breakdown` now use blended weights instead of the fixed
  `CEOAgent.WEIGHTS` dict, once each agent clears the sample floor.
- `CEODecision.to_dict()` gains a new key: `weights_used` — the exact
  weights (static or blended) used for that cycle. Purely additive; any
  code reading specific keys out of the dict is unaffected. Code doing an
  exact `set(dec.to_dict().keys()) == {...}` comparison would need
  updating — none exists in the current test suite.
- One extra read query (`journal.get_agent_performance()`) at most once
  every `DYNAMIC_WEIGHT_REFRESH_SECONDS` (default 5 min) per `CEOAgent`
  instance, only when enabled.

## Rollback

Set `DYNAMIC_AGENT_WEIGHTS_ENABLED=false` (or unset it) — no data
migration needed either direction, since no schema changed.
