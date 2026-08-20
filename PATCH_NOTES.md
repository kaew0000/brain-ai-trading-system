# PATCH NOTES — V16 Phase 4C: Symbol-Aware SMC/OI Regime Strategy Adapter

Branch: `feature/smc-oi-symbol-aware-strategy`
Base: `main` @ `210b45e` (merge of PR #70, Dashboard Session Persistence)

## Scope note

Requested directly: add a symbol-aware adapter for the SMC/OI-regime
pipeline (`decision/brain_decision_engine.py`'s `BrainDecisionEngine`,
driven via `execution/strategy.py`'s `SMC_OI_Regime_Strategy`) so it
becomes usable in `ExecutionScheduler`'s multi-symbol live path — today
only `"portfolio_signal_provider"` is safe there (see
`execution/strategy_registry.py`'s module docstring and
`docs/architecture.md` §25's "Scope boundary — `smc_oi_regime` is
registered but not symbol-aware").

Track A only (Python backend). No `dashboard_src/` changes.

## Root cause

`SMC_OI_Regime_Strategy.generate_signal()` (`execution/strategy.py`)
calls `self.data_provider.get_all_market_data()`, which takes no symbol
argument and always reflects the single globally-configured symbol
(`config/settings.py`'s `SYMBOL`). That is the only blocker —
`data/binance_provider.py`'s `get_market_data_for(symbol)` (added V16
Phase 2F for `PortfolioSignalProvider`) already returns the identical
shape, and the rest of the pipeline it drives
(`regime_engine.classify` → `smc_engine.analyze_mtf` →
`volume_engine.analyze` → `decision_engine.decide`) consumes only the
OHLCV/market dict it's handed, never `self.data_provider` directly —
confirmed by reading each of those four methods, not assumed.

## One correction to the brief this phase was scoped from

A literal re-implementation of `generate_signal()` would call
`self.regime_engine.classify(ohlcv["h1"])` with no `symbol=`. That's
correct for a single-global-symbol caller, but `RegimeEngine.classify()`
has held a per-symbol-keyed HMM model cache since V16 Phase 4B Step 3A
specifically so multi-symbol callers can give each symbol its own
independently-fit model (confirmed by reading `regime/regime_engine.py`
directly) — passing `symbol=` is what activates that cache; omitting it
silently pools every symbol onto one shared model.
`execution/portfolio_signal_provider.py` already passes `symbol=symbol`
here, and `tests/test_portfolio_signal_provider.py::
TestSharedEngineInjection::test_injected_regime_engine_is_used` already
asserts it does. Since this phase exists specifically to make the
pipeline safe for multi-symbol use, the new adapter passes `symbol=`
to `regime_engine.classify()` — deviating from a literal copy of the
legacy call site, which would have reproduced the exact cross-symbol
state-pooling bug this phase exists to avoid.

## What changed

| File | Change |
|---|---|
| `execution/smc_oi_regime_multi.py` (new) | `SMCOIRegimeMultiAdapter` — calls `data_provider.get_market_data_for(symbol)`, re-implements `generate_signal()`'s orchestration inline (regime check → skip if `VOLATILE` and `confidence > 0.75` → `smc_engine.analyze_mtf` → `volume_engine.analyze` → `decision_engine.decide`), with the `symbol=` correction above. Never raises; matches `PortfolioSignalProvider.get_signal()`'s documented contract. |
| `execution/strategy_registry.py` | `+_build_smc_oi_regime_multi_adapter` factory, `+register_strategy("smc_oi_regime_multi", ...)`, `+` module-docstring section. The existing `"smc_oi_regime"` registration and `SMCOIRegimeStrategyAdapter` class are byte-for-byte unchanged. |
| `tests/test_smc_oi_regime_multi.py` (new) | 21 tests: registration/factory, happy path (LONG/SHORT), no-signal path (SKIP/WAIT/VOLATILE-skip), missing-entry-price path, symbol threading to both `data_provider` and `regime_engine` (regression guard for the correction above), safety guards (incomplete OHLCV, provider/engine exceptions caught not raised, one bad symbol doesn't affect another), and `decision_engine.decide()`'s exact call shape. |

**Not touched** (per phase scope): `execution/strategy.py`,
`data/binance_provider.py`, `execution/portfolio_signal_provider.py`,
`execution/execution_orchestrator.py`, `config/settings.py`'s
`STRATEGY_NAME` default (still `"portfolio_signal_provider"` — this
phase does not change the live default).

## Testing

- `pytest tests/`: **2623 passed**, 45 deselected (integration marker),
  3 failed — all 3 pre-existing and unrelated
  (`tests/test_dashboard_serving.py`, blocked on the known
  `dashboard_src/dist` `TS2580` build gap, present on `main` before this
  branch and reproduced identically on a clean `main` checkout).
  Verified true baseline on `main` @ `210b45e`: 2602 passed / 3 failed
  (same 3) + 21 new in `tests/test_smc_oi_regime_multi.py` = 2623, zero
  regressions.
- `ruff check . --exclude dashboard_src --exclude dashboard`: clean,
  before and after.
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80`:
  0 findings, before and after (content-normalized diff against `main`
  is empty).
- `python3 -c "import main"`: OK.
- Frontend: not touched this phase (Track A only) — `tsc`/`vitest`/
  `npm run build` gates skipped per phase scope.
- Independent second-clone verification: see delivery message.

## What this does not fix / does not do

- Does not fix the pre-existing `dashboard_src/dist` `TS2580` build gap
  (`Cannot find name 'process'` in `api.ts`) — unrelated, Track B,
  already tracked separately.
- Does not switch the live default `STRATEGY_NAME` — `"smc_oi_regime_multi"`
  is registered and available to select, but `"portfolio_signal_provider"`
  remains the default main.py boots with. Selecting the new strategy is
  a deliberate config change the project owner makes separately.
- Does not modify or retire `"smc_oi_regime"` / `SMC_OI_Regime_Strategy` —
  both remain exactly as they were, for any existing single-symbol/
  conor19w-compatible use.
- Does not add a `MarketContextBuilder`/`ConfidenceEngine` step the way
  `PortfolioSignalProvider` does — this adapter deliberately mirrors
  `SMC_OI_Regime_Strategy`'s own (different) pipeline, per the phase
  brief. The two strategies are not expected to produce identical
  signals for the same symbol; they're separate, independently-selectable
  strategies.
