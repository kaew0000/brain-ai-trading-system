# MIGRATION — V16 Phase 2B: Portfolio Manager Orchestrator

## Do you need to do anything?

**No code changes required for existing callers.** Nothing in Phase 2A
(`CapitalManager`, `CorrelationEngine`, `PortfolioState`, existing
`portfolio_models.py` dataclasses) changed signature, behavior, or default.
If you're not yet calling `CapitalManager.decide()` directly from anywhere
outside tests, there is nothing to migrate — this phase is purely additive.

## If you want to start using `PortfolioManager`

Replace a direct `CapitalManager.decide()` call with `PortfolioManager.decide()`
— same four arguments, same `PortfolioState`/`RiskEngine` contract:

```python
# Before (Phase 2A)
from portfolio.capital_manager import CapitalManager
cm = CapitalManager.from_settings()
decision = cm.decide(candidates, risk_engine, state, balance)
# decision: PortfolioDecision

# After (Phase 2B) — additive, CapitalManager still works standalone
from portfolio.portfolio_manager import PortfolioManager
pm = PortfolioManager.from_settings()
decision = pm.decide(candidates, risk_engine, state, balance)
# decision: OrchestratedDecision — superset of PortfolioDecision's fields
# (.selected, .rejected, .blocked, .block_reason, .total_capital_allocated,
#  .total_risk_allocated, .explanation all present with the same meaning),
# plus .replacements, .sector_exposure, .diversification_score, .portfolio_score
```

`OrchestratedDecision.selected` is `CapitalManager`'s own selections after
additional sector-cap filtering — it can be a *subset* of what calling
`CapitalManager.decide()` directly would have returned (a candidate that
passed every 2A gate can still be rejected here for `sector_exposure_exceeded`).
Nothing else about `.selected`'s contents changes.

## Database

`database/schema_v13.sql` gained one new table, `portfolio_history`, via
`CREATE TABLE IF NOT EXISTS` — applied automatically the next time any
process calls `get_connection()`/`ManagedConn()`/`ReadConn()` against an
existing database file; no manual migration step, no data touched in any
existing table. Safe to deploy without downtime. If you never call
`PortfolioManager.decide()`, this table simply stays empty.

**Rollback:** if you need to revert this phase, `DROP TABLE IF EXISTS
portfolio_history;` is safe and reverses the only schema change — no
existing table's structure or data was touched.

## Configuration

Four new settings, all with defaults matching what's described in
`docs/architecture.md` §18 — no `.env`/config change required to deploy:

| Setting | Default | Meaning |
|---|---|---|
| `PORTFOLIO_REPLACEMENT_THRESHOLD_PCT` | `0.15` | Challenger must beat weakest held position's score by >15% to trigger a replacement proposal |
| `PORTFOLIO_COOLDOWN_SECONDS` | `3600` | How long a replaced/closed symbol is ineligible for new selection |
| `PORTFOLIO_MIN_HOLD_SECONDS` | `1800` | How long a freshly-replaced-in symbol is protected from being proposed as an outgoing side |
| `PORTFOLIO_HISTORY_RETENTION_HOURS` | `168` | `portfolio_history` row retention (mirrors `RANKER_HISTORY_RETENTION_HOURS`) |

## What is explicitly NOT part of this migration

- No execution wiring. `PortfolioManager.decide()` returns decisions; nothing
  calls `ExecutionCoordinator`, places an order, or reads live exchange state.
- No REST/WebSocket/dashboard exposure of the new decision data.
- No changes to `RiskEngine`'s account-level (not yet per-symbol) circuit
  breaker.

## Rollback (code)

This entire phase lives in four new files plus additive-only edits to four
existing ones (see `PATCH_NOTES.md`'s table). Reverting the single commit
on `feature/phase2b-portfolio-manager` — or simply not merging the branch —
fully removes it with zero impact on Phase 2A functionality, since nothing
Phase 2A already shipped was modified.
