# PATCH NOTES — AI Self-Improvement Governance Layer, Phase 1

Branch: `feat/self-improvement-governance-phase1`
Base: `main` @ `9ddd9d6` (merge of PR #78, training-lane visibility phase)

## Context

Request: make the system able to learn/self-tune (parameters, and
eventually trading logic) automatically, but hold every change for
explicit human confirmation first, with a log of what changed sent to
a second "review" agent that opines on whether the change looks good
before the human decides.

Scoped across several rounds of clarifying questions before any code
was written into a 6-phase roadmap (G1 proposal record, G2 wire the
nightly-retrain producer, G3 Review Agent, G4 dashboard approval UI,
G5 extend to agent weights/recommendation params, G6 trading-logic
tiers). **This delivery is Phase 1 only: G1 + G3**, plus a
lane-breakdown transparency addition surfaced during scoping (see
below). See `docs/architecture.md` §48 for the full write-up,
including every scope decision made and why.

## What was verified before writing code

- No approval/proposal concept existed anywhere in the repo (grepped
  for `approval`/`pending_update`/`human_review` — nothing).
- `ml/learning_mode.py::run_nightly_retrain()` already auto-promotes
  today, unconditionally, scheduled daily at `main.py:1970` — the
  most urgent live gap the request describes. Fixing it is Phase 2
  (G2), **not part of this delivery** — see "Known follow-up" below.
- `research/feature_store.py::get_training_rows()` has no
  `execution_lane` filter — the nightly retrain dataset already
  silently mixes `LIVE` + `TRAINING` (Track C's background paper
  account) + `PAPER` rows with zero visibility into the mix. Not
  previously documented. Addressed here as a transparency addition
  only (see below) — this phase does not change what the retrain
  trains on.
- No historical "what-if" replay/backtest engine exists for CEOAgent
  decisions — this is why the Review Agent only scores
  `proposal_type="model_promotion"` for real in Phase 1 (see below).

## What changed

### `database/schema_v13.sql`
New `update_proposals` table (+ 3 indexes) — one row per proposal the
system generates for itself. No separate migration script needed:
`database/db.py::_apply_schema()` re-runs the full schema script
(`CREATE TABLE IF NOT EXISTS`) against every DB path once per
process, including pre-existing files, so a brand-new table is picked
up automatically — same precedent `migration_001`'s own docstring
already documents for `execution_events`. No existing table touched.

### `config/settings.py`
Seven new settings for the Review Agent's scoring rubric —
`REVIEW_SCORE_WEIGHT_IMPROVEMENT` (0.40),
`REVIEW_SCORE_WEIGHT_DRAWDOWN_MARGIN` (0.30),
`REVIEW_SCORE_WEIGHT_SAMPLE_SIZE` (0.30, sums to 1.0),
`REVIEW_SCORE_WIN_RATE_DELTA_SCALE` (0.05),
`REVIEW_SCORE_PROFIT_FACTOR_DELTA_SCALE` (0.5),
`REVIEW_SCORE_SATURATION_N` (50), `REVIEW_MIN_SAMPLE_SIZE` (20),
`REVIEW_SCORE_APPROVE_THRESHOLD` (0.6). All new — no existing setting
touched, nothing reads these yet outside the new code below.

### `governance/` (new package)
- `update_proposal.py` — `UpdateProposal` dataclass (not frozen,
  unlike `Recommendation` — it has a real mutating lifecycle) +
  `to_row()`/`from_row()`. `proposal_type="logic_change"` always
  forces `requires_pr_review=True` in `__post_init__`, regardless of
  what the caller passes.
- `proposal_store.py` — `ProposalStore`: `create()` (always lands as
  `status="pending"`, even if the caller's dataclass says otherwise),
  `get()`, `list()` (filter by status/proposal_type), `set_review()`
  (attaches the Review Agent's opinion, never touches `status`),
  `set_status()` (the human decision point — raises on an unknown
  status rather than silently no-op'ing). Same `ManagedConn` +
  module-singleton `get_proposal_store()`/`reset_proposal_store()`
  pattern as `ml/model_registry.py`.
- `lane_breakdown.py` — `compute_lane_breakdown(rows)`, groups
  `feature_rows`-style dicts by `execution_lane`. Answers "how much of
  this model's training data was real trades vs. the paper account" —
  the transparency addition folded into this phase after that gap was
  found. Does not change what `get_training_rows()` returns; only
  makes the composition visible to whatever wants to report it.

### `agents/update_review_agent.py` (new)
`UpdateReviewAgent` — deterministic, no LLM call (checked `agents/`
first: nothing there calls an LLM anywhere in the decision path).
Deliberately **not** a `BaseAgent` subclass — `analyse(market_context)
-> AgentReport` is built around trading signals
(LONG/SHORT/NEUTRAL/WAIT), which doesn't fit "should this proposal be
approved."

`.review(proposal)` returns a `ReviewResult`:
- `proposal_type="model_promotion"`: real two-stage scoring. Stage 1
  is a hard gate — `model_promotion_hard_gate_passed()`, a literal
  re-implementation of `ml/model_registry.py::
  ModelRegistry.should_promote()`'s exact rule (win_rate↑ AND
  profit_factor↑ AND drawdown not worse), asserted equal to a real
  `ModelRegistry.should_promote()` call across 5 parametrized cases in
  `tests/test_update_review_agent.py`. Failing it is always
  `verdict="reject_recommended", score=0.0`, full stop. Stage 2 (only
  once the gate passes) is a weighted composite of
  improvement/drawdown-margin/sample-size sub-scores; below
  `REVIEW_MIN_SAMPLE_SIZE` rows the verdict is capped at `"caution"`
  even if the composite would otherwise clear
  `REVIEW_SCORE_APPROVE_THRESHOLD`.
- Every other `proposal_type` (`agent_weight`, `recommendation_param`,
  `strategy_selection`, `logic_change`): explicit **unscored** result
  (`verdict=""`, reasoning states there's no honest metrics source for
  it yet) rather than an invented number.
- If the proposal's `metrics["training_rows_by_lane"]` is present, the
  reasoning text surfaces it verbatim (e.g. "LIVE=150 (75%),
  TRAINING=50 (25%) — includes non-LIVE data") — only when a producer
  actually populates it; Phase 1 doesn't populate this on any live
  proposal itself.

### Tests (new, all `pytest.mark.unit`)
`tests/test_proposal_store.py` (25), `tests/test_update_review_agent.py`
(21, including the direct `ModelRegistry.should_promote()` cross-check),
`tests/test_lane_breakdown.py` (4). 50 total.

No existing export touched in any file. No `dashboard_src/` changes —
Track B untouched this phase.

## Testing

**Track A** — `pytest tests/`: 2873 passed (up from a 2823-passed
baseline, +50 = exactly the new tests), 45 deselected, same 3
pre-existing `tests/test_dashboard_serving.py` failures as baseline
(need a built `dashboard_src/dist/`, environmental, confirmed
identical before branching). `ruff check .`: clean. `vulture
governance/ agents/update_review_agent.py tests/test_proposal_store.py
tests/test_update_review_agent.py tests/test_lane_breakdown.py
--min-confidence 80`: clean. `python3 -c "import main"`: clean.

**Track B** — not applicable this phase; no `dashboard_src/` files
changed, so `tsc --noEmit`/`vitest`/`npm run build` have no diff to
check.

## Known follow-up (not done here, out of scope for this phase)

- **Phase 2 (G2 + G4, must ship together)**: wrap
  `run_nightly_retrain()` to create a `model_promotion` proposal
  instead of calling `ModelRegistry.promote()` directly, and ship the
  dashboard approve/reject panel — a proposal with no UI isn't
  actionable.
- **Phase 3 (G5)**: extend to
  `DYNAMIC_AGENT_WEIGHTS_ENABLED`/`RECOMMENDATION_APPLICATION_ENABLED`
  — needs a "Replay Tier A" (re-score already-taken trades under
  counterfactual weights from `agent_decisions`/`signals`/`trades`,
  honestly excluding WAIT→would-have-fired flips) before the Review
  Agent can score these for real.
- **Phase 4-6 (G6, 3 tiers)**: externalize+tune `ceo_agent.WEIGHTS`/
  `AGREEMENT_FLOOR_MULTIPLIER`/action-threshold (Tier 1), dynamic
  strategy selection (Tier 2), AI-authored logic always gated through
  the existing feature-branch+bundle+PR-review workflow (Tier 3,
  `requires_pr_review` is the schema-level enforcement point, never
  auto-deployed).
- **Replay Tier B** (full trade-outcome simulation from
  `market_snapshots.mark_price`) — a standalone backtesting-engine
  build, deliberately not started.
- `ProposalStore`/`UpdateReviewAgent` are fully functional and tested
  in isolation but not wired into any live code path yet — nothing in
  production code calls `ProposalStore.create()` until Phase 2.
