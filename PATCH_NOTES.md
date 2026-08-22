# PATCH NOTES — Fix: ExecutionCoordinator Rejects Scanner-Discovered Symbols

Branch: `feat/execution-coordinator-dynamic-symbols`
Base: `main` @ `a018f5e` (merge of PR #74, `feat/hft-6-live-weight-config`)

## Rebase note

Originally based on `d5e1151` (PR #73). PR #74 (HFT-1 through HFT-6,
derivatives-flow trend following) merged to `main` before this PR was
merged and also appended a `docs/architecture.md` section at the same
point (claiming §45 for itself). Rebased this branch onto the new
`main` tip; the only conflict was in `docs/architecture.md` — resolved
by keeping PR #74's §45 (HFT Flow Trend Following) as-is and
renumbering this phase's section to §46. Every other file
(`config/settings.py`, `execution/execution_factory.py`,
`CHANGELOG.md`, `PATCH_NOTES.md`, `MIGRATION.md`, both test files)
auto-merged cleanly with zero manual intervention — confirmed by
inspecting each one after the rebase, not just trusting a clean
`git status`. All quality gates re-run and passing against the rebased
tip (see Testing section below) — commit hash changed as a result
(rebasing rewrites the commit); see Deliverables for the new hash.

## Scope note

Requested via an uploaded phase brief
(`03_fix_execution_coordinator_symbol_mismatch.md`): `MarketScanner`
discovers candidates across the full ~527-symbol Binance USDT-perpetual
universe, but `ExecutionCoordinator` only knows about
`settings.symbol_list` (single symbol, `['BTCUSDT']`, by default) — so
every scanner-discovered candidate on any other symbol fails at the
execution step (37 occurrences across a 30-hour production log:
`ZROUSDT`, `ESPUSDT`, `ARBUSDT`, `XLMUSDT`, `SUIUSDT`, `LINKUSDT`,
`ENAUSDT`). Track A only.

## Root cause — confirmed by reading the code, not re-derived

`execution/execution_coordinator.py`'s `get_manager()` already had a
fully generic, lazy-construct-and-cache-per-symbol pattern —
`TradeManager(self._data_provider, symbol=symbol, ...)` works for any
symbol string. The **only** thing preventing a new symbol from working
was the explicit membership check three lines above it
(`if symbol not in self._symbols: raise ValueError(...)`) — a
deliberate design choice from V16 Phase 1 (Multi-Symbol Foundation,
pre-Scanner era), not a bug at the time it was written. It now
conflicts with the later Scanner/OpportunityRanker full-universe
discovery phase.

## Verified: this is the only choke point (no closer, safer place to fix)

Traced the full flow before writing any code:
`OpportunityRanker.rank()` → `PortfolioManager.decide()` →
`ExecutionOrchestrator.execute()` → `_execute_allocation()`, which calls
`self.execution_engine.execute_trade(..., symbol=alloc.symbol)`
(`execution/execution_orchestrator.py` ~line 451) with zero symbol
filtering anywhere in between — `alloc.symbol` flows straight from the
ranker's full-universe candidates to `ExecutionCoordinator`
(`execution_engine` IS the coordinator in testnet/live mode). Confirmed
`execution_orchestrator.py` has **no separate symbol allowlist** of its
own — its `_NON_RECOVERABLE_MARKERS` tuple already contains the literal
string `"not configured on this coordinator"` (classifying this
failure as non-retryable, i.e. someone already anticipated this exact
error and correctly decided not to waste retries on it) — that
classification needed **no change**: it's still correct for the
`allow_dynamic_symbols=False` path, and simply never fires once a
symbol is dynamically registered instead.

## What changed

### `execution/execution_coordinator.py`

- New constructor params: `allow_dynamic_symbols: bool = False`,
  `max_dynamic_symbols: int = 50`. Default preserves today's exact
  behavior for every existing caller with zero changes.
- `get_manager()`: when `symbol not in self._symbols` AND
  `allow_dynamic_symbols` is `False` (default) — raises exactly as
  today, unchanged code path. When `True` — registers the symbol
  (inside `self._lock`, double-checked, same race-guard pattern the
  existing manager-cache code already uses) and falls through to the
  **same, unmodified** construct-and-cache logic below — no duplicated
  `TradeManager(...)` line.
- `health_check()`: confirmed (and tested) dynamically-added symbols
  show up automatically, since it iterates `self._symbols`.
- Class + `__init__` docstrings updated to document the new mode and
  why the cap exists.

### `config/settings.py`

- `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS: bool = Field(default=False, ...)`
  — matches `SCANNER_ENABLED`/`SCHEDULER_ENABLED`/`CEO_MULTI_SYMBOL_ENABLED`'s
  exact style and comment convention.
- `EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS: int = Field(default=50, ...)`.

### `execution/execution_factory.py`

- `ExecutionCoordinator(data_provider, symbols=settings.symbol_list, allow_dynamic_symbols=settings.EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS, max_dynamic_symbols=settings.EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS)`.
  An operator with `SCANNER_ENABLED=true` / `SCHEDULER_ENABLED=true` /
  `CEO_MULTI_SYMBOL_ENABLED=true` but **not** this new flag sees exactly
  today's behavior — verified by test
  (`test_testnet_dynamic_symbol_settings_default_off`).

### Tests

- `tests/test_execution_coordinator.py`: 11 new tests — flag-off
  regression guard, happy path, singleton caching, `symbols`/
  `health_check()` propagation, cap enforcement (including that
  re-fetching an already-registered symbol doesn't consume cap budget,
  and a `max_dynamic_symbols=0` edge case), and two concurrency tests:
  10 threads racing to register the *same* new symbol (must converge on
  exactly one `TradeManager`, mirroring `tests/test_ceo_symbol_cache.py`'s
  existing race-test pattern), and 10 threads racing to register 10
  *different* new symbols against a cap of 3 (exactly 3 must succeed,
  no overshoot from the race).
- `tests/test_execution_factory.py`: 2 new tests confirming the settings
  flags are actually wired through `build_execution_engine()`.

## Explicit note on the unboundedness question (brief's "before writing
## any code" step 5) — decided, not left implicit

**Decision: added an explicit cap (`max_dynamic_symbols`, default 50),
not left unbounded.**

Checked whether `PORTFOLIO_MAX_POSITIONS` (default 5) already provides
a natural ceiling: it does **not** — that setting bounds *concurrent*
open positions, not the *cumulative count of distinct symbols* this
coordinator could ever be asked to manage over a long-running process.
`_symbols`/`_managers` are append-only (no eviction when a position
closes), so a symbol can close and a completely different one open on
the next cycle, and an unbounded scanner universe (~527 symbols)
feeding this over weeks/months could in principle accumulate a
`TradeManager` per symbol ever selected, not just per symbol
concurrently held.

Checked `TradeManager.__init__`'s actual cost before treating this as a
memory concern: construction is cheap — no network call happens at
construction time; `exchange_info()` is only ever called lazily, from
`execute_trade()`'s first real use (`@retry_api_call`-wrapped
`_symbol_info()`). So this cap is **not primarily a resource
safeguard** — it exists because "which symbols can the live executor
ever place a real order on" is a live-money scope-of-trading decision,
and an explicit, visible ceiling is safer than an implicitly unbounded
one, matching this project's demonstrated posture (every new capability
gets its own dial, conservative default).

`50` was chosen as 10× `PORTFOLIO_MAX_POSITIONS`' default (well above
any realistic concurrent need) while remaining far short of the full
~527-symbol universe. Once reached, a symbol beyond the cap gets
**exactly today's `ValueError`** (same exception type, still caught by
`execution_orchestrator.py`'s unchanged `_NON_RECOVERABLE_MARKERS`
classification) — not a new/different failure mode. Configurable via
`EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS`.

## Testing

- `pytest tests/`: **2797 passed**, 45 deselected (integration marker),
  3 failed — the same 3 pre-existing `test_dashboard_serving.py`
  failures from every prior phase in this session (missing
  `dashboard_src/dist` build artifact in this sandbox), unrelated. 13
  new tests from this phase, all passing, zero regressions (baseline
  jumped from 2649 to 2797 passed purely because PR #74's HFT track
  added ~148 tests of its own between this phase's original base and
  the rebase — not from anything in this diff).
- `ruff check .` (no excludes, per this phase's brief): clean.
- `vulture . --exclude tests --min-confidence 80` (per this phase's
  brief): 0 findings.
- `python3 -c "import main"`: OK.
- Frontend: not touched this phase (Track A only).

## What was NOT touched

- `main.py`'s `ExecutionCoordinator.initialize()` call — pre-warming
  statically-configured symbols at startup is correct and unchanged;
  dynamically-added symbols simply aren't pre-warmed (leverage/margin
  are set lazily on their own first `execute_trade()` call instead,
  which the existing code already does for every call, confirmed by
  reading `initialize()`'s own docstring before starting).
- `MarketScanner` / `OpportunityRanker` — already working correctly,
  not the source of this bug.
- `execution/execution_orchestrator.py`'s `_NON_RECOVERABLE_MARKERS` —
  still correct for the `allow_dynamic_symbols=False` path; simply
  unused (not wrong) once a symbol is dynamically registered.
- The default of `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS` — stays
  `False`. This phase does not change what any existing deployment does
  unless Kaew explicitly opts in.
