# CHANGELOG

## [Unreleased] — V16 Phase 4C Step 5: Live Recommendation Scoring Completeness (Track A)

Closes the one remaining gap Step 4's own design audit flagged: the
live decision path threaded `recommendations` all the way from
`_state` down to `recommendation_scoring._coverage_subscore()`
(Step 3), but never threaded `dataset_row_count` alongside it — that
value was written to `_state["learning_dataset_row_count"]` by
`main.run_learning_recommendation_refresh()` (Step 4) but nothing ever
read it back out, so the live path always called with
`dataset_row_count=None` and `_coverage_subscore()` fell back to its
own existing, correct `0.0` default.

**Audit note:** a fresh-clone, code-first re-trace of the full chain
(`CEOGatedSignalProvider` → `MultiSymbolCEODispatcher` →
`MultiSymbolCEOAdapter` → `CEOAgent.decide_from_context_with_recommendations()`
→ `apply_learning_recommendations()` → `recommendation_scoring`)
confirmed every layer below `CEOGatedSignalProvider` already accepted
and forwarded `dataset_row_count` (`MultiSymbolCEOAdapter`'s own
`decide_with_signal(dataset_row_count=None)` parameter, unused in
production; `MultiSymbolCEODispatcher`'s generic `**kwargs`
passthrough) — the gap was exactly two missing lines: no reader on the
`_state` side, no second provider slot on `CEOGatedSignalProvider`.

### Added
- `execution/ceo_gated_signal_provider.py`: `CEOGatedSignalProvider`
  gains an optional `dataset_row_count_provider` constructor parameter
  — same idiom, same defensive try/except, same "only added to kwargs
  when actually configured" contract as the existing
  `recommendation_provider` (Step 4). `None` (default): byte-identical
  to pre-Step-5 behavior.
- `main.py`: a `_get_learning_dataset_row_count()` reader (mirrors
  `_get_learning_recommendations()` exactly), wired to
  `CEOGatedSignalProvider(..., dataset_row_count_provider=...)`.
- 16 new regression tests
  (`tests/test_recommendation_dataset_row_count_wiring.py`): threading,
  multi-symbol isolation (same global count to every symbol, no
  cross-symbol leakage), provider-failure fallback, BLOCKED/action/
  direction/score_breakdown/agreement_score untouched, and the refresh
  job's own `learning_dataset_row_count` write (a narrow gap in Step
  4's own test coverage, closed additively without modifying that
  file).

### Not changed
No new architecture, no second recommendation engine/provider/
scheduler/EventBus/decision engine/state store. The scoring formula,
its weights, `RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT`, CEO decision
authority, `decide()`/`decide_from_context()`, and every existing
safety invariant (BLOCKED pass-through, action/direction/
score_breakdown/agreement_score never touched, advisory-only) are
unmodified — verified via the full pre-existing test suite passing
unchanged (2219 → 2235, exactly the 16 new tests, zero pre-existing
test modified).

## [Unreleased] — V16 Phase 4C Step 4: Live Scheduler Wiring (Track A)

Connects Phase 4C Step 3's recommendation application layer to the ONE
real live decision gate — `agents/multi_symbol_adapter.py::
MultiSymbolCEOAdapter.decide_with_signal()`'s call to
`CEOAgent.decide_from_context()`, reached via `execution/
ceo_gated_signal_provider.py::CEOGatedSignalProvider` in the
CEO-gated multi-symbol scheduler path (`SCHEDULER_ENABLED` +
`CEO_MULTI_SYMBOL_ENABLED`, both off by default).

**Design audit note:** a fresh-clone, code-first audit (this phase's own
brief, "ANALYSIS / SPEC ONLY") traced the real call path from
`main.py`/`ExecutionScheduler` down to the exact decision function and
found: (1) the legacy single-symbol path's `CEOAgent.decide()` call
(`main.py:833`) does NOT gate execution at all — `ConfidenceEngine`'s
own `decision.action` does — so wiring recommendations there would have
zero effect on real trades; (2) `learning/learning_report.py::
LearningReportGenerator` (Phase 4C Step 1) was never invoked anywhere
in live code — nothing ever populated `_state["learning_recommendations"]`
despite `/api/recommendations` reading it since Step 3. Both gaps are
closed by this phase. Full audit trail in PATCH_NOTES.md.

### Added
- **`CEOAgent.decide_from_context_with_recommendations()`**
  (`agents/ceo_agent.py`): the `decide_from_context()` counterpart to
  Step 3's `decide_with_recommendations()` — same thin-wrapper pattern,
  same safety contract (BLOCKED byte-identical, action/direction/
  score_breakdown/agreement_score never touched, confidence bounded by
  `RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT`), now additionally wrapped
  in try/except so a recommendation-application failure falls back to
  the unmodified decision instead of propagating into a live decision
  cycle. The pre-existing `decide_with_recommendations()` gained the
  same try/except (closes a gap found during this phase's own safety
  audit — Part G, Case 3).
- **`main.run_learning_recommendation_refresh()`**: new scheduled job
  (daily at 02:30, same cadence class as the existing nightly retrain
  job at 02:00) that calls the existing `LearningReportGenerator`
  unchanged and writes its output to the existing `_state[
  "learning_recommendations"]` slot via the existing `set_state()`
  helper — no new persistence layer, no new scheduler. Gated on
  `RECOMMENDATION_APPLICATION_ENABLED` (re-checked live every run); a
  no-op, journal-untouched no-op when the flag is off.
- `MultiSymbolCEOAdapter.decide()`/`decide_with_signal()`
  (`agents/multi_symbol_adapter.py`) and `CEOGatedSignalProvider`
  (`execution/ceo_gated_signal_provider.py`) both gained optional,
  default-`None` parameters (`recommendations`, `dataset_row_count`,
  `recommendation_provider`) to thread recommendations from
  `_state["learning_recommendations"]` down to the new CEO method —
  every default preserves prior behavior exactly; `main.py` is the only
  call site that opts in, via a small injected callable
  (`recommendation_provider`) rather than a hard `api.app` import inside
  `execution/ceo_gated_signal_provider.py`, preserving that module's
  existing dependency-injection/testability idiom.

### Verified unchanged
- `CEOAgent.decide()` and `decide_from_context()` — full existing test
  suites (`tests/test_multi_symbol_ceo_integration.py`,
  `tests/test_ceo_gated_signal_provider.py`,
  `tests/test_ceo_symbol_cache.py`,
  `tests/test_ceo_decide_with_recommendations.py`,
  `tests/test_ceo_ensemble_fusion.py`) pass unmodified.
- The legacy single-symbol path (`main.py::run_trading_cycle`) — not
  touched; its `ceo.decide()` call was confirmed (Part B of the audit)
  to already be decision-inert, so it was correctly left alone.
- Default configuration (`RECOMMENDATION_APPLICATION_ENABLED=False`,
  `CEO_MULTI_SYMBOL_ENABLED=False`, `SCHEDULER_ENABLED=False`) — zero
  behavioral change; the new scheduled job never touches the journal
  while disabled (tested), and every new adapter/provider parameter
  defaults to `None`/unused.

### Tests
- `tests/test_ceo_live_recommendation_wiring.py` (new, 22 tests):
  backward compatibility, BLOCKED byte-identity (via a
  ConfidenceEngine-hard-block fixture, since a risk-manager circuit
  breaker alone only ever produces WAIT — confirmed by reading
  `decide()`'s actual branch logic), recommendation-application-failure
  fallback (both new and pre-existing wrapper methods), multi-symbol
  isolation, `MultiSymbolCEODispatcher` kwarg forwarding,
  `CEOGatedSignalProvider.recommendation_provider` wiring and failure
  isolation, and the refresh job's disabled/enabled/generation-failure
  paths.
- Full suite: 2197 → 2219 (22 new, 0 removed, 0 weakened, 0 failing).
- `ruff check . --exclude dashboard_src --exclude dashboard`: clean.
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80`:
  clean (no output).

## [Unreleased] — V16 Phase 4C Step 3: Recommendation Application Layer (Track A)

Connects `learning/`'s (Phase 4C Step 1) recommendations to the live
decision pipeline as ADVISORY inputs only. No autonomous strategy
rewriting, no automatic parameter mutation — every applied
recommendation is bounded, explainable, and reversible by inspection.

**Verification note:** this phase's brief assumed a "Phase 4C Step 2"
had already been merged. An independent fresh clone (two separate
clones, same HEAD `90a7e4e`) found no such phase anywhere in
`git log --all` — only Step 1 exists. The missing prerequisite schema
work (recommendation identity/lifecycle fields) is folded into this
bundle instead of a separate phase, per instruction. See PATCH_NOTES.md
for the full gap report.

### Added
- **`learning/application/` package** (new): `recommendation_validator.py`
  (deterministic `validator_status`: valid/expired/insufficient_sample/
  invalid), `recommendation_context.py` (Part A — filters by symbol/
  regime/direction/confidence/expiry/validator status into one canonical
  `RecommendationSet`, with narrow best-vs-worst contradiction
  detection), `recommendation_scoring.py` (Part D — deterministic
  0.0-1.0 normalized score: confidence bucket + historical win-rate +
  sample size + recency + coverage + validator status, weights in
  `config/settings.py`, sum to 1.0), `recommendation_advisor.py`
  (Part B+C — bounded, explainable `CEODecision` adjustment: BLOCKED
  decisions pass through byte-identical; otherwise `confidence` moves by
  at most `RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT` points, `action`/
  `direction`/`score_breakdown`/`agreement_score` are never touched;
  every recommendation — applied or skipped — gets one
  `AppliedRecommendationExplanation`), `recommendation_metrics.py`
  (Part E — in-process runtime counters, `events/event_bus.py`-style
  singleton), `recommendation_events.py` (Part G — publishes
  `RECOMMENDATION_LOADED`/`APPLIED`/`SKIPPED`/`EXPIRED`/`CONTRADICTED`
  via the existing `EventBus`, no new transport),
  `recommendation_service.py` (orchestrates all of the above into one
  call).
- **`agents/ceo_agent.py`**: `CEOAgent.decide_with_recommendations()` —
  additive method, same thin-wrapper pattern as Phase 4B Step 3B's
  `decide_from_context()`. Calls the existing, UNCHANGED `decide()`
  first; nothing pre-existing calls this new method, so `decide()` and
  `decide_from_context()` behave identically to before this phase.
- **`api/app.py`**: `GET /api/recommendations` (active/skipped + reasons,
  optional `symbol`/`regime` filters), `GET /api/recommendations/metrics`
  (Part E counters). Both follow the existing honest-empty-state
  convention (`/api/ceo-decisions`) — zero and empty until a future
  scheduler populates `_state["learning_recommendations"]` (out of
  scope here, see "Known follow-up work" below).
- **`config/settings.py`**: `RECOMMENDATION_APPLICATION_ENABLED` (off by
  default), `RECOMMENDATION_TTL_HOURS`, `RECOMMENDATION_MIN_SAMPLE_SIZE`,
  `RECOMMENDATION_SCORE_SATURATION_N`, six
  `RECOMMENDATION_SCORE_WEIGHT_*` (sum to 1.0),
  `RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT`,
  `RECOMMENDATION_MAX_APPLIED_PER_DECISION`.
- **94 new tests** across 9 files (`tests/test_recommendation_*.py`,
  `tests/test_ceo_decide_with_recommendations.py`,
  `tests/test_recommendations_api.py`) covering loading, filtering,
  expiry, contradiction, scoring, application, safety-ordering (BLOCKED
  pass-through, confidence clamping, action/direction never touched),
  dashboard API, event publishing, and decision integration.

### Changed (additive, backward-compatible)
- **`learning/recommendation_engine.py`**: `Recommendation` gains six
  new defaulted fields — `id` (deterministic hash of
  category+kind+subject, NOT random, so identity survives
  regeneration), `symbol`, `regime` (both honestly `None` when the
  underlying pattern isn't scoped to one), `generated_at`, `expires_at`,
  `validator_status` (default `"unvalidated"`). `direction` was
  requested by this phase's brief but was **not** added — no pattern
  kind this engine reads is conditioned on trade direction anywhere in
  `pattern_miner.py`; adding the field would mean fabricating values.
  `RecommendationEngine.generate()` gained an optional `now` parameter
  (defaults to `datetime.now(timezone.utc)`); every existing positional/
  keyword call site and every existing test is unaffected.

### Known follow-up work (explicitly out of scope for this phase)
- No scheduler wires a live `LearningSnapshot`'s recommendations into
  `_state["learning_recommendations"]` or into
  `decide_with_recommendations()`'s live decision loop — both exist and
  are fully tested, but nothing calls them from `main.py` yet. Same
  "groundwork, not a behavior change" boundary Phase 4B Step 3B drew
  around `CEODecisionContext.portfolio_state`.
- Contradiction detection (Part A) is intentionally narrow (same-
  category, same-symbol, best-vs-worst `based_on.kind` polarity) — not
  a general-purpose text-contradiction detector.
- `direction`-based filtering exists in `recommendation_context.py` but
  is a no-op today (see above) until a future phase adds direction-
  conditioned patterns to `pattern_miner.py`.



New read-only package `exchange_state/` — single source of truth for
account/position/order state for World (C2), Dashboard (C3), and CEO/AI
context (C4). Nothing in the trading engine's decision path depends on
it; purely additive.

Rewritten from scratch after the repo owner reviewed an externally
produced v1 draft and rejected it pending fixes. v2 addresses every point
raised: no duplicate Binance JSON parsing (manager only calls two new
additive `BinanceDataProvider` methods), one `ExchangeSnapshot` cache
instead of six per-field caches, one 2-call `refresh()` instead of four
separate round trips, funding rate removed (it's market data, not
exchange state), and `snapshot_revision`/`position.version`/
`snapshot_uuid`/`sync_reason`/`last_sync_source`/`stale_reason`/
`health_score` added. Full design in
`docs/architecture/EXCHANGE_STATE_MANAGER.md`.

### Added
- `exchange_state/models.py` — frozen dataclasses: `AccountSnapshot`,
  `PositionSnapshot` (with per-symbol `version`), `OrderSnapshot` (with
  `is_sl`/`is_tp`), `ExchangeSnapshot`.
- `exchange_state/manager.py` — `ExchangeStateManager` (TTL cache,
  degraded/stale fallback, thread-safe via one `RLock` per manager) and
  `get_manager()` singleton registry keyed by `(mode, exchange, account_id)`.
- `exchange_state/constants.py` — valid modes, default TTL.
- `data/binance_provider.py` — two new additive methods:
  `get_account_snapshot()` (one `/fapi/v3/account` call → wallet/margin
  totals + all open positions) and `get_open_orders(symbol=None)` (one
  `/fapi/v1/openOrders` call). Reuses the existing parsing convention from
  `get_account_balance()`/`get_position_info()`; no new abstraction.
  Also added `get_server_time()` (thin wrapper, no new call pattern).
- Tests: `tests/test_exchange_state_models.py`,
  `tests/test_exchange_state_manager.py`,
  `tests/test_binance_provider_c1_additions.py`.

### Impact
Additive only. No existing file's existing methods changed behavior.
Full suite: `pytest -m unit -q` → all passing. `ruff check` and
`vulture --min-confidence 80` clean on all new/changed files.

## [Unreleased] — Hotfix: Live-Trading Risk Hardening (BUG-LIVE-RISK-01..04)

Four real-money-risk bugs found via source inspection of `main` after
BUG-V16-BP-05 (below) landed. Full detail: `PATCH_NOTES.md`,
`MIGRATION.md`, `docs/architecture.md`.

### Fixed
- **BUG-LIVE-RISK-01** — `config/settings.py`'s `API_AUTH_ENABLED`
  defaulted to `False` with nothing stopping a live run from using it.
  Now defaults to `True`; `api/app.py` refuses to start at all when
  `EXECUTION_MODE=live` and auth is off.
- **BUG-LIVE-RISK-02** — a real exchange position with no journal record
  (`system_health/recovery_engine.py`) got zero automatic protection.
  Now auto-places a protective SL and blocks new entries
  (`RiskEngine.set_manual_hold()`) until a human acknowledges via the
  new `POST /api/system/reconciliation/acknowledge`.
- **BUG-LIVE-RISK-03** — `execution/trade_manager.py`'s `execute_trade()`
  discarded `set_leverage()`'s return value and sized against the
  intended leverage even when the exchange call failed. Now re-queries
  and sizes against the actual current leverage, aborting if that can't
  be verified either.
- **BUG-LIVE-RISK-04** — `close_position()`'s retry budget (2 attempts)
  was lower than `place_stop_loss`'s (5), despite being the fallback
  used when SL placement exhausts all of ITS retries. Aligned to match.

### Added
- `tests/test_recovery_engine.py` — first-ever test coverage for
  `system_health/recovery_engine.py` (12 tests).
- 18 further new tests across `tests/test_api_auth.py`,
  `tests/test_execution.py`, `tests/test_v16_execution_idempotency.py`,
  and `tests/test_audit_fixes.py`.
- `conftest.py`: autouse fixture preserving the old auth-off-by-default
  behavior for the existing test suite.

### Impact
`config/settings.py`, `api/app.py`, `risk/risk_engine.py`,
`system_health/recovery_engine.py`, `execution/trade_manager.py`.
`RiskEngine.can_trade()` and `TradeManager.execute_trade()` keep their
existing signatures/contracts — internal logic only. **Operator impact:**
see `MIGRATION.md` — `.env` without an explicit `API_AUTH_ENABLED` will
now require `API_KEYS`/`JWT_SECRET` to avoid 401s, and
`EXECUTION_MODE=live` can no longer start with auth off at all.
Full suite: `pytest -m unit -q` → 1948 passed, 0 failed (1918 baseline +
30 new). `ruff check .` clean.

## [Unreleased] — Hotfix: Live Trading Client Wiring (BUG-V16-BP-05)

### Fixed
- **`data/binance_provider.py`** — `BinanceDataProvider.trade_client` was
  hardcoded to always construct with `BINANCE_TESTNET_API_KEY` /
  `BINANCE_TESTNET_BASE_URL`, regardless of `EXECUTION_MODE` /
  `settings.BINANCE_TESTNET`. `run_live.bat`/`run_live.sh` correctly set
  `EXECUTION_MODE=live` + `BINANCE_TESTNET=false`, and
  `execution/execution_factory.py` correctly logged `Binance LIVE ⚠️`, but
  every real order, balance check, and position check
  (`execution/trade_manager.py` → `self.client` → `data_provider.client` →
  `trade_client`) still went to Binance **Testnet**. `EXECUTION_MODE=live`
  could not previously reach mainnet under any configuration.
  `settings.base_url` (config/settings.py) already encoded the correct
  mainnet/testnet branch but was never referenced anywhere — dead code.
  Fix: `trade_client` now branches on `settings.BINANCE_TESTNET` (the same
  flag the run scripts already set) and raises `RuntimeError` at startup if
  live mode is selected with empty `BINANCE_API_KEY`/`BINANCE_API_SECRET`,
  instead of silently signing requests with blank mainnet credentials.
  `market_client` (market data) is unaffected — it was already always
  mainnet.
- Startup log line changed from `market=MAINNET | trading=TESTNET` (always)
  to `market=MAINNET | trading={TESTNET|MAINNET ⚠️ LIVE-REAL-MONEY}`
  reflecting the actual client in use.

### Added
- `tests/test_binance_provider_trade_client.py` — regression tests pinning
  testnet-mode credentials, live-mode mainnet credentials, and the
  fail-fast guard for live mode with missing mainnet keys.

### Impact
Affects only `data/binance_provider.py` (behavior) and
`tests/test_binance_provider_trade_client.py` (new tests). No API
signature changes; `execution/trade_manager.py`, `execution_factory.py`,
and everything above them are unaffected since they only ever consumed
`data_provider.client`. Paper mode (`EXECUTION_MODE=paper`) is unaffected
— it never uses `trade_client` for order execution. **Operational impact:
once this patch is applied, `run_live.bat`/`run_live.sh` will place real
orders on Binance mainnet using `BINANCE_API_KEY`/`BINANCE_API_SECRET`.
Verify those are genuine mainnet keys with the desired permissions/IP
whitelist before running live.**

## [Unreleased] — V16 Phase 4C Step 1: Autonomous Learning Pipeline (Track A)

### Added
- **`learning/` package** (new, Track A, READ ONLY): `dataset_builder.py`
  (`LearningDatasetBuilder`, wraps `journal_v2.get_ensemble_learning_dataset()`,
  adds derived `cumulative_pnl`/`running_drawdown`), `symbol_statistics.py`,
  `regime_statistics.py`, `agent_statistics.py`, `feature_statistics.py`,
  `performance_tracker.py`, `pattern_miner.py` (`PatternMiner`, every
  requested pattern kind, sample-size gated), `recommendation_engine.py`
  (`RecommendationEngine`, traceable text recommendations, no automatic
  actions), `learning_snapshot.py` (immutable, timestamp-named JSON
  snapshots), `learning_report.py` (`LearningReportGenerator`, writes
  `learning_report.json`/`performance_report.json`/`pattern_report.json`/
  `recommendation_report.json`).
- **`journal/journal_v2.py`**: `get_trade_attribution()` +13 keys
  (`quantity`, `stop_loss`, `take_profit`, `rr`, `regime`,
  `signal_confidence`, `score`, `mtf_aligned`, `smc_flags`, `reason`,
  `source`, `duration_seconds`, `close_confidence`) — surfaces data
  Phase 4B Step 3D was already storing but this method wasn't yet
  returning. Additive only.

### Discovery
`get_ensemble_learning_dataset()`'s N+1 `get_trade_attribution()` call
pattern doesn't scale past ~1,000 trades (found via this phase's
benchmark) — a pre-existing characteristic, not introduced or fixed
here. `market_context`/`volatility`/`atr`/`spread` aren't persisted
anywhere today — always `None` on `LearningRow`, schema-ready not
fabricated. `regime`/agent data is only real for legacy single-symbol
trades. See PATCH_NOTES.md and architecture.md §33 for full detail.

### Testing
`pytest tests/ -q` → 1885 passed, 0 failed (1783 baseline + 102 new).
`ruff check .` → clean.

## [Unreleased] — V16 Phase 4B Step 3D: Unified Trade Lifecycle & Trade Attribution

### Added
- **`execution/trade_lifecycle.py`**: `TradeLifecycle` — single
  orchestration point every open/close path routes through.
  `PENDING → EXECUTING → OPEN → MONITORING → EXIT_REQUESTED →
  EXIT_EXECUTING → CLOSED` (or `FAILED`) state machine, no back-
  transitions (this alone is the entire duplicate-close guard).
  `CloseSource` enum for all 12 requested close sources — honestly
  labeled which have a real automatic trigger in this codebase today
  vs. which are supported-but-not-yet-triggered-by-anything (see
  `docs/architecture.md` §32, Part B's table).
- **`api/lifecycle_api.py`**: `GET /api/lifecycle/state`,
  `GET /api/lifecycle/state/{symbol}` — read-only dashboard exposure.
  New process-wide `get_default_trade_lifecycle()` singleton (mirrors
  `execution_state.py`'s own pattern).
- `journal/trade_attribution.py::record_trade_outcome()`:
  +reason/+source/+symbol/+duration_seconds/+confidence, all optional,
  no schema change.
- `portfolio_manager.py::notify_position_closed()`: +`record_attribution`
  flag (default `True`, unchanged behavior for any pre-existing caller).
- `ExecutionOrchestrator`/`ExecutionCoordinator`/`TradeManager`: new
  optional `lifecycle` constructor parameter. Open side, replacement-
  close, and (newly) exchange-reject-on-close all routed through
  `TradeLifecycle`. `main.py`'s legacy SL/TP monitor and
  `system_health/recovery_engine.py`'s reconciliation cleanup routed
  the same way.
- 66 new tests across 5 files (unit, API, integration covering all 10
  requested Part H scenarios, concurrency stress tests at 25/50/100/250
  simultaneous positions, bug-regression tests). Full suite:
  1717 → 1783 passed, 0 failed.
- `docs/architecture.md` §32 — full design rationale, two real bugs
  found and fixed by this phase's own tests (documented in full, not
  glossed over), benchmark and stress-test results.

### Fixed (found by this phase's own tests, before reaching production)
- `TradeLifecycle` originally popped a handle from its internal dict on
  every terminal transition, which broke its own duplicate-close guard
  for a *second* close attempt against an already-closed symbol.
- `TradeLifecycle` defines `__len__`; without an explicit `__bool__`,
  a freshly-constructed empty instance was falsy, silently breaking
  `ExecutionOrchestrator`'s `lifecycle or TradeLifecycle(...)`
  constructor fallback — exactly `main.py`'s real bootstrap ordering.
  Fixed with an explicit `is not None` check plus a defensive
  `__bool__` override.

### Known limitation — not fixed this phase
- `execution/execution_factory.py::build_execution_engine()` (the
  3-mode paper/testnet/live factory `main.py` actually calls) isn't
  threaded with the shared lifecycle singleton yet — EMERGCLOSE
  reporting works for any directly-constructed `TradeManager`/
  `ExecutionCoordinator` but not yet the real bootstrap path.

---

## [Unreleased] — V16 Phase 4B Step 3C: Live CEO Agent Integration into Multi-Symbol Decision Pipeline

### Added
- **`execution/ceo_gated_signal_provider.py`** (`CEOGatedSignalProvider`,
  `map_ceo_decision_to_signal`): drop-in `SignalProvider`
  (`Callable[[str], ExecutionSignal | None]`, execution_orchestrator.py's
  exact contract) — zero changes to `ExecutionOrchestrator`. Disabled
  (`CEO_MULTI_SYMBOL_ENABLED=False`, default): byte-identical passthrough
  to the wrapped `PortfolioSignalProvider`, verified against the real
  class, not a fake. Enabled: routes through `MultiSymbolCEOAdapter`,
  maps `CEODecision` -> execution decision via the one centralized
  mapping function (BLOCKED/WAIT -> None; LONG/SHORT -> the already-priced
  signal if CEO agrees, None if it disagrees or nothing was priced to
  confirm). CEO can only confirm or veto an already-priced signal —
  `CEODecision` carries no entry/stop-loss/take-profit of its own.
- **`agents/ceo_symbol_cache.py`** (`CEOAgentSymbolCache`,
  `MultiSymbolCEODispatcher`): one full agent layer (all 6 sub-agents +
  CEOAgent) per symbol, via the existing `build_agent_layer()` factory,
  cached the same way `ExecutionCoordinator.get_manager()` caches
  per-symbol `TradeManager`. Solves a risk
  `agents/multi_symbol_adapter.py`'s own docstring flagged and deferred:
  sharing one `CEOAgent` across symbols would corrupt
  `RegimeAnalyst._prev_regime` and every agent's `_memory`/`_last`.
  Zero changes to `BaseAgent`, `RegimeAnalyst`, or any sub-agent class.
- **`agents/multi_symbol_adapter.py`**: `+decide_with_signal(symbol)` —
  same computation as the existing `decide()`, additionally returning
  the underlying priced `ExecutionSignal` so a caller needing both
  doesn't call `get_signal_with_context()` twice (which would duplicate
  MarketContextBuilder/ConfidenceEngine/RegimeEngine computation).
  `decide()` now delegates to it internally; output unchanged
  (verified byte-identical for identical input).
- **`execution/portfolio_signal_provider.py`**: now passes `symbol=symbol`
  into `regime_engine.classify()` — activates the per-symbol HMM cache
  built in Step 3A, which this file never actually triggered before
  (verified: `RegimeEngine.classify()` already supported `symbol=`, this
  call site just never used it).
- **`api/app.py`**: `+GET /api/ceo-decisions` — CEO Decision/Confidence/
  Consensus (agreement_score)/Top Reasons/Symbol for every candidate,
  newest first, optional `?symbol=` filter. Zero new persistence — reads
  `journal_v2.get_agent_decisions(agent="CEO_AGENT")` (Phase 4B Step 1's
  existing table). Returns an honest empty list (not an error) when CEO
  is disabled.
- **`config/settings.py`**: `+CEO_MULTI_SYMBOL_ENABLED` (default `False`).
- 142 new/changed tests across `test_ceo_gated_signal_provider.py` (26),
  `test_ceo_symbol_cache.py` (11), `test_ceo_decisions_api.py` (9),
  `test_phase4b_step3c_verification.py` (15, addressing every Part G
  brief requirement individually: byte-identical when disabled,
  independent per-symbol decisions when enabled, no duplicated
  MarketContextBuilder/ConfidenceEngine/RegimeEngine execution, HMM
  cache BTC/ETH/BTC = 2 models, execution follows CEODecision exactly),
  +4 in `test_multi_symbol_ceo_integration.py`. Full suite: 1652 → 1717
  passed, 0 failed. `ruff check .` clean.
- `docs/architecture.md` §31 (two corrections made to the requesting
  brief before writing code, the state-isolation risk and how it was
  solved, benchmark results, a specific real follow-up this phase makes
  possible but doesn't complete). §1-30 byte-for-byte untouched
  (diff-verified).

### Two real corrections to the requesting brief, made before writing code
- The brief's decision-mapping table named a `REJECT` CEOAgent action.
  Reading `agents/ceo_agent.py` directly confirms no such action can
  ever be produced — the real fourth action is `BLOCKED`. Used that
  instead.
- The brief asserted `RegimeEngine.classify()`'s per-symbol capability
  was already active. It existed (Step 3A) but was never actually
  invoked with a symbol anywhere in the codebase — a real, verified gap
  this phase's Part D closes, not a pre-existing done item.

### Not included (explicitly out of scope for this phase)
- No trade-level agent attribution wiring for CEO-confirmed executions
  (`journal/trade_attribution.py`'s `agent_attribution_from_ceo_decision()`
  exists but isn't called anywhere by this phase — would require
  `ExecutionOrchestrator` changes, ruled out by the brief's own "DO NOT
  rewrite... Execution Engine" constraint). See architecture.md §31
  "Next up" for the precise gap this leaves.
- No dashboard UI panel for the new `/api/ceo-decisions` endpoint.
- No changes to `PortfolioManager`, `TradeManager`, `TradeJournalV2`,
  `ExecutionOrchestrator`, `ExecutionCoordinator`, `RiskEngine`, or
  `CEOAgent.decide()`'s own behavior — every one of these is called
  exactly as already built and tested.

---

## [Unreleased] — V16 Phase 4B Step 3A: Symbol Isolation & Per-Symbol Regime Models

*(Backfilled during the C2 repository consolidation pass — this phase
merged via PR #13 on 2026-07-26 but had no CHANGELOG entry. Content below
is reconstructed from that PR's own merge commit message, not invented.)*

Architectural prerequisite for CEO Agent multi-symbol integration
(Step 3B+). Additive only — no CEO multi-symbol execution, no
`PortfolioSignalProvider`/`ExecutionOrchestrator`/journal/trade-attribution/
public-API changes.

Root cause fixed: `AgentReport` had no `symbol` field, so sequential
multi-symbol `analyse()` calls on a shared agent instance produced
reports indistinguishable by symbol after the fact. Separately,
`RegimeEngine` fit exactly one Gaussian HMM on whichever symbol's OHLCV
reached `classify()` first and silently reused it for every other
symbol for the process's lifetime (verified empirically: fitting on
BTC-like low-volatility data then classifying altcoin-like
high-volatility data reused the identical model object).

### Added
- **`agents/base_agent.py`**: `AgentReport` gains `symbol: str | None`
  (default `None`); included in `to_dict()`. Every existing kwargs-based
  construction site is unaffected.
- **`agents/trader_agent.py`, `risk_manager.py`, `smc_analyst.py`,
  `regime_analyst.py`, `journal_analyst.py`, `futures_analyst.py`**:
  each `analyse()`'s `AgentReport(...)` now passes
  `symbol=market_context.get("symbol")` — never fabricated when absent.
- **`agents/ceo_agent.py`**: `CEODecision` gains `symbol: str | None`
  (preparation only — does not touch action/confidence/score_breakdown/
  agreement_score/weights_used computation).
- **`regime/regime_engine.py`**: single `self._hmm_model`/`self._fitted`
  replaced with `self.models`, a dict keyed by an optional `symbol`
  parameter on `classify()`. Omitting `symbol` (every caller as of this
  commit) maps to one fixed default key, reproducing prior
  single-shared-model behavior byte-for-byte. Passing an explicit
  `symbol` gives that symbol its own independently-fit model.

### Known limitation
`execution/portfolio_signal_provider.py`'s own `RegimeEngine.classify()`
call is **not** wired with `symbol=` by this phase (out of scope per its
own stated constraints) — the actual multi-symbol production caller that
most needs per-symbol HMM isolation does not yet benefit from it. Step 3A
builds the capability; wiring `PortfolioSignalProvider` to use it is
deferred.

### Testing
`pytest tests/ -m unit -q` → 1626 passed, 0 failed (1600 baseline + 26
new, `tests/test_symbol_isolation.py`). All 12 pre-existing
`tests/test_regime.py` tests pass unchanged. `ruff check .` → clean.
Benchmark (50 timed `classify()` calls, steady state): old mean 16.16ms
vs. new-with-symbol mean 16.31ms — within one standard deviation of
measurement noise, not a measurable regression.

## [Unreleased] — V16 Phase 4B Step 3B: CEO Decision Context + Multi-Symbol Signal Integration

### Added
- **`agents/decision_context.py`**: `CEODecisionContext` — frozen
  dataclass (symbol, market_context, confidence_result,
  portfolio_state, existing_positions, risk_snapshot). The single
  input `CEOAgent.decide_from_context()` accepts.
- **`agents/multi_symbol_adapter.py`**: `MultiSymbolCEOAdapter(signal_provider,
  ceo_agent).decide(symbol)` — `PortfolioSignalProvider` ->
  `CEODecisionContext` -> `CEOAgent` -> `CEODecision`, zero duplicate
  MarketContextBuilder/ConfidenceEngine computation. Does not execute
  trades, allocate capital, or touch the journal.
- **`execution/portfolio_signal_provider.py`**: `+SignalWithContext`,
  `+get_signal_with_context(symbol)` — returns the already-computed
  market_context/confidence_result alongside the signal, instead of
  discarding them. `get_signal()` now delegates to the same internal
  computation (`_compute_signal_with_context`) — one path, not two.
- **`agents/ceo_agent.py`**: `+decide_from_context(context)` — thin
  compatibility wrapper around the existing, unchanged `decide()`.
- **`agents/__init__.py`**: exports `CEODecisionContext`,
  `MultiSymbolCEOAdapter`.

### Compatibility
`get_signal()`, `CEOAgent.decide()`, `CEODecision`, `AgentReport` all
unchanged. No settings/schema changes. `execution/execution_orchestrator.py`,
`portfolio/portfolio_manager.py`, `execution/trade_manager.py`,
`journal/`, `journal/trade_attribution.py`, `risk/risk_engine.py` not
modified.

### Known limitations
CEOAgent is still not invoked anywhere in the live V16 multi-symbol
path (this phase prepares integration only). Cross-symbol HMM
contamination on `PortfolioSignalProvider`'s `RegimeEngine` usage
remains unfixed (Step 3A's per-symbol capability exists; not yet
passed `symbol=` by this caller). See PATCH_NOTES.md for full detail.

### Testing
`pytest tests/ -q` → 1652 passed, 0 failed (1626 baseline + 26 new).
`ruff check .` → clean. Benchmark: flat ~91-101ms per symbol from
n=5 to n=40 — linear complexity confirmed.

## [Unreleased] — V16 Phase 4B Step 2: Execution Attribution + Portfolio Integration

### Added
- **`journal/trade_attribution.py`**: `record_trade_outcome(journal,
  trade_id, **fields)` — reusable attribution API, every field
  optional, covers both open-side (execution_id/order_id/slippage/
  latency_seconds) and close-side (+result/exit_price/pnl) calls.
  `agent_attribution_from_ceo_decision(ceo_decision)` — per-agent
  extraction from a real `CEODecision.to_dict()` using
  `CEOAgent.WEIGHTS`'s actual keys, plus a `"ceo"` aggregate entry.
- **`journal/journal_v2.py`**: `+save_execution_attribution()` (merges
  execution facts into `trades.extra_data`, no schema migration),
  `+get_trade_attribution()` (one trade's full facts + agent
  participation, joined via `signal_id` like `get_agent_performance()`
  already does), `+get_ensemble_learning_dataset()` (clean per-trade
  rows for a future Phase 4C — read-only, no weight-learning logic).
- **`portfolio/portfolio_models.py`**: `PortfolioPosition`
  `+trade_id: int | None = None`.

### Changed
- **`execution/execution_orchestrator.py`**: `+journal=None` (optional).
  Successful open now persists signal+trade+attribution and threads
  `trade_id` onto the position. Successful replacement close now
  computes exit_price/pnl/result honestly (never guessed) and hands
  them to `notify_position_closed()`.
- **`portfolio/portfolio_manager.py`**: `+journal=None` (optional).
  `notify_position_closed()` gains 10 new optional keyword-only
  params — every existing call site keeps working unchanged. Now the
  single place close-side attribution is persisted, for any current
  or future closing path.
- **`main.py`**: scheduler bootstrap passes `journal=journal_v2` into
  both `PortfolioManager(...)` and `ExecutionOrchestrator(...)`.

### Known limitations
Multi-symbol trades' `agent_participation` is genuinely `[]` (the
agent layer doesn't run on that signal path). Only replacement-
triggered closes are wired (no natural SL/TP monitor exists yet).
`fees` is always `None` (not computable from any data this codebase
fetches today). See PATCH_NOTES.md for full detail.

### Testing
`pytest tests/ -q` → 1600 passed, 0 failed (1556 baseline + 44 new).
`ruff check .` → clean.

## [Unreleased] — V16 Phase 4B Proper: Dynamic Per-Agent Weighting

> Added during the Repository Stabilization phase (2026-08-02) — this
> entry was missing from CHANGELOG.md despite the phase being merged,
> tested, and tagged; content verified against `docs/architecture.md`
> §28, not reconstructed from memory.

### Added
- **`config/settings.py`**: `DYNAMIC_AGENT_WEIGHTS_ENABLED` (default
  `False`), `DYNAMIC_WEIGHT_MIN_SAMPLES` (default `20`),
  `DYNAMIC_WEIGHT_BLEND` (default `0.3`),
  `DYNAMIC_WEIGHT_REFRESH_SECONDS` (default `300`).
- **`agents/ceo_agent.py`**: `CEOAgent.__init__` gains optional
  `journal=None`. New `_effective_weights()` blends each agent's
  static `WEIGHTS` entry toward its measured win-rate (via §27's
  `get_agent_performance()`) once it has `>= DYNAMIC_WEIGHT_MIN_SAMPLES`
  closed trades; always renormalizes to sum to 1.0; falls back to
  static weights on any error, disabled flag, or missing journal.
  `CEODecision` gains `weights_used: dict`.

### Compatibility
Off by default — `journal=None` (unchanged default) or
`DYNAMIC_AGENT_WEIGHTS_ENABLED=False` (default) both make this fully
inert. No changes to `journal/journal_v2.py`, `execution/execution_orchestrator.py`,
or any schema.

### Testing
`pytest tests/ -q` → 1556 passed, 0 failed (1546 baseline + 10 new,
`tests/test_dynamic_agent_weights.py`). `ruff check .` → clean.

## [Unreleased] — V16 Phase 4B Step 1: Per-Agent Outcome Attribution

> Added during the Repository Stabilization phase (2026-08-02) — same
> note as above; content verified against `docs/architecture.md` §27.

### Added
- **`journal/journal_v2.py`**: `get_agent_performance(limit=500)` —
  joins `agent_decisions` to `trades` on `signal_id`; an agent is
  credited a win/loss only when its vote matched the direction actually
  traded.

### Changed
- **`main.py`** (legacy single-symbol pipeline only): `save_signal()`'s
  return value is now captured and threaded into `save_trade(rec,
  signal_id=sig_id)`; each `ceo_decision.agent_reports` entry is now
  persisted via `save_agent_decision()`, wrapped in try/except per agent.

### Discovery
The V13 schema was already shaped for this join
(`agent_decisions.signal_id`, `save_trade(signal_id=...)`) — neither
side was ever populated by the live pipeline; this was a wiring gap,
not a schema gap. Separately: `execution/execution_orchestrator.py`
(the V16 multi-symbol path) does not call the journal at all — only
the legacy single-symbol pipeline does, so this phase only wires the
path that has something to attribute to.

### Testing
`pytest tests/ -q` → 1546 passed, 0 failed (1539 baseline + 7 new,
`tests/test_agent_outcome_attribution.py`). `ruff check .` → clean.

## [Unreleased] — V16 Phase 4A: Ensemble Decision Engine (ConfidenceEngine Fusion)

> Added during the Repository Stabilization phase (2026-08-02) — same
> note as above; content verified against `docs/architecture.md` §26.

### Changed
- **`agents/ceo_agent.py`**: `CEOAgent.WEIGHTS` gains a
  `confidence_engine` key (0.15), rebalanced from
  `{smc:.30 futures:.25 regime:.20 risk:.15 journal:.10}` to
  `{smc:.25 futures:.20 regime:.15 risk:.15 journal:.10
  confidence_engine:.15}`. `confidence_result` (previously an override
  that bypassed the agent vote entirely) is now folded into the same
  weighted vote as every other agent — except a hard `BLOCKED` result,
  which still short-circuits, same precedence as the risk veto.
  `CEODecision` gains `agreement_score` (0-1); confidence is damped by
  `0.5 + 0.5*agreement_score` when the agent layer disagrees.

### Compatibility
`execution/strategy.py`, `execution/portfolio_signal_provider.py`,
`decision/confidence_engine.py`, `ranking/confidence_fusion.py` — not
modified; this phase only changes how `CEOAgent` consumes their output.

### Testing
`pytest tests/ -q` → 1539 passed, 0 failed (1533 baseline + 6 new,
`tests/test_ceo_ensemble_fusion.py`). `ruff check .` → clean.

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
