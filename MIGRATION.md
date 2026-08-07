# MIGRATION — V16 Phase 4C Step 3: Recommendation Application Layer (Track A)

## Do you need to do anything?

**No.** Everything in this phase is additive and off by default. If you
do nothing, the system behaves exactly as it did before this phase:

- `RECOMMENDATION_APPLICATION_ENABLED` defaults to `False` —
  `CEOAgent.decide()` is untouched, and the new
  `decide_with_recommendations()` method is a complete no-op even if
  something calls it (returns `decide()`'s result unchanged).
- Nothing pre-existing calls `decide_with_recommendations()` — every
  existing caller of `decide()` / `decide_from_context()` is
  unaffected.
- `GET /api/recommendations` and `GET /api/recommendations/metrics` are
  new endpoints, not replacements — nothing existing changes shape.
- `Recommendation`'s six new fields are all defaulted — any code
  holding a `Recommendation` and reading only `.text`/`.category`/
  `.confidence`/`.based_on` (i.e. everything that existed before this
  phase) works exactly as before.

## If you want to turn this on

1. Set `RECOMMENDATION_APPLICATION_ENABLED=true` in `.env`.
2. Wire a source of `Recommendation` objects into the live decision
   loop — **this phase does not do this wiring**. You'll need to:
   - Load (or regenerate) a `LearningSnapshot`'s `.recommendations`
     (e.g. via `learning/learning_report.py`'s existing
     `LearningReportGenerator`, or by reading a saved
     `learning_report.json`/`recommendation_report.json` and
     reconstructing `Recommendation(**row)` per entry).
   - Call `ceo.decide_with_recommendations(market_context,
     confidence_result, recommendations=your_list,
     dataset_row_count=your_dataset.row_count)` instead of
     `ceo.decide(...)` at your call site.
   - Optionally populate `_state["learning_recommendations"]` in
     `api/app.py`'s startup/refresh path so
     `GET /api/recommendations` reflects live data instead of an empty
     list.
3. Tune the new settings if the defaults don't fit your risk
   tolerance:
   - `RECOMMENDATION_TTL_HOURS` (default 24) — how long a
     recommendation stays eligible before `validator_status` becomes
     `"expired"`.
   - `RECOMMENDATION_MIN_SAMPLE_SIZE` (default 5) — floor before a
     recommendation is trusted at all.
   - `RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT` (default 5.0
     percentage points) — hard ceiling on how much any combination of
     recommendations can move `CEODecision.confidence`.
   - `RECOMMENDATION_MAX_APPLIED_PER_DECISION` (default 5) — caps how
     many recommendations contribute to one decision's adjustment.
   - The six `RECOMMENDATION_SCORE_WEIGHT_*` settings — must continue
     to sum to 1.0 if you change them (enforced by this phase's own
     `test_recommendation_scoring.py::TestWeightsConfig`, not by a
     runtime check — a bad edit won't crash, but scores will fall
     outside [0,1]).

## What this can never do, even fully enabled

- Change `CEODecision.action` or `.direction` — a `BLOCKED` decision is
  always returned byte-identical; a LONG/SHORT/WAIT decision's action
  never flips because of a recommendation.
- Bypass Risk Manager or the Circuit Breaker — both already run before
  `CEOAgent.decide()` returns; this layer only ever sees the result.
- Open or close a trade — this layer has no path to
  `execution/`/`portfolio/` at all.

## Rollback

Set `RECOMMENDATION_APPLICATION_ENABLED=false` (or leave it unset — the
default). No data migration, no schema rollback needed — the new
`Recommendation` fields are additive and simply go unused again.
