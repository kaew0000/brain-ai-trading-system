# MIGRATION — V16 Phase 4C Step 1: Autonomous Learning Pipeline

## Do you need to do anything?

**No.** This phase adds a new, independent, read-only package.
Existing behavior is unaffected:

- `journal_v2.get_trade_attribution()` gained 13 new dict keys — any
  existing caller reading only the keys that existed before this phase
  is unaffected.
- `get_ensemble_learning_dataset()` is unchanged.
- No `.env`/settings changes. No schema changes. No new tables.
- Nothing in `agents/`, `execution/`, `portfolio/`, `risk/` was touched.

## Using the pipeline

```python
from journal.journal_v2 import TradeJournalV2
from learning import LearningReportGenerator

journal = TradeJournalV2()
gen = LearningReportGenerator(journal, min_sample_size=5)
bundle = gen.generate(limit=10_000)   # LearningReportBundle

paths = gen.write_reports(bundle, "reports/learning")
# -> reports/learning/learning_report.json
#    reports/learning/performance_report.json
#    reports/learning/pattern_report.json
#    reports/learning/recommendation_report.json
```

For a timestamped, never-overwritten historical snapshot:

```python
from learning.learning_snapshot import save_snapshot
save_snapshot(bundle.snapshot, "reports/learning/snapshots")
```

Nothing above runs automatically yet — no scheduled job calls this.
Wiring a periodic run is a natural, small follow-up (see
`docs/architecture.md` §33 "Future Phase Proposal") but is not part of
this phase.

## What this phase does NOT do

- Does not change any weight, threshold, or trading-behavior setting —
  `RecommendationEngine` produces text, never an action.
- Does not fix the cross-symbol HMM contamination, the missing
  per-agent attribution for CEO-gated multi-symbol trades, or the N+1
  read pattern in `get_ensemble_learning_dataset()` — all documented,
  none fixed here (each would mean touching a module this phase's
  brief forbids).
- Does not persist market_context/volatility/ATR/spread — those fields
  exist on `LearningRow` but are always `None` today; no write path
  captures them yet.
- Does not touch Track B (`world/`) in any way.

## Roadmap note

See `docs/architecture.md` §33 "Future Phase Proposal" and
`CLAUDE.md`'s Priority 2/4 for the precise remaining gaps, each scoped
as its own future phase.
