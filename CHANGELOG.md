# CHANGELOG

## [Unreleased] — V16 Phase 3A: Strategy Plugin System

### Added
- **`execution/strategy_registry.py`** (`StrategyRegistry`): name →
  factory lookup for `signal_provider` implementations, formalising the
  plug point `execution/execution_orchestrator.py` (§23) already
  documented but never made selectable. Duplicate registration under
  an existing name raises unless `override=True`. Pre-registers:
  - `"portfolio_signal_provider"` (default) — wraps the existing
    `PortfolioSignalProvider` unmodified.
  - `"smc_oi_regime"` — wraps `execution/strategy.py`'s
    `SMC_OI_Regime_Strategy` via the new `SMCOIRegimeStrategyAdapter`,
    which converts its bare `(direction, stop_loss, take_profit)`
    tuple into a full `ExecutionSignal` using `.last_decision.entry_price`.
    Documented as **not symbol-aware** — see PATCH_NOTES.md.
- **`config/settings.py`**: `+STRATEGY_NAME` (default
  `"portfolio_signal_provider"`, byte-for-byte the class already
  hardcoded before this phase — no behavior change unless explicitly
  configured).

### Changed
- **`main.py`**: the `ExecutionScheduler` bootstrap's
  `signal_provider = PortfolioSignalProvider(...)` construction now
  reads `signal_provider = build_strategy(settings.STRATEGY_NAME, ...)`
  with identical keyword arguments. No other line changed.

### Testing
`pytest tests/ -q` → 1533 passed, 0 failed (1512 baseline + 21 new in
`tests/test_strategy_registry.py`). `ruff check .` → clean.

## [Unreleased] — V16 Phase 2F: Execution Scheduler + Multi-Symbol Signals

### Added
- **`execution/portfolio_signal_provider.py`** (`PortfolioSignalProvider`):
  the real `signal_provider` `ExecutionOrchestrator` (§23) was designed
  to accept as an injected dependency. Reuses the exact pipeline
  `main.py`'s live single-symbol loop already uses — `RegimeEngine` ->
  `SMCEngine` -> `VolumeEngine` -> `MarketContextBuilder` ->
  `ConfidenceEngine` — confirmed by reading `main.py`'s actual
  `run_trading_cycle()`, not `execution/strategy.py`'s
  `SMC_OI_Regime_Strategy`/`BrainDecisionEngine` (a parallel pipeline
  that exists for external-bot-framework compatibility but is never
  instantiated in production). Never raises — one bad symbol can't
  poison a multi-symbol batch.
- **`execution/execution_scheduler.py`** (`ExecutionScheduler`): the
  timer loop — rank -> limit -> balance -> `decide()` -> `execute()`.
  Threading mirrors `scanner/market_scanner.py`'s `MarketScanner`
  exactly (daemon thread, `start()`/`stop()`/`is_running()`).
  `run_once()` is public so it can be driven synchronously without
  threading at all.
- **`data/binance_provider.py`**: `+symbol=` param on 7 methods
  (defaults to `self.symbol`, every existing call site unaffected),
  `+get_market_data_for(symbol)` for an explicit arbitrary symbol.
- **`intelligence/market_context_builder.py`**: `+symbol=` param on
  `build()` — the one place a symbol was implicitly hardcoded
  (`settings.SYMBOL`) in an otherwise fully stateless pipeline.
- **`config/settings.py`**: `+SCHEDULER_ENABLED` (default `False`),
  `+SCHEDULER_INTERVAL_SECONDS` (default 60),
  `+SCHEDULER_CANDIDATE_LIMIT` (default 20).
- **`main.py`**: new guarded bootstrap block, same shape as the
  existing `MarketScanner` block — `if SCHEDULER_ENABLED: try: ...
  except: log, don't crash`. Requires `SCANNER_ENABLED` (logged, not a
  hard error, if missing). Reuses the already-built `trade_manager`
  rather than constructing a second execution engine.
- 34 new tests (`test_portfolio_signal_provider.py` 12,
  `test_execution_scheduler.py` 22). Full suite: 1478 → 1512 passed, 0
  failed. `ruff check .` clean.
- `docs/architecture.md` §24 (the pipeline-choice correction, why the
  pipeline could be reused unmodified, two real bugs caught before
  merge, scope boundary). §1-23 byte-for-byte untouched — verified with
  `diff` against the pre-phase file, not just asserted.

### Two real bugs caught before merge (see architecture.md §24 for detail)
- A local re-import of `build_execution_engine` inside the new
  bootstrap block shadowed the existing module-level import for the
  *entire* `build_system()` function — breaking an unrelated, already-
  working call earlier in that same function the moment
  `SCHEDULER_ENABLED=true`. Caught by `ruff check .`'s `F823` before
  ever running.
- The first draft called `build_execution_engine()` a second time
  instead of reusing the already-built `trade_manager` — would have
  silently split execution state into two disconnected engines (two
  separate paper balances, or two separate `ExecutionCoordinator`
  per-symbol caches) in the same process.

### Not included (explicitly out of scope for this phase)
- No reconciliation-fed `PortfolioState` — `ExecutionScheduler`'s state
  starts empty each process start and is built up only from its own
  executions; a position opened before it started, by the legacy loop,
  or manually on the exchange is not reflected yet.
- No execution-outcome persistence (carried forward from §23, still
  unchanged).
- No dashboard panel for `ExecutionScheduler.to_dict()` or the existing
  `/api/execution/*` endpoints.

---

## [Unreleased] — V16 Phase 2E: Execution Wiring & Live Orchestrator

### Added
- **`execution/execution_orchestrator.py`** (`ExecutionOrchestrator.execute()`):
  connects `PortfolioManager`'s `OrchestratedDecision` to the existing
  execution layer. Per allocation: idempotent (keyed on
  `(batch_id, symbol)`), retries recoverable failures up to
  `EXECUTION_MAX_RETRIES` (never retries risk rejection/insufficient
  capital/duplicate order/manual cancel), publishes lifecycle events,
  updates the caller's `PortfolioState` on success. Per replacement:
  closes `outgoing_symbol` only and calls
  `PortfolioManager.notify_position_closed()` — does not open
  `incoming_symbol` (no sizing data exists for it at this decision
  layer; see architecture.md §23).
- **`execution/execution_state.py`**, **`execution_metrics.py`**,
  **`execution_events.py`**: in-memory execution-lifecycle tracking,
  pure metrics computation over it, and a thin vocabulary wrapper over
  the existing `events/event_bus.py` (no second pub/sub mechanism).
- **`execution/execution_coordinator.py`**: `+close_position()` —
  additive passthrough routing to the correct per-symbol `TradeManager`
  (needed for replacement-close; the existing `__getattr__` fallback
  only delegates to the *default* symbol's manager, which would have
  closed the wrong position for any non-default symbol).
- **`api/execution_api.py`**: `GET /api/execution/metrics`, `/status`,
  `/executions[?status=][&limit=]`, `/executions/{id}` — additive
  router, same pattern as Phase 2C's `portfolio_api.py`.
- **`api/portfolio_ws.py`**: relays `execution_started`/`_completed`/
  `_failed`/`_cancelled`/`_metrics_updated` over the existing
  `/ws/portfolio` connection (dedup by `EventBus` seq, same shape as
  the existing dedup-by-row-id decision relay) — no protocol redesign,
  no second WebSocket route.
- **`config/settings.py`**: `+EXECUTION_MAX_RETRIES` (default 2),
  `+EXECUTION_RETRY_DELAY_SECONDS` (default 0.0).
- 100 new tests (`test_execution_state.py` 25, `test_execution_metrics.py`
  9, `test_execution_events.py` 9, `test_execution_orchestrator.py` 34,
  `test_execution_api.py` 14, +2 in `test_execution_coordinator.py`,
  +7 in `test_portfolio_ws.py`). Full suite: 1280 → 1380 passed, 0
  failed. `ruff check .` clean.
- `docs/architecture.md` §23 (design rationale, scope boundary, and the
  real placement bug caught during testing — see that section for
  details). §20 "Next up" left untouched, per the phase's own
  documentation rules.

### Not included (explicitly out of scope for this phase)
- No execution-outcome persistence (`portfolio_history` remains
  decision-only; fills/slippage are not yet written anywhere durable —
  see architecture.md §23 "History updates").
- No scheduler calling `PortfolioManager.decide()` then
  `ExecutionOrchestrator.execute()` on a cadence — `CLAUDE.md`'s own
  next priority after this phase, not started early.
- No multi-symbol-capable signal generation — `ExecutionOrchestrator`
  takes `signal_provider` as an injected dependency;
  `execution/strategy.py`'s existing `SMC_OI_Regime_Strategy` remains
  single-symbol-only and unmodified.
- No dashboard panel consuming `/api/execution/*` or the new WS events
  yet.

---

## [Unreleased] — V16 Phase 2C: Portfolio API

### Added
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
## [Unreleased] — Bundle Manager (tools/)

### Added
- New `tools/` package: `git_utils.py`, `bundle_utils.py`, `history.py`,
  Automates importing `.bundle`/`.bundle.txt` files dropped into
  `update/incoming/`: verify → extract feature branch/SHA → skip
  duplicates (`bundle_history.json`) → fetch → checkout → push → file
  into `update/applied/` or `update/failed/`. `sync` fast-forwards the
  base branch after a merge. See `docs/architecture.md` §21.
- New `PORTFOLIO_*`-style `BUNDLE_*` settings in `config/settings.py`
  (`BUNDLE_INCOMING_DIR`, `BUNDLE_APPLIED_DIR`, `BUNDLE_FAILED_DIR`,
  `BUNDLE_HISTORY_FILE`, `BUNDLE_REMOTE`, `BUNDLE_BASE_BRANCH`,
  `BUNDLE_PUSH_RETRIES`, `BUNDLE_GIT_TIMEOUT_SECONDS`).
- `update/{incoming,applied,failed}/` directories (tracked via
  `.gitkeep`; contents gitignored).
- 98 new tests (`tests/test_bundle_manager_*.py`). Full suite:
  1001 → 1099 passed, 0 failed.

### Design notes
- Dry-run preview + confirmation before any real fetch/checkout/push;
  never force-pushes/force-fetches without `--force` (and then via
  `--force-with-lease`, never a bare `--force`).
- `bundle_history.json` is tracked in git (shared duplicate-import
  ledger), atomic writes.
- No `.github/workflows/*.yml` generated — out of scope, needs its own
  secrets/permissions design.

---

## [V16.5] — Patch consolidation merge (this repository)

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
