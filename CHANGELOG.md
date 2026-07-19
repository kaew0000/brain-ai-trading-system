# CHANGELOG

## [Unreleased] — V16 Phase 2C: Portfolio API

### Added
- **`api/portfolio_api.py`**: REST read layer over `portfolio_history`
  (`GET /api/portfolio/state`, `/decision/latest`, `/history`
  [limit/offset/symbol/sector], `/sectors`, `/allocations`). `APIRouter`
  included into the existing `api/app.py` singleton — not a second
  FastAPI app. No exchange calls, no `PortfolioManager`/`CapitalManager`
  calls; reads only what Phase 2B already persisted.
- **`api/portfolio_ws.py`**: `WS /ws/portfolio` — `decision`/`state`/
  `sectors`/`allocations`/`replacement_proposal` events, broadcast only
  when a new row appears in `portfolio_history` (deduped by row id),
  plus a 5s heartbeat. No polling loop of its own — hooks into
  `api/app.py`'s existing supervised `_broadcast_loop()` (same one
  `/ws/decision`, `/ws/agents`, `/ws/missions` already ride on).
- **`api/portfolio_serializers.py`**: pure row-dict → JSON shaping.
  Every payload carries an explicit `"source": "latest_persisted_decision"`
  / `"live": false` marker — this API reports the latest *persisted*
  decision cycle, never a live `PortfolioState` (none exists yet; see
  architecture.md §19's flagged-and-resolved conflict with §18's
  original "wait for the orchestrator" recommendation).
- Additive extensions to `portfolio/portfolio_history.py`:
  `query_decisions()` (paginated, optional symbol/sector filter) and
  `count_decisions()`. `get_latest_decisions()` itself unchanged —
  same signature, same one existing caller (its own tests).
- 92 new tests (`test_portfolio_serializers.py` 33,
  `test_portfolio_history_query.py` 14, `test_portfolio_api.py` 27,
  `test_portfolio_ws.py` 18). Full suite: 1188 → 1280 passed, 0 failed.
- `docs/architecture.md` §19 (design rationale, including the flagged
  architecture conflict and its resolution) and renumbered the previous
  §19 "Next up" to §20.

### Not included (explicitly out of scope for this phase)
- No scheduler/orchestrator calling `PortfolioManager.decide()` on a
  cadence — `portfolio_history` remains unpopulated in production until
  that future phase exists; every endpoint here already handles that
  honestly (200 + empty/null, never fabricated).
- No dashboard page consuming this API yet.
- No new auth role — `/api/portfolio/*` already covered by
  `_auth_middleware`'s default VIEWER-role path; `/ws/portfolio` uses
  the existing `enforce_ws_role()`.

---

## [Unreleased] — V16 Phase 2B: Portfolio Manager Orchestrator

### Added
- **`portfolio/portfolio_manager.py`** (`PortfolioManager.decide()`): the
  orchestrator §17/§18 deliberately left out. Wraps `CapitalManager.decide()`
  (called unmodified) with sector exposure enforcement, replacement logic
  (re-runs `CapitalManager` with one extra slot to find the best
  capacity-blocked challenger, no eligibility rules re-implemented), and
  cooldown/min-hold bookkeeping. Decision-only — does not execute trades,
  place orders, or call Binance; returns an `OrchestratedDecision`.
- **`portfolio/sector_engine.py`** + **`config/sector_table.py`**: symbol
  → sector classification (13 sectors, ~110 symbols, Version 1/hand-curated,
  same precedent as `config/correlation_table.py`), sector exposure
  (capital- and notional-based, kept separate — see architecture.md §18),
  and a Herfindahl-index diversification score.
- **`portfolio/portfolio_history.py`**: persists each `decide()` cycle to a
  new `portfolio_history` table (additive schema change, `CREATE TABLE IF
  NOT EXISTS`), mirroring `ranking/ranking_history.py`'s pattern exactly.
- Additive dataclasses in `portfolio/portfolio_models.py`:
  `ReplacementProposal`, `OrchestratedDecision`. Nothing existing changed.
- New `PORTFOLIO_REPLACEMENT_THRESHOLD_PCT` / `PORTFOLIO_COOLDOWN_SECONDS`
  / `PORTFOLIO_MIN_HOLD_SECONDS` / `PORTFOLIO_HISTORY_RETENTION_HOURS`
  settings (`config/settings.py`).
- 106 new tests (`test_sector_engine.py` 60, `test_portfolio_manager.py`
  36, `test_portfolio_history.py` 10). Full suite: 1082 → 1188 passed,
  0 failed.
- `docs/architecture.md` §18 (design rationale, replacing the previous
  "Next up" placeholder) and §19 (next up).

### Fixed (found during this phase's own test-writing, not a released bug)
- Sector-cap enforcement was first written comparing leveraged notional
  exposure against an unleveraged `balance`-based cap — failed its own
  tests immediately (one ordinary position at 5x leverage already
  exceeds a 50% cap measured that way). Fixed to compare capital
  (margin), matching how `max_symbol_pct` already works. Never merged
  in the broken form; see architecture.md §18 "Why capital, not
  notional" for the full explanation.

### Not included (see architecture.md §19)
- Real orchestrator wiring (reading live exchange/journal state into
  `PortfolioState`, driving the position state machine, calling
  `ExecutionCoordinator`, acting on a `ReplacementProposal`) —
  provisionally "Phase 2E". REST/WebSocket/Dashboard, `RiskEngine`
  per-symbol/aggregate exposure, real price-history correlation,
  sector-cap capital redistribution. All explicitly out of scope for
  this phase.

---

## [Unreleased] — V16 Phase 2A: Portfolio Intelligence Core

### Added
- **Portfolio Intelligence Core** (`portfolio/`): `portfolio_models.py`
  (dataclasses), `portfolio_state.py` (in-memory position/capital/risk
  tracker, no exchange calls), `correlation_engine.py` (tier-based
  correlation lookup against `config/correlation_table.py`),
  `capital_manager.py` (`CapitalManager.decide()` — the decision engine:
  ranked candidates + `RiskEngine` + `PortfolioState` → `PortfolioDecision`).
  Decision-only — does not execute trades, place orders, or call Binance.
  New `PORTFOLIO_*` settings (`config/settings.py`), all with defaults
  matching `PortfolioLimits`' own dataclass defaults.
- `RankedOpportunity.coverage` (`ranking/ranking_models.py`): additive
  field, default `1.0`, backward compatible. Previously computed by
  `confidence_fusion.fuse()` and discarded after use in a log string;
  now stored and used by `capital_manager.py` in place of the
  structurally-unavailable "AI Confidence" factor.
- 81 new tests (`test_portfolio_models.py`, `test_portfolio_state.py`,
  `test_correlation_engine.py`, `test_capital_manager.py`). Full suite:
  1001 → 1082 passed, 0 failed.
- `docs/architecture.md` §17 (design rationale) and §18 (next up).

### Not included (see architecture.md §17/§18)
- `portfolio/portfolio_manager.py` (orchestrator), Sector Engine, REST/
  WebSocket/Dashboard, execution wiring, `RiskEngine` per-symbol/
  aggregate exposure awareness. All explicitly out of scope for this
  phase.

---

## [V16.5] — Patch consolidation merge (this repository)

Merged ten development-phase bundles into one tree. See
`MERGE_REPORT.md` for full detail. Summary of functional changes
relative to the pre-merge `Brain_Bot_RUN` baseline:

### Added
- **Dashboard API authentication** (P1-A): bearer-token auth
  (`api/auth.py`), `API_AUTH_ENABLED` / `API_KEYS` / `JWT_SECRET`
  settings, off by default.
- **Dynamic, volatility-aware risk sizing** (P1-B1): risk-per-trade and
  leverage calculation moved from `agents/risk_manager.py` into
  `risk/risk_engine.py` (`get_leverage`, `_volatility_factor`), now
  reacting to ATR-normalized volatility, not just consecutive-loss
  streaks.
- **Multi-symbol foundation** (P1-C): `Settings.symbol_list` /
  `SYMBOLS` env var — architecture-only, falls back to the existing
  single-`SYMBOL` behavior when unset, so no deployment is affected
  unless explicitly opted in.
- **Market Scanner** (V16 Phase 2 Part 1): `scanner/market_scanner.py`,
  wired into `main.py`, gated behind `SCANNER_ENABLED` (default off).
  New `scanner_snapshots` table.
- **Opportunity Ranking Engine** (V16 Phase 2 Part 2): `ranking/`
  package (composite scoring across trend/momentum/volume/funding/
  liquidity/risk/AI-confidence/historical-performance factors). New
  `ranking_history` table. Not yet wired to a consumer — see
  `ARCHITECTURE_REPORT.md`.
- **Watchdog supervision**: `system_health/watchdog.py` gains
  `WatchdogSupervisor`, paired with `systemd`'s `Type=notify` +
  `WatchdogSec=30` in `deployment/systemd/brain_bot.service`.
- Duplicate-order-id protection in `execution/trade_manager.py`
  (`_is_duplicate_order_error`, `new_client_order_id`).
- `PyJWT` added to `requirements.txt` (dashboard auth dependency).

### Fixed
- `/paper_trades` API endpoint returns `200` with `enabled: false`
  instead of `503` when the paper engine isn't running, so the
  dashboard renders a clean empty state instead of an error
  (previously shipped as a loose, unapplied `.patch` file — now
  confirmed applied and the stray patch file removed).

### Changed
- `agents/risk_manager.py`: risk-percentage calculation delegated to
  `RiskEngine` rather than computed locally (see Added, dynamic risk).

### Repository hygiene
- Removed dead patch artifacts (`findstr`, `uvicorn.txt`,
  `paper_metrics_503_fix.patch`, a stray brace-expansion-named empty
  directory) — see `CLEANUP_REPORT.md`.
- Added `.github/workflows/ci.yml` (lint + test + advisory
  `pip-audit`) and `release.yml`.
- Added `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`.

---

Earlier history is described in `docs/V16_AUDIT_REPORT.md`,
`docs/V16_PHASE1_MULTISYMBOL_MIGRATION.md`, and `reports/` (V14/V15-era
audits), carried over unchanged by this merge.
