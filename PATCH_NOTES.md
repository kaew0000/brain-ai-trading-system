# PATCH NOTES — V16 Phase 4C Step 1: Autonomous Learning Pipeline

Branch: `feature/phase4c-step1-autonomous-learning`
Base: `main` (post Phase 4B Step 3D merge, tag `v16-engine-phase4b-step3d`, 1783 passing)
Track: A only (`docs/architecture/SEPARATION_POLICY.md`)

## Summary

New `learning/` package: Trade Closed -> Journal -> Execution
Attribution (existing) -> Dataset Builder -> Statistics -> Pattern
Miner -> Recommendation Engine -> Snapshot -> Reports. READ ONLY
throughout — no automatic weight, parameter, strategy, execution,
portfolio, or risk changes anywhere in this phase.

## Discovery — read before writing any code

1. The Learning Dataset already exists — `journal_v2.get_ensemble_learning_dataset()`
   (Phase 4B Step 2). This phase wraps it, never re-queries the DB.
2. Real surfacing gap found: `get_trade_attribution()` was already
   storing `reason`/`source`/`duration_seconds`/close-time `confidence`
   (Phase 4B Step 3D) but never returning them. Fixed additively — 13
   new dict keys, nothing renamed/removed. The one deliberate exception
   to "do not modify Journal behavior" this phase makes, flagged
   explicitly.
3. `regime`/`signal_confidence`/`score`/`mtf_aligned`/`smc_flags` are
   only real for legacy single-symbol trades — `_record_trade_opened()`
   (Phase 4B Step 2) never threaded market_context into the multi-symbol
   `TradeRecord`. Pre-existing, not fixed here (would touch
   ExecutionOrchestrator, forbidden this phase).
4. `market_context`/`volatility`/`atr`/`spread` aren't stored anywhere
   for any trade today — always `None`, schema-ready not fabricated.
5. `get_ensemble_learning_dataset()`'s N+1 read pattern doesn't scale
   past ~1,000 trades (see Benchmark) — a real, measured, pre-existing
   characteristic, not fixed here.

## New modules (Track A, `learning/`)

| File | Purpose |
|---|---|
| `learning/dataset_builder.py` | `LearningDatasetBuilder(journal).build()` -> `LearningDataset`. Adds `cumulative_pnl`/`running_drawdown` (genuinely derived, not raw storage). |
| `learning/_stats_utils.py` | Private shared `trade_stats()`/`streaks()` helpers. |
| `learning/symbol_statistics.py`, `regime_statistics.py`, `agent_statistics.py`, `feature_statistics.py` | Per-dimension breakdowns. |
| `learning/performance_tracker.py` | Overall stats, streaks, drawdown, hour/weekday breakdowns. |
| `learning/pattern_miner.py` | `PatternMiner(min_sample_size=5).mine(dataset)` — every requested pattern kind, sample-size gated. Includes joint symbol×regime and first-half-vs-second-half trend patterns so the brief's own recommendation examples are grounded in real correlations, not glued-together independent facts. |
| `learning/recommendation_engine.py` | Patterns -> human-readable, traceable Recommendations. Negative/actionable patterns only — positive ones don't get a redundant recommendation. |
| `learning/learning_snapshot.py` | Immutable `LearningSnapshot` + `save_snapshot()` (timestamp-named JSON files, never overwritten). |
| `learning/learning_report.py` | `LearningReportGenerator` — wires everything, writes the 4 requested JSON reports (these DO get overwritten each run). |

## Changes to existing modules

| File | Change |
|---|---|
| `journal/journal_v2.py` | `get_trade_attribution()` +13 keys (Discovery #2) — additive only. |
| `README.md` | `learning/` added to Repository layout. |
| `CLAUDE.md` | Status/priorities updated; backfills Step 3C/3D (neither updated this file either). |
| `docs/architecture.md` | +§33 (this phase). |

`agents/`, `execution/` (besides the one dict extension), `portfolio/`,
`risk/`, `world/`, every dashboard/API module — **not touched**.

## Compatibility analysis

`get_trade_attribution()`: new keys only, existing callers unaffected.
`get_ensemble_learning_dataset()`: unchanged signature/behavior.
CEOAgent, ExecutionOrchestrator, PortfolioManager, RiskEngine,
TradeLifecycle: untouched.

## Testing

```
pytest tests/ -q   → 1885 passed, 0 failed  (1783 baseline + 102 new)
ruff check .        → clean
```

102 new tests across 6 files + a shared `tests/_learning_helpers.py`
seeding helper that writes real trades through `TradeJournalV2` +
`record_trade_outcome()` (not hand-built dicts).

## Benchmark

```
n=    10 trades   0.016s    0.15 MB peak
n=   100 trades   0.107s    0.64 MB peak
n=  1000 trades   1.183s    4.76 MB peak
n= 10000 trades  28.550s   47.55 MB peak
```

**Not linear at the high end** (1,000→10,000 is ~24x, not ~10x) — root
cause is `get_ensemble_learning_dataset()`'s N+1 `get_trade_attribution()`
call pattern, a real, pre-existing characteristic of the method this
phase reuses. Memory scales linearly, stays modest (47.6 MB at n=10,000).
Not fixed here — see Future Phase Proposal.

## Risk analysis

- Performance ceiling on large journals (latency risk, not correctness).
- Every unavailable field is `None`/`[]`, never fabricated —
  `RegimeStatistics.coverage` and every `Pattern.sample_size` make data
  gaps visible.
- No automatic-action risk: `learning/` imports nothing from `agents/`,
  `execution/`, `portfolio/`, `risk/` — structurally cannot change
  trading behavior.
- `min_sample_size` is a design choice (default 5), not a statistical
  significance test.

## Future Phase Proposal

Fix the N+1 read pattern; persist a market-context snapshot at
trade-open time; thread regime/confidence into multi-symbol
`TradeRecord`s; wire per-agent attribution for CEO-gated multi-symbol
trades; a scheduled snapshot job; Phase 4C Step 2+ (actual weight
learning — explicitly out of scope for Step 1).
