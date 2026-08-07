# PATCH NOTES — V16 Phase 4C Step 3: Recommendation Application Layer (Track A)

Branch: `feature/phase4c-step3-recommendation-application`
Base: `main` @ `90a7e4e` (2054 passing, ruff clean — verified via two
independent fresh clones, not session context)
Track: A (backend/engine) only — no Track B (`world/`) files touched.

## Summary

This phase's brief instructed: "verify Track A4C Step 2 is already
merged" and treat any missing Step 2 capability as an incomplete
prerequisite to finish inside this same bundle. Independent
verification (two separate fresh clones of `main`, same HEAD, `git log
--all`, all 31 remote branches, all tags) found **no Phase 4C Step 2
anywhere in this repository** — only Phase 4C Step 1 (`c34b959`, PR
#20) exists. Per instruction, the missing prerequisite is completed
here, folded into this one bundle, not as a separate branch/phase.

Connects `learning/`'s (Step 1) recommendations to the live decision
pipeline as advisory inputs only — no autonomous strategy rewriting,
no automatic parameter mutation, every applied recommendation bounded
and explainable.

## Gap report — what the brief assumed vs. what actually existed

| Brief assumed | Actually found | Resolution |
|---|---|---|
| `Recommendation` has `symbol`/`direction`/`expiry`/numeric confidence/`validator_status` | Only `text`/`category`/`confidence` (low/med/high)/`based_on` | Extended additively (see below); `direction` NOT added — fabricated data, see below |
| A `Validator` component exists to reuse | Only an unrelated `world/runtime/state_validator.py` | Built `learning/application/recommendation_validator.py`, deterministic rule-based |
| An `Analytics` class exists to reuse | None found anywhere in the repo | Not built as a standalone class — scoring/metrics cover the actual need (Parts D/E) without inventing an unused abstraction |
| A recommendation-facing "CEO Adapter" exists to reuse | `ceo_gated_signal_provider.py`/`multi_symbol_adapter.py` exist but serve execution-signal gating, unrelated purpose | New additive `CEOAgent.decide_with_recommendations()`, same thin-wrapper pattern as the existing `decide_from_context()` |
| Dashboard already has learning/recommendation endpoints | None in `api/app.py` | Added `GET /api/recommendations` + `GET /api/recommendations/metrics` |

## Root cause (why the schema gap existed)

Phase 4C Step 1's `RecommendationEngine` was scoped as a pure,
read-only text-report generator — human-readable strings for a JSON
file a person reads, not a live-filterable object model. It never
needed an id, a lifecycle, or a machine-checkable status because
nothing downstream consumed individual recommendations programmatically.
This phase is the first consumer that needs that — the gap is expected
sequencing, not a defect in Step 1.

## What changed

### `learning/recommendation_engine.py` (additive, backward-compatible)
`Recommendation` gains six new defaulted fields: `id` (deterministic
hash of `category`+`based_on.kind`+`based_on.subject` — **not** a
random UUID, so a recommendation's identity survives regeneration from
a re-run dataset — Part G's contradiction/expiry tracking needs a
stable identity across cycles, a random id would break that on every
single run), `symbol`, `regime` (both honestly `None` when the
underlying pattern isn't scoped to one — e.g. `losing_streak`,
`agent_disagreement_quality`, `latency_trend` are portfolio/agent/
execution-level facts, not tied to a symbol), `generated_at`,
`expires_at` (`generated_at` + `RECOMMENDATION_TTL_HOURS`),
`validator_status` (default `"unvalidated"`).

**`direction` was requested but NOT added.** No pattern kind
`pattern_miner.py` produces is conditioned on trade direction (LONG vs
SHORT) — there is no directional win-rate breakdown anywhere in the
underlying `LearningDataset`. Adding the field would mean inventing
values with nothing behind them. `recommendation_context.py`'s
direction filter is implemented and tested (as a documented no-op
today) so a future phase that adds direction-conditioned patterns
doesn't need to touch this module.

Every one of the 12 existing keyword-only construction points inside
`_recommend_for()` is untouched — the new fields are stamped in
`generate()` via `dataclasses.replace()`, in one place, after
`_recommend_for()` has already decided whether/what to recommend.
Verified: all 18 pre-existing `test_learning_recommendation_engine.py`
tests pass unchanged, plus `test_learning_snapshot.py` and
`test_learning_report.py` (43 tests total, zero modified).

### New package: `learning/application/`
- **`recommendation_validator.py`** — deterministic, rule-based
  `validator_status`: `valid` / `expired` (past `expires_at`) /
  `insufficient_sample` (below `RECOMMENDATION_MIN_SAMPLE_SIZE`) /
  `invalid` (malformed `based_on`). Never raises — a malformed
  recommendation is "invalid", not an exception that could take down a
  live decision cycle.
- **`recommendation_context.py`** (Part A) — `build_recommendation_set()`
  filters by symbol/regime/direction/min-confidence/validator-status
  into one canonical `RecommendationSet(applied, skipped)`. Every
  excluded recommendation gets exactly one reason (symbol_mismatch /
  regime_mismatch / direction_mismatch / below_min_confidence /
  validator_status=X / contradicted_by=\<id\>). Symbol/regime matching is
  asymmetric by design: a recommendation with no `.symbol` (a global or
  regime-level finding) is never excluded just because the caller asked
  for one symbol.
- **Contradiction detection** — deliberately narrow: two candidates
  sharing the same `category` and `symbol` where one's `based_on.kind`
  starts with `best_` and the other's with `worst_` (e.g.
  `worst_confidence_range` vs `best_confidence_range` for the same
  symbol really do give opposite guidance). Not a general text-contradiction
  detector. When found, **both** sides move to `skipped` — an advisory
  layer that can't resolve a genuine disagreement should abstain, not
  guess which side to trust.
- **`recommendation_scoring.py`** (Part D) — deterministic weighted sum
  of six sub-scores (confidence bucket, historical win-rate, sample
  size, recency, dataset coverage, validator status), each clamped to
  [0,1], weights in `config/settings.py` summing to 1.0. No ML model,
  nothing trained — same inputs always produce the same score.
- **`recommendation_advisor.py`** (Part B+C) — `apply_recommendations()`.
  **Safety ordering (Part H):** a `BLOCKED` `CEODecision` (Risk
  Manager's veto already folded into `decide()`) is returned
  byte-identical — recommendations never touch it. Otherwise only
  `confidence` (clamped to ±`RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT`
  points, then re-clamped to [0,100]), `reasons` (appended, never
  removed), and `weights_used` (an annotation key added, the real
  per-agent weights are never altered) are ever touched. `action`,
  `direction`, `score_breakdown`, `agreement_score` are never changed.
  At most `RECOMMENDATION_MAX_APPLIED_PER_DECISION` highest-scored
  recommendations contribute per decision. Every recommendation
  considered — applied or skipped, for any reason — produces exactly
  one `AppliedRecommendationExplanation` (id, reason text, confidence
  bucket, source pattern, sample size, effect, applied/skip_reason,
  score).
- **`recommendation_metrics.py`** (Part E) — in-process counters
  (loaded/applied/skipped/expired/contradictory/invalid/
  insufficient_sample, average score, average latency), same
  `get_*()`/`reset_*()` singleton pattern as `events/event_bus.py`.
- **`recommendation_events.py`** (Part G) — thin publishers over the
  existing `EventBus` singleton (`RECOMMENDATION_LOADED` /
  `_APPLIED` / `_SKIPPED` / `_EXPIRED` / `_CONTRADICTED`), agent name
  `"LEARNING_RECOMMENDATION"`. No new transport, no new persistence —
  `EventBus` already persists when constructed with `persist=True`,
  same as every other agent. Every publish call is defensively wrapped
  — a logging failure can never break a live decision cycle.
- **`recommendation_service.py`** — orchestrates all of the above into
  the one call `CEOAgent.decide_with_recommendations()` makes. An empty
  or `None` recommendations list is a normal, honest no-op — returns
  the decision completely unchanged.

### `agents/ceo_agent.py` (additive)
`CEOAgent.decide_with_recommendations()` — new method, same thin-wrapper
pattern Phase 4B Step 3B's `decide_from_context()` already established:
calls the existing, unmodified `decide()` first, then hands the result
to the application layer. Nothing pre-existing calls this new method —
`decide()` and `decide_from_context()` behave identically to before
this phase for every existing caller. No-op if
`RECOMMENDATION_APPLICATION_ENABLED=false` (the default) or no
recommendations are passed.

### `api/app.py` (additive)
`GET /api/recommendations` (active/skipped + reasons, optional
`symbol`/`regime` filters) and `GET /api/recommendations/metrics`.
Both read from `_state`/an in-process singleton — zero new persistence,
zero new database tables. Honest empty/zero state until a future
scheduler populates `_state["learning_recommendations"]` (see Known
follow-up work).

### `config/settings.py` (additive)
`RECOMMENDATION_APPLICATION_ENABLED` (default `False`),
`RECOMMENDATION_TTL_HOURS` (24.0), `RECOMMENDATION_MIN_SAMPLE_SIZE` (5),
`RECOMMENDATION_SCORE_SATURATION_N` (50), six
`RECOMMENDATION_SCORE_WEIGHT_*` (sum to 1.0, unit-tested),
`RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT` (5.0 points),
`RECOMMENDATION_MAX_APPLIED_PER_DECISION` (5).

## Files changed

**Modified:**
- `learning/recommendation_engine.py` — additive schema + `generate()` change
- `agents/ceo_agent.py` — additive method
- `api/app.py` — two new endpoints + imports
- `config/settings.py` — new settings block
- `CHANGELOG.md` — new entry

**Created:**
- `learning/application/__init__.py`
- `learning/application/recommendation_validator.py`
- `learning/application/recommendation_context.py`
- `learning/application/recommendation_scoring.py`
- `learning/application/recommendation_advisor.py`
- `learning/application/recommendation_metrics.py`
- `learning/application/recommendation_events.py`
- `learning/application/recommendation_service.py`
- `tests/test_recommendation_validator.py` (18 tests)
- `tests/test_recommendation_scoring.py` (11 tests)
- `tests/test_recommendation_context.py` (15 tests)
- `tests/test_recommendation_advisor.py` (14 tests)
- `tests/test_recommendation_metrics.py` (12 tests)
- `tests/test_recommendation_events.py` (6 tests)
- `tests/test_recommendation_service.py` (6 tests)
- `tests/test_ceo_decide_with_recommendations.py` (6 tests)
- `tests/test_recommendations_api.py` (6 tests)
- `PATCH_NOTES.md`, `MIGRATION.md` (this pair — overwritten per-phase,
  matching the existing `live-trading-risk-hardening` phase's own
  convention)

## Test results

- Baseline (`main` @ `90a7e4e`, two independent fresh clones): **2054
  passed, 0 failed**, `ruff check .` clean.
- This phase's 94 new tests, run in isolation: **94 passed**.
- Full suite after this phase: **2148 passed, 0 failed** (2054 + 94,
  exact match — no pre-existing test was modified or removed).
- `ruff check .` (whole project, after this phase): **clean**.
- One real bug caught by this phase's own test suite before commit:
  `recommendation_context.py`'s direction filter referenced
  `rec.direction`, an attribute that (correctly, by design) does not
  exist on `Recommendation` — fixed to `getattr(rec, "direction",
  None)`, now forward-compatible if a future phase adds the field.

## Performance impact

- Disabled by default (`RECOMMENDATION_APPLICATION_ENABLED=false`):
  zero impact — `decide()` is byte-for-byte the pre-existing code path;
  `decide_with_recommendations()` is a new method nothing calls.
- Enabled, per decision cycle: one `O(n)` validation pass + one narrow
  `O(n²)` contradiction scan over that cycle's recommendation set (n is
  expected to be at most a few dozen — one learning snapshot's worth,
  not `get_ensemble_learning_dataset()`'s documented ~1,000-row N+1
  ceiling from Phase 4C Step 1's own CHANGELOG entry) + one scored sort
  capped at `RECOMMENDATION_MAX_APPLIED_PER_DECISION`. Measured latency
  in this phase's own tests: single-digit milliseconds for realistic
  recommendation-set sizes.

## Known follow-up work (explicitly out of scope for this phase)

- No scheduler wires a live `LearningSnapshot`'s recommendations into
  `_state["learning_recommendations"]` or into a running decision
  loop's call to `decide_with_recommendations()` — both exist and are
  fully tested end-to-end, but nothing in `main.py` calls them yet.
  Same "groundwork, not a behavior change" boundary Phase 4B Step 3B
  drew around `CEODecisionContext.portfolio_state`/
  `existing_positions`/`risk_snapshot`.
- `direction` filtering exists and is tested but is a no-op today (see
  Root cause above) until a future phase adds direction-conditioned
  patterns to `pattern_miner.py`.
- `docs/CHANGELOG.md` (a separate, much shorter, stale file — 60 lines,
  last major entry "V16.5 Patch consolidation merge") was **not**
  touched — it appears to already be a known documentation-drift issue
  predating this phase, out of this phase's scope to fix.
