# PATCH NOTES — V16 Phase 2B: Portfolio Manager Orchestrator

Branch: `feature/phase2b-portfolio-manager`
Base: `main` @ `e21dab0` (Phase 2A merged)

## Summary

Adds the orchestration layer Phase 2A's own docs (architecture.md §17/§18)
explicitly deferred: `PortfolioManager`, which wraps `CapitalManager.decide()`
(called unmodified, nothing about it changes) with sector exposure
enforcement, replacement logic, and cooldown/min-hold bookkeeping.
Decision-only, same boundary `CapitalManager` already drew for itself —
nothing in this phase places an order, calls `set_leverage`, or imports
`execution/`/`data/`. No REST API, WebSocket, dashboard, or scheduler
wiring, per this phase's own scope.

## New modules

| File | Purpose |
|---|---|
| `portfolio/portfolio_manager.py` | `PortfolioManager.decide()` — the orchestrator |
| `portfolio/sector_engine.py` | Sector lookup, exposure (capital- and notional-based), diversification score |
| `portfolio/portfolio_history.py` | Persists each decision cycle (mirrors `ranking_history.py`) |
| `config/sector_table.py` | Static symbol→sector table (13 sectors, ~110 symbols, Version 1) |

## Additive changes to existing files

| File | Change |
|---|---|
| `portfolio/portfolio_models.py` | + `ReplacementProposal`, `OrchestratedDecision` dataclasses. Nothing existing modified. |
| `config/settings.py` | + `PORTFOLIO_REPLACEMENT_THRESHOLD_PCT` (0.15), `PORTFOLIO_COOLDOWN_SECONDS` (3600), `PORTFOLIO_MIN_HOLD_SECONDS` (1800), `PORTFOLIO_HISTORY_RETENTION_HOURS` (168). |
| `database/schema_v13.sql` | + `portfolio_history` table + index, appended at EOF, `CREATE TABLE IF NOT EXISTS` (idempotent, safe on every existing DB). |
| `docs/architecture.md` | §18 replaced (was a "Next up" placeholder written in Phase 2A, now the real design writeup); new §19 "Next up". |
| `CHANGELOG.md`, `README.md` | New entry / package-list addition. |

**Nothing was removed or had its public signature changed.** `CapitalManager`,
`CorrelationEngine`, `PortfolioState`, and every existing dataclass in
`portfolio_models.py` are byte-for-byte unchanged.

## Design notes (see `docs/architecture.md` §18 for the full writeup)

- **Sector cap uses capital (margin), not leveraged notional.** The first
  implementation used notional and failed its own tests — at 5x leverage,
  one ordinary position's notional already exceeds a 50% balance-based cap.
  Fixed before this was ever committed; caught by the test suite, not left
  as a shipped bug. `SectorEngine.capital_by_sector()` (new) vs.
  `exposure_by_sector()` (notional, used for the *reported* diversification
  score, where leveraged market exposure is the right question) are
  deliberately two different methods answering two different questions.
- **Replacement logic reuses `CapitalManager`, never re-implements its
  eligibility/correlation/scoring rules.** Evaluates a capacity-blocked
  challenger by re-running `CapitalManager` itself with room for one extra
  slot, rather than a second, independently-maintained copy of the same
  logic.
- **`ReplacementProposal` is advisory only** — never merged into
  `selected`/`total_capital_allocated`. `PortfolioManager` still does not
  execute trades.

## Test results

```
pytest tests/ -q
1188 passed, 0 failed   (1082 baseline + 106 new)

ruff check . --exclude dashboard_src --exclude dashboard
All checks passed!
```

New test files: `tests/test_sector_engine.py` (60), `tests/test_portfolio_manager.py`
(36), `tests/test_portfolio_history.py` (10).

## Known limitations / follow-up (not urgent, documented not hidden)

- Sector-cap rejections don't redistribute freed capital to remaining
  candidates this cycle (same simplification Phase 2A already accepted for
  `max_symbol_pct`).
- At most one replacement proposed per `decide()` call.
- Cooldown/min-hold are registered at proposal time, not confirmed-execution
  time — there's no feedback loop yet telling `PortfolioManager` whether a
  proposal was actually acted on. `notify_position_closed()` is the hook a
  future execution-wiring phase should call for real closures.

See `MIGRATION.md` for upgrade/rollback notes.
