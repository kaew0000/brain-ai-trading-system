# PATCH NOTES — V16 Phase 4C Track C: Multi-Symbol Rotation for the Background Training Lane

Branch: `feat/training-lane-multi-symbol-rotation`
Base: `main` @ `9ddd9d6` (merge of PR #78, Training-Lane Visibility + Boot-Enabled 24/7 Background Training)

## Scope note

Requested directly, after confirming the background training lane
(`training_lane/training_lane_runner.py`, shipped in PR #76/#78) was
running successfully: it trades exactly one hardcoded symbol
(`settings.SYMBOL`, `BTCUSDT` in this deployment) forever, while the
live `portfolio_signal_provider` lane trades across the full scanner
universe (~527 symbols, up to `PORTFOLIO_MAX_POSITIONS=5` concurrently).
Any model eventually trained from this lane's dataset would only have
ever seen BTCUSDT market conditions — a real train/serve mismatch
against what the live lane actually does. This phase makes the training
lane rotate across scanner-ranked candidates instead, opt-in, off by
default.

Track A only (Python backend). No `dashboard_src/` changes.

## Root cause / what was actually blocking this

Two things, found in that order:

1. `training_lane/training_lane_runner.py`'s `TrainingLaneRunner.__init__`
   set `self.symbol = symbol or settings.SYMBOL` once, and `_cycle()`
   never touched it again — no rotation mechanism existed at all.
2. Deeper, and the actual hard blocker even after adding a rotation
   mechanism: `paper/paper_execution.py`'s `PaperExecutionEngine.execute()`
   hardcoded `symbol=settings.SYMBOL` directly on the `PaperPosition` it
   constructs, **ignoring whatever symbol the caller actually asked
   for**. This class predates the training lane (it originally only
   backed `EXECUTION_MODE=paper`, a whole-bot single-symbol mode — see
   `execution/execution_factory.py`), so it was never built with
   per-call symbol flexibility. Rotating `self.symbol` on the
   `TrainingLaneRunner` side alone would not have worked — every
   position opened would still have been tagged with the fixed
   `settings.SYMBOL` regardless of which symbol was actually rotated to,
   silently mislabeling the training data. Confirmed by reading
   `execute()`'s body directly before writing any fix, not assumed.

## What changed

| File | Change |
|---|---|
| `paper/paper_execution.py` | `execute()` gains an optional `symbol: str \| None = None` parameter, defaulting to `settings.SYMBOL` when omitted — every existing caller (`execution/execution_factory.py`'s `EXECUTION_MODE=paper` wiring) is byte-for-byte unaffected. Also corrected a misleading `# BTC min` comment on the quantity floor (still a generic 0.001 floor, not a real per-symbol exchange minimum — documented honestly in the method's own docstring rather than left silently wrong now that arbitrary symbols are supported). |
| `training_lane/training_lane_runner.py` | New `_select_symbol()` method: round-robins through an injected `opportunity_ranker`'s top-N ranked candidates when multi-symbol mode is on; falls back to the original fixed symbol (never raises) when the flag is off, no ranker was supplied, ranking returns nothing, or ranking itself throws. `_cycle()` now calls `_select_symbol()` only at the point of attempting a new entry (i.e., only while flat) — a position, once opened, keeps its symbol for its whole life; rotation cannot happen mid-position. `execute()` is now called with `symbol=self.symbol` explicitly. `status()` gained a `multi_symbol_enabled` field. |
| `config/settings.py` | `+BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED` (bool, default `False`), `+BACKGROUND_TRAINING_SYMBOL_POOL_SIZE` (int, default `10`). |
| `main.py` | When `BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED` is `True` and `market_scanner` is available (i.e., `SCANNER_ENABLED=true`), constructs a dedicated `OpportunityRanker(market_scanner, top_n=BACKGROUND_TRAINING_SYMBOL_POOL_SIZE)` — its own instance, reading the same underlying scanner cache `ExecutionScheduler`'s own ranker reads, not a second `MarketScanner` — and passes it into `TrainingLaneRunner(opportunity_ranker=...)`. If the flag is off or the scanner isn't running, `training_lane_ranker` stays `None` and the lane behaves exactly as it did before this phase. |
| `tests/test_training_lane_runner.py` | +21 new tests: rotation order, empty-ranking fallback, raising-ranker fallback, no-ranker fallback, mid-position symbol stability (regression guard — the one case that would have silently corrupted PnL tracking if gotten wrong), post-close rotation, `PaperExecutionEngine.execute()`'s new `symbol=` parameter (default-preserved, explicit-respected, and that a closed trade actually carries the symbol it was opened with), and `main.py` wiring (ast-based source check, mirroring `TestBootBehavior`'s existing pattern). |

**Not touched**: `ranking/opportunity_ranker.py`, `scanner/market_scanner.py`
— both reused exactly as they already existed for the live scanner path,
zero changes needed. `execution/execution_factory.py`'s
`EXECUTION_MODE=paper` wiring — unaffected, doesn't pass the new
`symbol=` parameter, gets the exact same default behavior as before.

## Testing

- `pytest tests/`: **2876 passed** (2842 baseline + 34 new in
  `test_training_lane_runner.py`), 0 failed, 45 deselected (integration
  marker) — zero regressions. Also independently re-ran every other test
  file touching `PaperExecutionEngine`
  (`test_execution_factory.py`, `test_recovery_engine.py`,
  `test_phase4c.py`, `test_p1b1_dynamic_risk.py`, `test_audit_fixes.py`
  — 256 tests) before touching the shared file, to catch any regression
  from the `execute()` signature change specifically: all passed,
  unchanged.
- `ruff check .`: clean, before and after.
- `vulture . --min-confidence 80`: 0 findings, before and after.
- `python3 -c "import main"`: OK.
- Frontend: not touched this phase — `tsc`/`vitest`/`npm run build`
  gates not applicable.
- Independent second-clone verification: see delivery message.

## What this does not fix / does not do

- Does not turn multi-symbol rotation on by default —
  `BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED=false` remains the default;
  opt in via `.env` to activate it.
- Does not change what the *live* lane trades — this phase is entirely
  about the background training lane's own dataset diversity, not live
  execution scope (that was already fixed separately — PR #75,
  `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS`).
- Does not add a real per-symbol exchange minimum-quantity table to
  `PaperExecutionEngine` — the 0.001 floor is a generic safety floor,
  documented honestly as such, not exchange-accurate for every symbol.
  Acceptable for this engine's actual purpose (paper/training data), not
  something to reuse anywhere real order sizing matters.
- Does not change the rotation *strategy* itself beyond simple
  round-robin through the top-N ranked list — no weighting by score,
  liquidity, or recency. A reasonable, simple starting point; revisit if
  the resulting dataset's symbol distribution turns out skewed in
  practice.
