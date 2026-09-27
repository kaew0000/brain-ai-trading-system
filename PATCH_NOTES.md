# PATCH NOTES — AI Self-Improvement Governance Phase 3 / G5: Recommendation Proposals (V16 §72)

Branch: `feat/governance-phase3-recommendation-proposals`
Base: `main` @ `2d19ffd` (merge of PR #106, §71 news sentiment hardening)

Wires the second real proposal producer into the AI Self-Improvement
Governance Layer (`docs/architecture.md` §48's roadmap): `learning/`'s
daily recommendation batch now goes through the same propose → review
→ human-approve pipeline `model_promotion` has used since §58 (Phase
2), instead of becoming live-eligible unattended. Full root-cause and
design detail in `docs/architecture.md` §72; this file summarizes.

## Root cause

`main.py::run_learning_recommendation_refresh()` runs daily at 02:30
(same cron shape as `run_nightly_retrain()`). It wrote every generated
`Recommendation` straight into the in-memory `learning_recommendations`
state, which the live, CEO-gated decision path reads every cycle and
uses to nudge decision confidence — zero human checkpoint. Same
unattended-nightly-batch shape §58 (G2) already closed for
`model_promotion`, just a different producer that hadn't been wired
yet.

## Scope decision: `agent_weight` deferred (not built this phase)

§48's original roadmap scoped G5 as covering both
`RECOMMENDATION_APPLICATION_ENABLED` and `DYNAMIC_AGENT_WEIGHTS_ENABLED`.
Investigated before writing any code: `RECOMMENDATION_APPLICATION_ENABLED`'s
producer is a discrete daily batch (clean fit for a proposal — this
phase). `DYNAMIC_AGENT_WEIGHTS_ENABLED` is a continuous, live-recomputed
blend re-derived every decision cycle (~5 min TTL) with no discrete
candidate value anywhere to wrap in a proposal — already bounded
(0.5×–1.5×) and off by default (not an active live-trading gap).
Discussed three concrete designs with the project owner; decided to
defer entirely and fold into G6 Tier 1 (`externalize+tune
ceo_agent.WEIGHTS`), which already plans to move the static base into
config — doing that refactor once, there, avoids doing it twice.

## What changed

- **`config/settings.py`** — new `RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL`
  (default `True`), naming/default pattern matches
  `MODEL_PROMOTION_REQUIRES_APPROVAL`. Also corrected a stale
  `RECOMMENDATION_TTL_HOURS` comment claiming no scheduled cadence
  exists — one has existed (daily @ 02:30) since Phase 4C Step 4.
- **`governance/recommendation_proposals.py`** (new) —
  `gate_recommendations()`: one proposal per `Recommendation`, keyed
  by its own stable deterministic `id` (confirmed time-independent —
  a hash of category + based_on fields — before relying on it for
  dedup). A recommendation's governance approval has the *same*
  lifetime as the recommendation's own TTL, deliberately — a
  still-recurring pattern needs re-approval every refresh cycle rather
  than one approval standing in forever. `RECOMMENDATION_TTL_HOURS` is
  the lever to widen that window if unwanted.
- **`governance/apply_proposal.py`** — extended for
  `proposal_type == "recommendation_param"`: approved → applied, no
  other side effect (the proposal row's own status is the
  live-eligibility signal `gate_recommendations()` reads next cycle —
  unlike `model_promotion`, there's no separate disk/DB state to
  mutate). `agent_weight`/`strategy_selection`/`logic_change` still
  raise, unchanged.
- **`api/app.py`** — approve endpoint's defined-behavior type set
  extended to include `recommendation_param`. List/reject already
  generic, untouched.
- **`main.py`** — `run_learning_recommendation_refresh()` now filters
  through `gate_recommendations()` before writing state. Flag-off
  behavior verified byte-identical to pre-§72.
- **`governance/__init__.py`** — docstring brought current (documents
  §58 and §72 as delivered; had gone stale after §58 too).
- **`agents/update_review_agent.py`** — no changes; already generically
  handles any non-`model_promotion` type as unscored, confirmed by
  reading the file first, not assumed.

## Testing

`tests/test_governance_phase3_recommendations.py` (new, 16 tests):
producer dedup/eligibility/expiry/fault-isolation, apply-behavior for
the new type, API approve/reject, and `main.py` wiring including a
byte-identical flag-off check. One pre-existing test in
`tests/test_governance_phase2.py` had its error-message assertion
updated to match `apply_proposal()`'s now-accurate message (the
behavior it actually tests — an unsupported type still raises — is
unchanged). Five other pre-existing test files on the same code paths
read and re-run to confirm compatibility, not just re-run blind:
`test_recommendations_api.py`, `test_recommendation_dataset_row_count_wiring.py`,
`test_ceo_live_recommendation_wiring.py`, `test_recommendation_service.py`,
`test_recommendation_explanation_persistence.py` — all pass unmodified.

Full suite: **3205 passed** (+16 over the §71 baseline of 3189, exactly
this phase's new tests), **45 deselected, 0 failed** attributable to
this change. Same 7 pre-existing, unrelated failures as §71 (3
dashboard-build, 4 missing-optional-`stable_baselines3`).

`ruff check .`: **clean, repo-wide.**
`vulture . --min-confidence 80`: **clean on every changed/new file**
(2 pre-existing findings in untouched lines of `test_governance_phase2.py`,
confirmed identical on unmodified `main`).
`python -c "import main"`: **succeeds.**
