# PATCH NOTES — V16 Phase 4B Step 1: Per-Agent Outcome Attribution

Base: `main` (post Phase 4A merge, "feat(agents): Phase 4A Ensemble
Decision Engine", 1539 passing)

## Summary

architecture.md §26 "Next up" scoped Phase 4B's first step as adding
per-agent outcome attribution at trade close. Inspecting the code first
(per CLAUDE.md workflow) found the schema already supported this
(`agent_decisions.signal_id`, `trades.signal_id`, `save_trade(signal_id=)`
all already existed) — it was simply never wired up. It also found a
bigger, previously undocumented gap: `execution/execution_orchestrator.py`
(V16's multi-symbol path) never writes to the journal at all, so this
phase's attribution only covers the legacy single-symbol `main.py`
pipeline, which is the only one that currently records real trade
outcomes. See `docs/architecture.md §27` for the full discovery writeup.

## Changes to existing modules

| File | Change |
|---|---|
| `journal/journal_v2.py` | New `get_agent_performance(limit=500)` — joins `agent_decisions` to `trades` via the existing `signal_id` link. Counts a vote toward its agent only when that agent's vote direction matches the direction actually traded; dissenting agents are attributed neither the win nor the loss. Returns raw `{agent, total_trades, wins, losses, win_rate, total_pnl}` — not a weight recommendation. |
| `main.py` | `ceo_decision` now initialised to `None` before the agent-layer block (previously only defined inside a nested `if`, unsafe to reference afterward). `save_signal()`'s return value is now captured as `sig_id` (previously discarded). Each agent in `ceo_decision.agent_reports` is now persisted via `save_agent_decision(..., signal_id=sig_id)`. `save_trade(rec)` → `save_trade(rec, signal_id=sig_id)`. |
| `docs/architecture.md` | +§27 (this phase). |
| `CLAUDE.md` | Phase 4B Step 1 moved to Completed; Priority 2 updated with the execution_orchestrator.py journal gap noted as a separate, still-open item. |

`execution/execution_orchestrator.py`, `agents/ceo_agent.py`,
`decision/confidence_engine.py`, and `database/schema_v13.sql` were **not**
modified — no schema change was needed (see architecture.md §27
"Discovery"), and the execution layer was deliberately left untouched per
CLAUDE.md's "never modify Execution Layer blindly" rule.

## Known limitation (documented, not hidden)

Only the legacy single-symbol `main.py` pipeline is wired. Trades taken
through `execution/execution_orchestrator.py` (V16 multi-symbol path)
never call `save_trade`/`update_trade_result` at all today, so
`get_agent_performance()` cannot see them — it will only ever reflect
single-symbol history until that separate gap is closed. This was a
deliberate scope decision, not an oversight; see architecture.md §27
"Next up".

## Testing

```
pytest tests/ -q   → 1546 passed, 0 failed  (1539 baseline + 7 new)
ruff check .        → clean
```

7 new tests in `tests/test_agent_outcome_attribution.py`: agreeing agent
credited with a win, dissenting agent attributed nothing, win-rate across
multiple trades, open trades excluded, `signal_id=None` rows safely
ignored, and the `limit` parameter. Uses a `tmp_path` temp-file DB per
test (not `db_path=":memory:"`, which is a process-wide shared connection
in `database/db.py` — see the test file's fixture docstring).
