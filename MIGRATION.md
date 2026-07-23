# MIGRATION — V16 Phase 4A: Ensemble Decision Engine (ConfidenceEngine Fusion)

## Do you need to do anything?

**No config changes required.** `main.py` calls `ceo.decide(pos_info,
confidence_result=decision)` exactly as before — the signature is
unchanged. What changed is internal: that `confidence_result` argument
now competes as a weighted vote instead of overriding the agent layer.

## Behavior change to be aware of

If you rely on `CEODecision.action`/`.confidence` (dashboard, logs,
`/api/agents` consumers, or your own scripts), note:

- **Before:** whenever a `confidence_result` was passed, `CEODecision`
  mirrored it exactly (same action/direction/confidence). The agent
  layer's votes were cosmetic (`reasons` text only).
- **Now:** `CEODecision` reflects the fused vote across all agents
  *including* `confidence_result` at 15% weight. If `smc`/`futures`/
  `regime`/`risk`/`journal` strongly disagree with `confidence_result`'s
  direction, the final action can now differ from what
  `confidence_result` alone said. A `blocked`/`"BLOCKED"`
  `confidence_result` is unaffected — that still passes straight through
  as a hard veto, same as before.
- **New field:** `CEODecision.agreement_score` (0-1, also in
  `to_dict()`/`/api` output). 1.0 = every directional agent agrees with
  the winning action. When it's below 1.0, `confidence` is damped
  (`0.5 + 0.5*agreement_score` multiplier) and a `reasons` entry lists
  which agents dissented.
- `score_breakdown` now includes `journal` and `confidence_engine` keys
  it didn't have before (both were computed internally pre-4A but never
  surfaced in the breakdown dict).

If any downstream code (dashboard widgets, alerting) assumed
`CEODecision` always exactly matches `confidence_result`'s
action/confidence, it should instead treat `CEODecision` as the
authoritative fused decision and `confidence_result`/`ConfidenceResult`
as one input among several — which is what the module docstring always
said the relationship was meant to be.

## Tuning the fusion weights

`agents/ceo_agent.py`'s `CEOAgent.WEIGHTS` (sums to 1.0):

```python
WEIGHTS = {
    "smc":               0.25,
    "futures":           0.20,
    "regime":            0.15,
    "risk":              0.15,
    "journal":           0.10,
    "confidence_engine": 0.15,
}
```

Adjusting `confidence_engine`'s weight changes how much ConfidenceEngine's
opinion counts relative to the agent layer's own analysis — 0 would
restore agent-layer-only decisions (never provide `confidence_result`
achieves the same thing), while pushing it toward 1.0 approaches the
pre-4A override behavior (but never fully reaches it, since a hard block
already always wins regardless of weight).

## What's next (Phase 4B, not in this phase)

Dynamic per-agent weighting from real win-rate is deliberately deferred —
see `docs/architecture.md` §26 "Next up" for why (it needs per-agent
outcome attribution in the journal first, which doesn't exist yet).
