# CHANGELOG

## [Unreleased] — AI Self-Improvement Governance Layer, Phase 1

Request: let the system learn/self-tune automatically, but hold every
change for explicit human confirmation, with a log of what changed
sent to a second "review" agent that opines on whether it looks good
before the human decides. Scoped into a 6-phase roadmap (G1-G6) before
any code was written. **This is Phase 1 only: G1 (proposal record) +
G3 (deterministic Review Agent)**, plus a lane-breakdown transparency
addition surfaced during scoping. See PATCH_NOTES.md and
`docs/architecture.md` §48 for the full write-up.

### Added
- `update_proposals` table — one row per self-improvement proposal
  (model promotion, agent weight, recommendation param, strategy
  selection, or logic change). Starts empty; nothing writes to it yet
  in this phase.
- `governance/` package: `UpdateProposal` (record), `ProposalStore`
  (create/get/list/set_review/set_status — always lands `pending`),
  `compute_lane_breakdown()` (surfaces how much of a model's training
  data was real `LIVE` trades vs. the `TRAINING`/`PAPER` paper-account
  lanes — a gap found during scoping: `research/feature_store.py::
  get_training_rows()` has no lane filter at all, so every nightly
  retrain today silently mixes them with zero visibility).
- `agents/update_review_agent.py::UpdateReviewAgent` — deterministic
  (no LLM call), scores `model_promotion` proposals for real via a
  hard gate identical to `ModelRegistry.should_promote()`'s rule plus
  a weighted composite score; every other proposal type is explicitly
  left unscored (no honest metrics source for them yet) rather than
  estimated.
- 50 new tests (`tests/test_proposal_store.py`,
  `tests/test_update_review_agent.py`,
  `tests/test_lane_breakdown.py`), including a direct assertion that
  the new hard-gate logic agrees with a real `ModelRegistry.
  should_promote()` call.
- 7 new `REVIEW_SCORE_*`/`REVIEW_MIN_SAMPLE_SIZE` settings in
  `config/settings.py` for the Review Agent's scoring rubric.

### Changed
Nothing. This phase is 100% additive — no existing table, setting,
function signature, or behavior was modified. See MIGRATION.md.

### Known follow-up
G2 (wire `run_nightly_retrain()` to actually create a proposal instead
of auto-promoting directly) and G4 (dashboard approval UI) are the
next phase and ship together — not part of this delivery. `ml/
learning_mode.py::run_nightly_retrain()` still auto-promotes exactly
as before this phase.

## [Unreleased] — Training Lane Restore-on-Restart

Root cause: `TrainingLaneRunner._new_engine()` always built a fresh
$100 `PaperAccount` with no loading from anywhere — every process
restart threw the whole background training lane's state away,
including silently dropping any genuinely open position's eventual
WIN/LOSS outcome (never captured, no error, no log). See
`PATCH_NOTES.md` for the full writeup, including a real bug this
phase's own tests caught in `PaperAccount.from_state_dict()` before
delivery (an early version still raised on a corrupted saved value
despite documenting "never raises").

### Added
- `paper/paper_account.py`, `paper/paper_position.py`,
  `paper/paper_execution.py` — `to_state_dict()`/`from_state_dict()` on
  each, for full-fidelity persistence/restore.
- `database/schema_v13.sql` — `+training_lane_state` table (single-row
  JSON blob).
- `training_lane/state_store.py` (new) — persistence layer + singleton
  accessor, mirrors `get_dataset_builder()`/`get_trade_journal_v2()`'s
  pattern.
- `training_lane_runner.py` — restores at construction, saves every
  cycle (not just on graceful stop — this project's restarts have more
  often looked like a closed terminal than a clean Ctrl+C). New
  `status()` field: `restored_from_prior_run`.
- 21 new tests (13 in `tests/test_training_lane_runner.py`, 8 in new
  `tests/test_training_lane_state_store.py`).

### Changed
- Nothing existing modified in meaning — restore/save is additive
  on top of the lane's existing behavior; a restore problem of any kind
  falls back to exactly what happened before this phase (a fresh
  account), never a hard failure.
- Also fixed, found while writing this phase's own tests: a
  cross-test-contamination bug in `tests/test_training_lane_runner.py`'s
  `_make_runner()` helper (no `state_store` isolation existed before
  this phase needed one) — every pre-existing test in that file was
  re-verified passing after the fix.

## [Unreleased] — Multi-Symbol Rotation for the Background Training Lane

Root cause: `training_lane/training_lane_runner.py`'s background paper-
training lane (PR #76/#78) traded exactly one hardcoded symbol
(`settings.SYMBOL`) forever, while the live `portfolio_signal_provider`
lane trades across the full ~527-symbol scanner universe — a real
train/serve mismatch for any model eventually trained on this lane's
data. Fixing the training lane's own symbol-selection logic wasn't
sufficient on its own: `paper/paper_execution.py`'s
`PaperExecutionEngine.execute()` separately hardcoded
`symbol=settings.SYMBOL` on every position it opened, ignoring whatever
symbol the caller asked for — found by reading `execute()`'s body
directly before writing any fix. See `PATCH_NOTES.md` for the full
writeup.

### Added
- `paper/paper_execution.py` — `execute()` gains an optional `symbol=`
  parameter (defaults to `settings.SYMBOL`, so every existing caller is
  unaffected).
- `training_lane/training_lane_runner.py` — `_select_symbol()`
  round-robins through scanner-ranked candidates when
  `BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED` is on; rotation only ever
  happens while flat, never mid-position.
- `config/settings.py` — `BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED`
  (default `false`), `BACKGROUND_TRAINING_SYMBOL_POOL_SIZE` (default `10`).
- 34 new tests (`tests/test_training_lane_runner.py`).

### Changed
- Nothing existing modified in meaning. Every new flag defaults to
  preserving today's exact behavior; `execute()`'s new parameter is
  optional and defaults to the prior hardcoded value.

## [Unreleased] — Training-Lane Visibility + Boot-Enabled 24/7 Background Training

Reported symptom: Train Monitor showing every row `BLOCKED`. Traced
against a real production run.bat log: correct behavior — the real
RiskEngine circuit breaker had tripped (3 consecutive losses), and
Train Monitor's Scanner Decision Log panel was accurately reporting
the *live* scanner's blocked cycles. The actual gap: Phase 4C Track C's
background paper-training engine (`training_lane/training_lane_runner.py`,
PR #76) already runs fully independent of that circuit breaker, resets
its isolated $100 account immediately on bust, and labels the bust
event for training — but it defaulted to disabled, and nothing on the
dashboard showed it was alive even when running. See PATCH_NOTES.md
for the full root-cause trace and file-by-file breakdown.

### Added
- `TrainingLaneRunner.status()` — read-only snapshot (balance, bust
  count, open position, last closed trade), reading only
  already-lock-protected properties.
- `GET /api/training-lane/status` — same "always 200, `enabled` flag
  tells the story" contract as `/api/paper`.
- Train Monitor dashboard: "Background Training Lane (Track C)" panel,
  polled every 20s, showing live training-lane state independent of
  the live scanner's blocked/unblocked status.
- 6 new backend tests (`tests/test_training_lane_runner.py::TestStatus`,
  `tests/test_api.py::TestTrainingLane`).

### Changed
- **`BACKGROUND_PAPER_TRAINING_ENABLED` now defaults to `true`**
  (was `false`) — training now starts automatically on boot rather
  than requiring a manual `.env` edit, per explicit request that it
  run "24/7 whenever the system is opened." See MIGRATION.md to
  restore the previous opt-in-only behavior.
- `main.py::_start_api_server()` gained a `training_lane_runner`
  parameter (additive; every existing parameter unchanged) so the API
  layer can report the lane's real state instead of always answering
  "disabled."
- `tests/test_training_lane_runner.py::TestBootFlag` — two tests
  rewritten for the new default; the old flag-off-only guard test
  never actually exercised its own flag-on branch (old default made
  that branch dead code) — its replacement exercises both directions.
  See MIGRATION.md's closing note.



Root cause: `MarketScanner`/`OpportunityRanker` discover candidates
across the full ~527-symbol Binance USDT-perpetual universe, but
`ExecutionCoordinator.get_manager()` rejected any symbol outside
`settings.symbol_list` (single symbol by default) with a `ValueError`
— 37 occurrences across a 30-hour production log
(`ZROUSDT`/`ESPUSDT`/`ARBUSDT`/`XLMUSDT`/`SUIUSDT`/`LINKUSDT`/`ENAUSDT`).
Traced the full candidate-to-execution flow before fixing: confirmed no
closer/safer choke point exists — `alloc.symbol` flows straight from
the ranker's full universe to `ExecutionCoordinator`, which was always
the only symbol-validation point. See PATCH_NOTES.md for the full
writeup, including the explicit unboundedness decision (added a cap;
`PORTFOLIO_MAX_POSITIONS` does not provide one, since it bounds
concurrent positions, not cumulative distinct symbols over a
long-running process).

### Added
- `ExecutionCoordinator.__init__`'s `allow_dynamic_symbols` (default
  `False`) and `max_dynamic_symbols` (default `50`) parameters.
- `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS` / `EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS`
  settings, matching `SCANNER_ENABLED`-style convention.
- 13 new tests across `tests/test_execution_coordinator.py` (including
  two concurrency/race tests) and `tests/test_execution_factory.py`.

### Changed
- `execution/execution_factory.py` wires the two new settings through
  to `ExecutionCoordinator`. Default behavior unchanged for every
  existing deployment.

## [Unreleased] — Fix: Dangling `signals_pre_w14_2d_1` FK Breaks Trade Journaling

Root cause: `database/migrations/migration_001_execution_lane_backfill.py`
processed `trades` before `signals` in `_LANE_TABLES`. SQLite's `ALTER
TABLE ... RENAME TO` automatically rewrites every other table's stored
FK clauses that reference the table being renamed — so when `signals`
was rebuilt after `trades` already had a fresh FK, that fresh clause
was silently rewritten to reference the temp rename name, which gets
dropped moments later. Every trade insert with a non-null `signal_id`
then failed with `sqlite3.OperationalError: no such table:
main.signals_pre_w14_2d_1`. `ai_explanations` (same FK shape, not even
in `_LANE_TABLES`) was corrupted by the identical side effect. See
`PATCH_NOTES.md` for the full root-cause writeup, including an
important interaction: repairing one table can itself corrupt another
table that references it (repairing `ai_explanations` initially broke
`trades.explanation_id`'s already-fixed clause) — the repair pass
iterates to a fixed point to handle this.

### Added
- `database/migrations/migration_002_repair_dangling_signals_fk.py` —
  standalone, dry-run-by-default operator script for inspecting/repairing
  a database on demand. Deliberately not registered in
  `runner.py`'s automatic boot sequence.
- `_find_dangling_fk_tables()` / `_repair_dangling_fks()` /
  `_rebuild_table()` in `migration_001_execution_lane_backfill.py`.
- 11 new tests across
  `tests/test_migration_001_fk_repair.py` and
  `tests/test_migration_002_repair_dangling_signals_fk.py`.

### Changed
- `_LANE_TABLES` reordered so `signals` rebuilds first — prevents this
  specific corruption for any fresh application of this migration
  going forward. Kept alongside (not instead of) the generic repair
  pass, since reordering alone can't cover `ai_explanations`.
- `migrate()`'s report dict gains an `fk_repairs` key.

## [Unreleased] — Fix: Live Account Balance Reads 0.00 USDT (Blocks Every Trade)

Root cause: `data/binance_provider.py`'s `get_account_balance()`
silently `return 0.0` with no log line at any level whenever
`trade_client.balance()`'s response contained no `"USDT"` entry —
indistinguishable in `logs/brain_bot.log` from a genuinely empty
account. This was the cause of every live order the bot ever attempted
being skipped by `execution/trade_manager.py`'s `minQty` guard (411
occurrences of `Invalid qty=0.0` in a single 10MB production log,
covering 30+ hours of correctly-generated 60–77%-confidence LONG/SHORT
decisions). `trade_manager.py`'s rounding/refusal logic itself was
confirmed correct and untouched — the bug is entirely upstream, in how
balance is obtained. See `PATCH_NOTES.md` for the full writeup,
including why this phase deliberately stops short of identifying
*which* of 5 candidate causes it is (no Binance network path from this
sandbox — requires Kaew to run the new diagnostic script against the
live account).

### Added
- `scripts/diagnose_balance.py` — standalone operator script (first
  file in a new `scripts/` directory). Prints resolved environment
  (`EXECUTION_MODE`, `BINANCE_TESTNET`, `base_url`, active API key
  alias) and the full raw `trade_client.balance()` response, with
  analysis pointing at which of 5 candidate root causes it matches.
- 3 new tests (`tests/test_balance_zero_diagnostics.py`).

### Changed
- `data/binance_provider.py`'s `get_account_balance()`: the silent
  zero-balance fallback now logs a `WARNING` (asset names only, never
  balance figures). The success-path log promoted from `DEBUG` to
  `INFO`. No control-flow change — same return values, same exceptions.

## [Unreleased] — V16 Phase 4C: Symbol-Aware SMC/OI Regime Strategy Adapter

Root cause: `execution/strategy.py`'s `SMC_OI_Regime_Strategy.generate_signal()`
calls `data_provider.get_all_market_data()`, which has no symbol
argument and always reflects the single globally-configured symbol —
the only thing that made this strategy unsafe to select for
`ExecutionScheduler`'s multi-symbol path (see `docs/architecture.md`
§25's "Scope boundary"). `data/binance_provider.py`'s
`get_market_data_for(symbol)` already returns an identical-shape dict
per arbitrary symbol; the rest of the pipeline it drives was already
symbol-agnostic. See `PATCH_NOTES.md` for the full writeup, including
one correction made to the original phase brief (`RegimeEngine.classify()`
needs an explicit `symbol=` to activate its per-symbol HMM cache — a
literal copy of the legacy call site would have silently pooled every
symbol onto one shared model).

### Added
- `execution/smc_oi_regime_multi.py` — `SMCOIRegimeMultiAdapter`, a new
  symbol-aware `SignalProvider` wrapping the same
  `BrainDecisionEngine`/`RegimeEngine`/`SMCEngine`/`VolumeEngine`
  pipeline `SMC_OI_Regime_Strategy` uses, but per-symbol.
- `execution/strategy_registry.py` — new `"smc_oi_regime_multi"` entry
  (`STRATEGY_NAME=smc_oi_regime_multi` to opt in). Safe for
  `ExecutionScheduler`'s multi-symbol path, unlike the existing
  `"smc_oi_regime"`.
- 21 new tests (`tests/test_smc_oi_regime_multi.py`).

### Changed
- Nothing existing modified. `"smc_oi_regime"` /
  `SMC_OI_Regime_Strategy` / `STRATEGY_NAME`'s default
  (`"portfolio_signal_provider"`) are all unchanged.

## [Unreleased] — V16 Phase 4C: Dashboard Session Persistence

Root cause: the dashboard's session Bearer JWT is held in browser JS
memory only, by deliberate design (never localStorage/sessionStorage,
to stop XSS-based theft of a long-lived session — see
dashboard_src/src/lib/api.ts's own docstring). A page refresh always
wiped it, and nothing existed to restore a session afterward, forcing
the operator to re-enter their API key on every refresh. See
PATCH_NOTES.md for the full writeup. Delivered as a companion to, but
independent from, a separate database-migration phase/bundle
(unrelated root cause, merged as PR #66). Rebased onto current `main`
after two more rounds of upstream merges during this phase (PR #67-69);
PR #67 (WS auth + proactive token rotation) touches the same file —
see PATCH_NOTES.md's "`main` moved twice" section for how the two were
integrated.

### Added
- `api/auth.py` — a separate, longer-lived refresh token, delivered
  ONLY as an httpOnly cookie (unreadable by page JS, XSS included).
  Rotates on every use (single-use per silent re-auth). `typ` claim
  cross-checked both directions so a bearer token and a refresh token
  can never be used as each other.
- `POST /api/auth/session` — silently exchanges the refresh cookie for
  a fresh bearer token; the dashboard calls this once on page load.
- `POST /api/auth/logout` — now actually revokes the session
  server-side (cookie + bearer token), not just local frontend state.
- `config/settings.py` / `.env.example` — `JWT_REFRESH_EXPIRY_DAYS`
  (default 7), `COOKIE_SECURE` (default true; false only for local
  http:// dev).
- `dashboard_src/src/lib/api.ts::restoreSession()` — called once on app
  mount (`Layout.tsx`); never throws, resolves false when there's
  nothing to restore (the ordinary case). Integrated with PR #67's
  proactive-rotation/WS-reconnect system (`_scheduleRotate()`,
  `_notifyAuthChange('login')`) so a restored session behaves exactly
  like a freshly logged-in one.
- 12 new backend tests (`tests/test_api_auth.py::TestRefreshTokenSessionPersistence`),
  11 new frontend tests (10 in `src/lib/tests/api.test.ts`, 1 added to
  PR #67's own `api.auth.test.ts` proving the WS-reconnect integration).

### Changed
- `dashboard_src/src/lib/api.ts` — `login()`/`logout()` now use
  `credentials: 'include'`; `logout()` also revokes server-side.
- `dashboard_src/src/components/auth/LoginModal.tsx` — copy updated to
  match: the API key itself is still never stored, the session now is
  (securely, revocably).

### Removed
- `api/auth.py::issue_token_for_api_key()` — superseded by
  `issue_login_session()`. Confirmed zero other callers/test references
  before removing.

### Not in scope for this phase
- The database schema-migration issue (separate phase/bundle).
- Refresh-token reuse-detection/breach-alerting, CSRF tokens on the two
  new endpoints (reasoned through — SameSite=Lax + no credentialed CORS
  already covers the realistic attack surface), split-origin deployment
  support. See PATCH_NOTES.md's "What this does not do".

## [Unreleased] — V16 Phase 4C: Automatic Migration Runner

Existing production database files created before W14-2D-1 never
received the `execution_lane` column that phase added, because
`database/db.py::_apply_schema()`'s `CREATE TABLE IF NOT EXISTS` is a
no-op against tables that already exist, and nothing ever called the
migration that was written for exactly this case
(`migration_001_execution_lane_backfill.py`). First write from
`TradeJournalV2` against such a file raised
`sqlite3.OperationalError: no such column: execution_lane` — matches
the known `monitor_open_trades()` / `daily_report()` failures. See
`PATCH_NOTES.md` for the full root-cause writeup.

### Added
- `database/migrations/runner.py` — ordered migration registry;
  `run_pending_migrations()` runs every registered migration, in
  order, idempotently, against `database.db.get_db_path()` by default.
  Raises on real failure rather than starting live trading against a
  database in an unknown schema state. CLI:
  `python -m database.migrations.runner [db_path]`.
- `tests/test_migration_runner.py` — 7 new tests (registry shape,
  legacy-file migration, idempotency across repeated boots, fresh-file
  no-op, default path resolution, failure propagation).

### Changed
- `main.py::build_system()` — new `[0/9]` step calls
  `run_pending_migrations()` before any component opens the database
  file. No existing step renumbered, reordered, or modified.

### Not in scope for this phase
- Dashboard refresh forcing re-login — separate, unrelated root cause
  (in-memory-only bearer JWT by design, not a database issue).
- Legacy `TradeJournal` V1 (`analytics/trade_journal.py`) and
  `world/readers/base.py::SQLiteSource` both still use raw
  `sqlite3.connect()`, bypassing `database/db.py`'s WAL/lock
  protections — flagged, not fixed this phase.

## [Unreleased] — Track B: Train Monitor Dashboard Tab

New "Train Monitor" tab (`/train`) for checking ML training results
and confirming the system is still training normally. See
`PATCH_NOTES.md` for full detail.

### Added
- `dashboard_src/src/pages/TrainMonitor.tsx` — model version/training
  history per model type (meta_label / confidence_calibrator /
  outcome_predictor), currently-active model detail, last-prediction
  detail, dataset row counts + session-local growth counter.
- `dashboard_src/src/lib/trainMonitor.ts::computeRowsGrowth()` — new,
  additive, pure, tested.
- `dashboard_src/src/lib/tests/trainMonitor.test.ts` — 5 new cases.
- `dashboard_src/src/types/api.ts::MLModelsData` — new, additive type
  mirroring the existing (previously frontend-unused)
  `GET /api/ml/models` response.

### Changed
- `App.tsx` — new `/train` route.
- `components/layout/Layout.tsx` — new "Train Monitor" nav entry.

No backend routes added or changed. No existing frontend export
modified.

## [Unreleased] — Track B: LifecycleControl Unauthorized-State Visibility Fix

Reactive UI bugfix. An unauthenticated viewer's START/STOP/LOGIN
control in the Command Center header rendered as a muted, `cursor-wait`
"…" with no visible affordance that it was clickable — it was, and
correctly opened the login modal, but nothing on screen invited the
click. See `PATCH_NOTES.md` for full root-cause detail.

### Added
- `dashboard_src/src/lib/lifecycleControl.ts::lifecycleButtonDisplay()`
  — new, additive pure function deciding the button's visible
  label/tone; fully decoupled from `lifecycleButtonSpec()` while
  unauthorized (always `{label:'LOGIN', tone:'login'}`), identical to
  `spec` once authorized.
- `dashboard_src/src/lib/tests/lifecycleButtonDisplay.test.ts` — 7 new
  cases.

### Changed
- `dashboard_src/src/components/commander/LifecycleControl.tsx` —
  button now renders from `lifecycleButtonDisplay()`; added a `login`
  tone to `TONE_CLASS` (accent-blue, no `cursor-wait`).

## [Unreleased] — V16 W14-2D-1: Execution-Lane Data Model

Every journal/dataset table had zero concept of which execution context
(live money vs. paper/training simulation) produced a row, and the
training-dataset export path pulled every row with no filter — meaning
a real live trade and a simulated one were indistinguishable at the
data layer. See `docs/architecture.md` §40 for the full root-cause
writeup and file-level detail.

### Added
- `execution_lane TEXT NOT NULL CHECK(... IN ('LIVE','TRAINING','PAPER'))`
  on `trades`, `signals`, `agent_decisions`, `feature_rows`,
  `ml_predictions`, `order_timeline_history` — no SQL `DEFAULT` on any
  of them.
- New append-only `execution_events` table + `journal/journal_v2.py
  ::record_execution_event()` / `get_execution_events()` — immutable
  audit trail; corrections are new rows via `correction_of`, never an
  `UPDATE`/`DELETE` (statically enforced by a repo-wide grep test).
- `config/settings.py::EXECUTION_LANE` — derived once from the existing
  `EXECUTION_MODE` (`live`/`testnet`→`LIVE`, `paper`→`TRAINING`,
  unrecognized→`TRAINING` fail-safe).
- `database/migrations/migration_001_execution_lane_backfill.py` —
  idempotent migration for pre-existing database files; backfills
  historical rows to `LIVE` (approved: all historical data predates any
  dual-lane concept and was real money), parsed directly from
  `schema_v13.sql`'s own target schema so there's no drift risk.
- `tests/test_execution_lane_contract.py` — 45 new tests covering the
  full contract.

### Changed
- `journal/journal_v2.py::save_trade/save_signal/save_agent_decision` —
  `execution_lane` is now a required parameter (no default; omitting it
  is a `TypeError`, never a silent `LIVE`).
- `execution/execution_orchestrator.py::ExecutionOrchestrator`,
  `execution/ceo_gated_signal_provider.py::CEOGatedSignalProvider`,
  `execution/order_timeline.py::OrderTimeline` — all require
  `execution_lane` at construction; `main.py` passes `EXECUTION_LANE`
  explicitly at every real call site.
- `research/feature_store.py::FeatureStore.save_row`,
  `research/dataset_builder.py::DatasetBuilder.capture_closed_mission`,
  `ml/ml_advisor.py::MLAdvisor.advise` — same required-argument
  contract.

### Scope boundary
No changes to `agents/`, `decision/`, `risk/`,
`portfolio/portfolio_manager.py`, order sizing/SL/TP/strategy logic,
Binance order-placement behavior, W14-0 START/STOP lifecycle, or
authentication (verified by `git diff` against those paths, not
assumed). `EXECUTION_MODE` still selects exactly one engine per
process, unchanged — concurrent LIVE+TRAINING runtime, the training
scheduler, and dashboard visibility remain W14-2D-2 through W14-2D-9.
Not pushed, no PR opened, not merged.
## [Unreleased] — V16 Phase 4C Track A: Agent Performance Attribution Unification

Post-Step-8-audit gap fix. `journal_v2.get_trade_attribution()` already
reads agent attribution from either the `agent_decisions` signal_id
join (Step 7C) or W14-2A's explicit `trades.extra_data.attribution.agent_attribution`
list, explicit-wins-if-present. `journal_v2.get_agent_performance()`
was never updated to match — it only ever ran the signal_id join, so
every trade attributed through W14-2A's default-execution-loop path
contributed zero rows to it. Reproduced live before fixing: 7 agents
via `get_trade_attribution()`, 0 rows via `get_agent_performance()` for
the identical trade. See `docs/architecture.md` §41 for the full
root-cause writeup and a note on the parallel implementation this
entry defers to.

### Fixed
- **`journal/journal_v2.py::get_agent_performance()`** (landed via PR #58,
  commit `30f0f72`) — now aggregates from both attribution sources by
  calling `get_trade_attribution()` per closed trade and reusing
  whichever `agent_participation` it returns, so a trade is never
  credited twice. Return shape, field names, rounding, ordering, and
  `limit` semantics unchanged — every pre-existing test for this
  method passes unmodified. Unblocks `agents/ceo_agent.py`'s
  `DYNAMIC_AGENT_WEIGHTS_ENABLED` blend and
  `knowledge_engine/agent_knowledge.py` (Step 8) from silently seeing
  zero data for trades taken through the default (non-multi-symbol)
  execution loop. Test coverage: `tests/test_agent_performance_attribution.py`
  (8 tests).

### Known follow-up (not in scope here, documented not fixed)
- The two attribution sources use different agent-identifier strings
  by design (join path: `save_agent_decision()`'s raw name, e.g.
  `"CEO_AGENT"`; explicit path: `CEOAgent.WEIGHTS` keys, e.g. `"ceo"`).
  Not unified — would be a second attribution format, out of scope.
- `knowledge_engine/`'s own ingestion step remains unwired to any
  scheduler (by design, per §36) — this fix makes its agent-performance
  data source correct once ingestion does run, it does not wire
  ingestion itself.
- Recommendation→trade-outcome causal linkage and cross-symbol HMM
  contamination remain open, separate, unaddressed gaps (see prior
  Track A audit).

## [Unreleased] — V16 W14-2B: Bundle Manager Working-Tree Isolation Fix

`cmd_import`'s real pass saves `bundle_history.json` unconditionally
once per batch (correct — see `docs/architecture.md` §21/§39 and
`tools/history.py`), including for failed-only outcomes (a legitimate
audit-trail write). Left uncommitted, that write lingered as a dirty
tracked file and tripped the *existing* preflight dirty-tree guard
(PR #36) on every subsequent `cmd_import` invocation — including for
entirely unrelated bundles — until a human committed it by hand. The
tool was locking itself out with its own prior output.

### Fixed
- **Bundle Manager working-tree isolation** — `cmd_import`'s real pass
  now locally commits `bundle_history.json` (that file only, never
  pushed) immediately after `history.save()`, returning to
  `base_branch` first so the commit lands on trunk rather than on
  whichever feature branch the last bundle in the batch happened to
  leave checked out. New setting `BUNDLE_AUTO_COMMIT_HISTORY` (default
  `true`) gates this; set `false` to restore the exact pre-fix manual
  `git add && git commit` workflow. The dry-run/preview pass, `sync`,
  and `history` subcommands were already fully read-only with respect
  to history and needed no change (verified by inspection, not
  assumed). See `docs/architecture.md` §39 for the full root-cause
  writeup.

### Added
- `tools/git_utils.py:commit_paths()` — scoped `git add` + conditional
  `git commit`, no-op if nothing was actually staged.
- `tests/test_bundle_manager_git_utils.py::TestCommitPaths`,
  `tests/test_bundle_manager_cli.py::TestCommitHistoryFileWiring`,
  `::TestReturnToBaseBranch` — mocked unit coverage of the new helper
  and its wiring into `cmd_import`.
- `tests/test_bundle_manager_worktree_isolation.py` — real local git
  repositories in `tmp_path` (no mocking), proving the working tree
  stays clean end-to-end, including the literal regression case: an
  unrelated, valid bundle is no longer blocked by an earlier failure.

## [Unreleased] — $20 Live-Money Safety Patch (Track A)

Read-only GO/NO-GO audit (fresh clone @ `c564985`) found three ways a
low-capital account's real risk/margin exposure could exceed its
configured policy. This patch fixes exactly those three, and nothing
else — no strategy, CEO/agent, risk-policy-value, dashboard, WebSocket,
EventBus, OrderTimeline, or reconciliation code was touched.

### Fixed
- **Live/testnet configuration invariant** — `EXECUTION_MODE` and
  `settings.BINANCE_TESTNET` previously could disagree
  (`EXECUTION_MODE=testnet` + `BINANCE_TESTNET=false` could reach
  Binance **mainnet**; `EXECUTION_MODE=live` + `BINANCE_TESTNET=true`
  could silently run on testnet). `BinanceDataProvider.__init__` now
  refuses to start with a clear `RuntimeError` (no credentials
  included) whenever `testnet`/`live` mode and the testnet flag
  disagree. Paper mode is unconstrained, matching prior behavior.
- **Minimum-quantity safety behavior** — `TradeManager.calculate_position_size()`
  previously clamped a risk/margin-derived quantity **up** to the
  exchange's `LOT_SIZE` `minQty` whenever it floored below that
  minimum, silently letting exposure exceed `RISK_PER_TRADE_MAX` /
  `MAX_MARGIN_USAGE`. It now returns `0.0` (skip trade) instead,
  reusing the existing "cannot size" convention already handled by
  `execute_trade()`. `_round_qty()` itself is unchanged and still used
  to format already-approved quantities for SL/TP orders.
- **Minimum-notional preflight** — no proactive check against the
  exchange's `MIN_NOTIONAL`/`NOTIONAL` filter existed; the system
  relied entirely on Binance rejecting an under-notional order at
  submission time. `calculate_position_size()` now validates locally
  before ever calling `place_market_order()`, and fails closed (skips
  the trade) if the filter is missing or unparseable rather than
  guessing a value.

### Added
- `tests/test_live_money_safety.py` — 29 regression/safety tests
  covering the quantity-skip matrix, the full
  `EXECUTION_MODE`×`BINANCE_TESTNET` matrix, min-notional edge cases,
  a strategy/CEO non-interference guard, and an offline $20 pre-flight
  simulation. No test submits or can submit a real Binance order.

## [Unreleased] — V16 Phase 4C Step 7: Per-Agent Vote Persistence for CEO-Gated Decisions (Track A)

Roadmap-level audit (post-Step-6) found `docs/ROADMAP.md`'s "Planned"
backlog item "Per-agent attribution for CEO-gated multi-symbol
trades — agent votes still aren't persisted for that path" to be
genuinely open (unlike two neighboring backlog items this same audit
found stale/already-done: "Phase 4C Step 2+", closed by Steps 3-6, and
"pass symbol= to RegimeEngine.classify()", closed back in Phase 4B
Step 3C). This phase closes the genuinely-open part of it.

**Audit finding (important, corrects a stale docstring):**
`journal_v2.get_trade_attribution()`'s own docstring says "the
pipeline doesn't run the agent layer" for V16 multi-symbol trades —
accurate for the *plain* `execution/portfolio_signal_provider.py`
path (which indeed never touches `CEOAgent`), but this phase's
fresh-clone trace confirms it is **not** accurate for the CEO-gated
path: `agents/ceo_symbol_cache.py::CEOAgentSymbolCache.get_ceo_agent()`
builds a real, full 6-agent layer per symbol (`build_agent_layer()`),
and `CEODecision.agent_reports`/`.weights_used` are genuinely
populated on every CEO-gated multi-symbol decision. The real gap was
purely that `execution/ceo_gated_signal_provider.py::_journal_ceo_decision()`
never carried that already-computed data into the journal — the exact
same shape of gap Step 6 closed for `recommendation_explanations`.

### Added
- `execution/ceo_gated_signal_provider.py`: `_journal_ceo_decision()`
  additively carries `agent_reports` and `weights_used` (both already
  computed by `CEOAgent.decide()`, nothing recalculated) into the same
  `details` dict `reasons`/`agreement_score`/`direction`/
  `recommendation_explanations` already go through. Same try/except,
  same failure isolation, same `/api/ceo-decisions` reachability, zero
  new architecture.
- 12 new regression tests (`tests/test_ceo_agent_vote_persistence.py`),
  run against the real live chain (`CEOGatedSignalProvider` → real
  `MultiSymbolCEODispatcher`/`CEOAgentSymbolCache` with a real 6-agent
  layer, not a fake). Includes an explicit regression test asserting
  the agent layer genuinely runs for this path (guards against a
  future change silently making this phase's premise false), and the
  genuinely-empty-`agents={}` case journaling cleanly rather than
  erroring.

### Known follow-up work (explicitly NOT done in this phase)
This makes per-agent votes inspectable **per decision cycle** via the
existing `/api/ceo-decisions` — it does **not** make
`journal_v2.get_trade_attribution()`'s `agent_participation` populate
for these trades. That join is `trades.signal_id ==
agent_decisions.signal_id`; `_journal_ceo_decision()` has never
recorded a `signal_id` (every `save_agent_decision()` call here omits
it, before and after this phase). Threading a shared `signal_id` from
this signal-layer class through to
`execution/execution_orchestrator.py`'s `save_trade(rec,
signal_id=sig_id)` call — a separate write, in a different layer, at
trade-open time rather than decision-cycle time — is a larger,
cross-layer piece of work this phase's audit found but deliberately
did not attempt, to stay within a minimal, single-file, additive
patch. Flagged for its own future audit rather than attempted here
under time/risk pressure.

## [Unreleased] — V16 Phase 4C Step 6: Live Recommendation Explanation Persistence (Track A)

Closes the observability gap this phase's own fresh-clone audit found:
`CEOAgent.decide_with_recommendations()` / `decide_from_context_with_recommendations()`
already computed the full per-recommendation
`AppliedRecommendationExplanation` list (Phase 4C Step 3's own Part C
deliverable — recommendation id, applied/skipped, skip reason, score,
sample size, source pattern, effect) on every live decision cycle, but
discarded it before returning — both methods' return type is a bare
`CEODecision`, not a tuple. Only one aggregate line
(`"[learning] applied N recommendation(s), confidence ±X.XX"`)
survived, folded into `decision.reasons`. Every individual
recommendation's detail, and every skip reason, was lost the instant
the method returned.

**Audit note:** the fresh-clone trace confirmed persistence
infrastructure already existed and already worked —
`execution/ceo_gated_signal_provider.py::_journal_ceo_decision()` was
already the one place a live `CEODecision` gets journaled, into an
existing `details` dict (`reasons`/`agreement_score`/`direction`), via
the existing `journal_v2.save_agent_decision()` →
`get_agent_decisions()` round trip, already surfaced unmodified by the
existing `GET /api/ceo-decisions`. The gap really was just forwarding
— no new table, no new journal, no new endpoint, no new EventBus
event.

### Added
- `agents/ceo_agent.py`: `CEODecision` gains a
  `recommendation_explanations` field (`list`, empty-list default —
  every pre-existing construction site, and `decide()`/
  `decide_from_context()`, are unaffected). `decide_with_recommendations()`
  and `decide_from_context_with_recommendations()` now attach the
  already-computed explanations onto the returned decision via
  `dataclasses.replace()` (never mutates the original) instead of
  discarding them.
- `execution/ceo_gated_signal_provider.py`: `_journal_ceo_decision()`
  additively carries `recommendation_explanations` (serialized via
  `AppliedRecommendationExplanation.to_dict()`, already existing —
  nothing recalculated) into the same `details` dict it already builds.
  Still wrapped in the same pre-existing try/except — a persistence
  failure still cannot break a live decision cycle.
- `api/app.py`: docstring-only update to `/api/ceo-decisions`
  documenting the new `details.recommendation_explanations` key. No
  functional change — the endpoint already returned `details`
  unmodified.
- 14 new regression tests
  (`tests/test_recommendation_explanation_persistence.py`), run against
  the real live chain (`CEOGatedSignalProvider` → real
  `MultiSymbolCEODispatcher`/`MultiSymbolCEOAdapter`/`CEOAgentSymbolCache`
  → journal, not a low-level helper in isolation): applied and skipped
  explanations both persist with their real fields, multiple
  recommendations survive without collapsing into the aggregate line,
  `RECOMMENDATION_APPLICATION_ENABLED=false` and no-recommendation
  paths remain empty-list/unchanged, BLOCKED decision values
  (`action`/`direction`/`score_breakdown`/`agreement_score`) remain
  byte-identical even though explanations are attached (attaching data
  doesn't require object-identity preservation, only value-identity —
  verified explicitly), journal-write failure isolation, and backward
  compatibility (pre-Step-6 `CEODecision` construction and journal
  records without this key remain valid, nothing is backfilled on
  read).

### Not changed
No new architecture — no second recommendation engine, journal,
EventBus, database, scheduler, or API namespace.
`recommendation_scoring.py`, `recommendation_advisor.py`,
`recommendation_context.py`, and `recommendation_service.py` are
untouched; the scoring formula, its weights,
`RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT`, CEO decision authority,
`decide()`, `decide_from_context()`, and every existing safety
invariant are unmodified — verified via the full pre-existing suite
passing unchanged (2284 → 2298 in `tests/`, exactly +14; 565 → 565 in
`world/tests/`, zero pre-existing test modified).

## [Unreleased] — Track C3 Phase 2: Ghost Detection, Timeline Cross-Check & Reconciliation Metrics (Track A)

Fresh-clone gap audit against `main` at `830d10d` (post W13-CI-1) found
the runtime-ghost-position bug this phase was originally scoped to fix
(`ReconciliationEngine._read_bot()` mirroring exchange state in live
mode instead of reading `PortfolioState` independently) was **already
fixed** — merged as PR #35, V16 Phase ORDER-01 — and confirmed
byte-identical, unmodified, on this baseline. Degraded-exchange safety
(`OrderState.UNKNOWN` short-circuit before any GHOST/DESYNC logic) was
independently verified correct and was likewise left untouched. No
duplicate `ReconciliationEngine`, `RecoveryEngine`, `OrderManager`,
World runtime, WebSocket transport, or command-dispatch system was
created; every existing authority is reused exactly as-is.

Four genuine, narrow gaps remained and are what this phase adds:

1. `execution/order_timeline.py`'s `OrderTimeline` (C3-1) had exactly
   one consumer anywhere in the codebase —
   `telemetry/world_export.py::orders_payload()` — and that consumer
   only *displays* `current_state()`, never cross-checks it against
   independently-verified exchange truth. A stale timeline entry
   (exchange flat, timeline's last recorded state still "OPEN") was
   structurally undetectable. New: `TIMELINE_DESYNC`.
2. `OrderStateManager`'s `GHOST`/`DESYNC` canonical states don't say
   *which* source was stale, or distinguish an orphaned real exchange
   position from a side/quantity/duplicate-journal mismatch — the data
   to do so already exists in `OrderStateSnapshot.exchange_position` /
   `.runtime_position` / `.journal_position` / `.mismatch_type`, just
   not exposed as a queryable classification. New: `GHOST_RUNTIME`,
   `GHOST_JOURNAL`, `ORPHAN_EXCHANGE`, `SIDE_MISMATCH`,
   `QUANTITY_MISMATCH` sub-classification.
3. A failed automatic recovery attempt was logged but never published
   on the event bus — silent by default. New: `RECONCILIATION_FAILED`
   event, plus `RUNTIME_POSITION_MISMATCH` (a gap `POSITION_DESYNC`
   alone doesn't cover — see module docstring's "reuse first"
   section for exactly which existing events are deliberately **not**
   duplicated) and `ORDER_TIMELINE_DESYNC`.
4. No read-only endpoint exposed recent ghost/desync/timeline-desync
   findings, and `GET /api/order-state/metrics` didn't carry any of
   this phase's counters.

### Added
- `system_health/ghost_reconciliation.py` — `GhostReconciliationMonitor`,
  a composition over `OrderStateManager` (unchanged) + `OrderTimeline`
  (unchanged), read-only. Full architecture/safety rationale, including
  which existing events are reused vs. which three are genuinely new,
  is in the module's own docstring.
- `GET /api/order-state/ghosts` — current + recent findings for a
  symbol. Read-only; runs the same read path every existing consumer
  of this data already uses, never places/cancels/modifies an order,
  never calls `refresh(force=True)`.
- `GET /api/order-state/metrics` — additively merges this phase's
  counters (`ghost_detected_count`, `orphan_exchange_count`,
  `timeline_desync_count`, `recovery_success_count`,
  `recovery_failure_count`, `reconciliation_latency_ms`,
  `timeline_sync_latency_ms`, ...) into the existing response. Every
  ORDER-01 key is unchanged.
- `config/settings.py`: `ORDER_RECONCILIATION_ENABLED` (default
  `False`), `ORDER_RECONCILIATION_INTERVAL_SECONDS` (default `60.0`),
  `ORDER_RECONCILIATION_DEDUP_SECONDS` (default `30.0`).
- `main.py`: `run_ghost_reconciliation_check()`, an optional scheduled
  job registered **only** when `ORDER_RECONCILIATION_ENABLED=True` —
  with the flag at its default, `main.py`'s scheduling behavior is
  byte-identical to before this phase.
- `tests/test_ghost_reconciliation.py` (26 tests),
  `tests/test_ghost_reconciliation_api.py` (8 tests) — classification
  for every scenario in the phase brief's test matrix, degraded-input
  handling, event-transition dedup (including a same-window
  flap-then-return case), a real measurement proving one `check()`
  cycle causes exactly one exchange read (no per-consumer fan-out),
  real-money safety (orphan exchange positions never produce a "close"
  recovery result, structurally — no close-order code path exists
  anywhere in `recovery_engine.py`), and read-only/backward-compatible
  API behavior.

### Known limitations (deliberately out of scope for this phase)
- Metrics and findings history are in-memory only, not persisted
  across a restart — same caveat `OrderStateManager.status()` already
  carries for its own counters.
- `TIMELINE_DESYNC` is detection-only; no automatic recovery action is
  attempted for it (not yet backed by a proven recovery policy in
  `RecoveryEngine` — a C3-3 candidate).
- If `ORDER_RECONCILIATION_ENABLED=True`, the optional background job
  causes one additional live `get_position_info()` call per its own
  configured interval, on top of the existing always-on 60s
  `run_position_reconciliation()` job. `ReconciliationEngine.run()` has
  no caching of its own today — this is a pre-existing characteristic
  (the same call already happens on every `GET /api/order-state`
  request), not something this phase introduces; documented here for
  operators deciding whether to enable it.

### Impact
`system_health/ghost_reconciliation.py` (new), `api/app.py`,
`main.py`, `config/settings.py` — additive only. No trading, risk,
CEO-decision, execution, `ReconciliationEngine`, `RecoveryEngine`,
`OrderTimeline`, or World-runtime code modified.
`pytest tests/ -q`: 2250 → 2284 passed (34 new, 0 removed, 0 modified).
`pytest world/tests/ -q -m ""`: 565 passed, unchanged.
`ruff check .` / `vulture . --min-confidence 80`: clean, no new
findings. `python -c "import main"`: OK.

## [Unreleased] — W13-CI-1: World Test Coverage & Dependency Hygiene

Independent post-W13 audit found `world/tests/` (565 tests, including
the 14 new W13-2 command-audit-log tests) was never actually executed
by CI: `pytest.ini`'s `testpaths = tests` excludes it from default
collection, and its files almost never carry the `unit` marker that
`addopts = -m "unit"` filters on, so even a direct
`pytest world/tests/ -q` invocation silently selected zero tests
rather than failing. Separately, 8 files under `world/tests/` (plus
`world/scripts/validate_schemas.py`) hard-import `jsonschema`, which
was never declared in `requirements.txt`.

Fresh-clone audit reproduced both exactly as reported before any fix
was written. No W13 implementation, World runtime architecture, or
trading/risk/CEO/execution code was touched.

### Fixed
- **World test CI coverage** — new `world-tests` job in
  `.github/workflows/ci.yml`, parallel to the existing `test` job,
  running `pytest world/tests/ -q -m ""`. The `-m ""` override applies
  only to this job; `pytest.ini`'s global `-m "unit"` default (relied
  on by 97 of 99 files under `tests/`) is untouched, as is the
  existing `test` job's invocation of `pytest tests/ -q`. pytest
  itself exits non-zero on zero-collected, so a future regression back
  to "0 selected" now fails the build instead of reporting green.

### Added
- `jsonschema>=4.17.0` in `requirements.txt` — genuinely required
  (hard `import jsonschema`, no try/except) by 8 world/tests files;
  added alongside the existing `pytest`/`pytest-mock` entries,
  matching this repo's convention of declaring test tooling directly
  in `requirements.txt` rather than a separate dev-requirements file.

### Impact
`requirements.txt`, `.github/workflows/ci.yml` only. No production,
World-runtime, or test-behavior code changed.
`pytest tests/ -q` (existing invocation): 2250 passed, unchanged.
`pytest world/tests/ -q -m ""` (new invocation): 565 collected, 565
passed — including all 14 W13-2 audit-log tests, verified
individually. `ruff check . --exclude dashboard_src --exclude
dashboard`: clean. `vulture . --exclude dashboard_src,dashboard,tests
--min-confidence 80`: clean. No frontend changes; no frontend CI
convention exists in this repo to run.

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
