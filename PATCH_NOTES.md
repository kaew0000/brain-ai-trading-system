# PATCH NOTES — V16 ML Extensions Integration Layer (observe-only)

Branch: `feat/ml-extensions-integration-layer`
Base: `main` @ `ac913b5` (merge of PR #82, RL/HPO/Online-Learning subpackage)

## Scope note

Requested: "สร้างต่อจาก PR ในภาพ" (continue building from the PR shown in
the screenshot — PR #82) — continuing from a supplied draft
`brain_integration_bundle.zip` as a starting point. Before writing any
code, fresh-cloned the real repo and inspected every real module the
draft's four adapters needed to call.

**Root cause: the draft bundle invented APIs that don't exist in this
repo.** It assumed a fictional `decision.ensemble_decision_engine`
(`.add_vote()`/`.resolve()`) — the real ensemble is
`agents/ceo_agent.py`'s `CEOAgent`. It assumed a fictional
`executor.submit_order()`/`.cancel_order()` — the real
`ExecutionOrchestrator.execute()` takes a full `OrchestratedDecision` +
`PortfolioState` + balance, and calling it directly from an ML signal
would bypass Scanner→Ranking→Portfolio→Risk→Decision→Execution
entirely. It assumed a generic `data_pipeline.get_ohlcv()`/`.portfolio`
dict — `ml/extensions/rl/env.py`'s `BrainTradingEnv` actually requires a
narrower, specific contract (`get_features(window)`/`reset()`/`step()`/
`get_current_price()`/`is_done()`, confirmed against that file and its
own `example.py::MockDataPipeline`). It also referenced a
config-syncing "Auto-Config Engine" that a repo-wide grep confirms does
not exist anywhere in this codebase, and assumed a `class BrainBot`
that doesn't exist (`main.py`'s `main()` is procedural). None of this
was malicious — it was written without inspecting the real repo. All
four adapters were rewritten from scratch against the real APIs.

**Key finding, confirmed by reading `CEOAgent.decide()`:** the
weighted-vote loop only ever iterates `CEOAgent.WEIGHTS` (a fixed
6-key dict). An agent registered under a 7th key still runs every
cycle (telemetry, reasoning stream, dashboard) but can never enter the
score or change the decided action — this repo already relies on
exactly this pattern for `"trader"`. Verified with a worst-case test: a
stub agent reporting `LONG` at 100% confidence, registered under
`"ml_extensions"`, changes nothing about `CEOAgent.WEIGHTS` or the
resulting action.

**Scope decision, asked rather than assumed:** wiring RL/Online/HPO
into a real trading vote or into execution means either rebalancing
`CEOAgent.WEIGHTS` or bypassing the core execution pipeline — both
carry real capital-safety weight. Presented as an explicit choice;
confirmed answer: **observe-only this phase**. Live-vote wiring is
deferred to a separate, future, human-approved phase.

Track A only (Python backend). No `dashboard_src/`/frontend changes,
no database schema changes, no changes to `ml/extensions/` itself
(PR #82's files are untouched — this layer is purely additive).

## What changed

| File | Change |
|---|---|
| `ml/extensions_integration/data_adapter.py` | New. `RLDataPipelineAdapter` — the real `BrainTradingEnv` data_pipeline contract over real OHLCV (`BinanceDataProvider.get_ohlcv()`, fetched once, walked in-memory — not called per-step). `compute_feature_frame()` — 20 deterministic pandas technical-indicator columns, matching `BrainTradingEnv`'s hardcoded `n_features=20`. |
| `ml/extensions_integration/portfolio_adapter.py` | New. `PortfolioStateAdapter` — combines real `PortfolioState` + account balance into the dict `TradingPolicy.get_action()` expects. Never raises; degrades to zeroed defaults. Documented proxy limitation (see architecture.md §53). |
| `ml/extensions_integration/ml_extensions_agent.py` | New. `MLExtensionsAgent(BaseAgent)` — observe-only, registered outside `CEOAgent.WEIGHTS`. `analyse()` never raises. |
| `ml/extensions_integration/config_bridge.py` | New. `ConfigBridge` — reuses `settings.symbol_list`; builds `ExtensionsConfig` from real settings only. |
| `ml/extensions_integration/system_integrator.py` | New. `SystemIntegrator.wire_all()` — single entry point, config-gated, non-fatal, defers all optional heavy imports so `import ml.extensions_integration` never requires gymnasium/stable-baselines3/torch/river/optuna to be installed. |
| `api/ml_extensions_api.py` | New. 5 read-only `/api/ml_extensions/*` endpoints, mirrors `api/execution_api.py`'s conventions exactly. |
| `api/app.py` | `+1` import, `+1` `include_router()` — covered by existing prefix-generic auth. |
| `main.py` | `_start_api_server()`: `+ml_extensions_components` param + `set_state()` call. `build_system()`: new config-gated try/except block after `agent_layer = build_agent_layer(...)`; `+1` key in `components`; threaded into the `_start_api_server(...)` call. |
| `config/settings.py` | New `ML_EXTENSIONS_ENABLED: bool` (default `False`). |
| `.env.example` | New "ML Extensions Integration Layer" section. |
| `docs/architecture.md` | `+2` sections: §52 backfills PR #82 (never documented by that PR itself), §53 documents this phase in full. |
| `CLAUDE.md` | `+2` Completed entries (§52 backfill, §53). |
| `tests/test_ml_extensions_data_adapter.py` | New, 14 tests. |
| `tests/test_ml_extensions_agent.py` | New, 12 tests — includes the `CEOAgent.WEIGHTS` isolation proof. |
| `tests/test_ml_extensions_integration.py` | New, 19 tests — `ConfigBridge`, `SystemIntegrator`, `PortfolioStateAdapter`, all 5 API endpoints. |

No changes to `ml/extensions/`, `agents/ceo_agent.py`, `execution/`,
`risk/`, journal schema, or `database/db.py` — verified by direct
inspection.

## Fix after first delivery, caught by CI

The first delivery of this branch put the integration package at
`ml/extensions/integration/` — nested *inside* `ml/extensions/`.
Locally that passed every test, because this sandbox happened to have
`ml/extensions/`'s optional dependencies (gymnasium, stable-baselines3,
torch, river, optuna) installed globally already, from directly
smoke-testing the real `ExtensionsOrchestrator`. That masked a real
bug: `ml/extensions/__init__.py` (PR #82's own file, unmodified here)
eagerly imports `.rl`/`.online`/`.hpo`/`.orchestrator` at its own
module top level, contrary to that file's own docstring. CI — which
correctly installs only the base `requirements.txt` — failed to even
collect this layer's 3 test files as a result. Fixed by moving the
package to `ml/extensions_integration/`, a sibling of `ml/extensions/`
rather than a child of it (see `docs/architecture.md` §53's
"Post-commit fix" addendum for the full write-up). This also surfaced
a second, smaller bug in this layer's own test suite: 4 of the 45 tests
genuinely need the optional stack to exercise `wire_all()`'s success
path and weren't gated for its absence — fixed with
`pytest.importorskip("gymnasium")`, plus one new regression test
(`test_degrades_gracefully_when_gymnasium_not_installed`) that
specifically proves graceful degradation without it. `ml/extensions/`
itself remains completely untouched throughout both fixes.

## Testing

- New: 45 tests across 3 files — 41 always run, 4 skip cleanly (not
  fail) in any environment without `ml/extensions/requirements.txt`
  installed, since they specifically exercise the real
  `ExtensionsConfig`/`ExtensionsOrchestrator` success path
- Verified in BOTH environments, not just reasoned about: with
  gymnasium/stable-baselines3/torch/river/optuna genuinely uninstalled
  (matching CI) — 42 passed, 4 skipped, 0 errors across the 3 new
  files; full backend suite 2958 passed, 4 skipped, 45 deselected. With
  those optional packages installed — all 45 pass, 0 skipped; full
  backend suite 2961 passed, 45 deselected. Both runs: same 3
  pre-existing `tests/test_dashboard_serving.py` failures (no frontend
  build present in this environment; confirmed unrelated, present on
  unmodified `main`)
- `ruff check`: clean on all touched/new files, in both environments
- `vulture --min-confidence 80`: clean on all touched/new files
- `python3 -c "import main"`: succeeds in both environments
- The real `ExtensionsOrchestrator`/`RLAdapter`/`HPOManager`/
  `OnlineLearner` were exercised directly in manual smoke tests (not
  just mocked) to confirm the integration layer's assumptions against
  actual runtime behavior, in addition to the automated tests above.

## Activation (operator action required — not automatic)

Add to `.env` and restart, **and** install
`ml/extensions/requirements.txt`'s optional dependencies:
```
ML_EXTENSIONS_ENABLED=true
```
Without those optional dependencies installed, wiring fails non-fatally
(caught and logged) and the bot behaves exactly as if the flag were
`false`. See `MIGRATION.md` for what to expect after activation.
