# PATCH NOTES — Nightly Retrain Governance Gate, Phase 2 (V16 §58)

Branch: `feat/nightly-retrain-governance-gate`
Base: `main` @ `29784c1` (merge of PR #93, scheduler Gate 0 + restart persistence)

## Root cause / gap

`ml/learning_mode.py::run_nightly_retrain()` called `ModelRegistry.
promote(model_id, model_type)` directly, unconditionally, the moment a
freshly retrained model beat `should_promote()`'s algorithmic gate
(win rate up, profit factor up, drawdown not worse). No human ever
saw the model before it started driving live trading decisions with
real money — the nightly cron makes that call unattended.

The governance building blocks to prevent exactly this already
existed in the codebase (`governance/proposal_store.py`,
`governance/update_proposal.py`, `agents/update_review_agent.py`,
the `update_proposals` DB table in `database/schema_v13.sql`) but were
completely unwired: `governance/__init__.py`'s own module docstring
states "Wiring an actual proposal producer... is Phase 2 and not part
of this delivery." Confirmed by grep: zero references to `proposal`
or `governance` anywhere in `api/app.py` or `dashboard_src/`, and zero
imports of the `governance` package from `ml/learning_mode.py`.

## Fix (Track A / backend only — see Known follow-up)

- **`config/settings.py`** — new `MODEL_PROMOTION_REQUIRES_APPROVAL: bool`
  (default `True`).
- **`ml/learning_mode.py`** — rewritten. New
  `_register_and_gate_promotion()` helper: always registers the
  candidate model (unchanged — a model that doesn't beat
  `should_promote()` is still never even saved, exactly as before).
  When the model beats the gate:
  - `MODEL_PROMOTION_REQUIRES_APPROVAL=False` → promotes immediately,
    byte-for-byte the old behavior (for dev/testnet environments that
    deliberately want unattended promotion).
  - `MODEL_PROMOTION_REQUIRES_APPROVAL=True` (default) → creates an
    `UpdateProposal` (`proposal_type="model_promotion"`, `before`=
    current active model's metrics, `after`=new metrics, `metrics`
    carries `model_id`/`model_type` so the proposal knows what to
    apply later), persists it via `ProposalStore`, runs it through
    `UpdateReviewAgent` (Phase 1's deterministic
    hard-gate-then-composite-score reviewer) for a first-pass opinion,
    and stops — does **not** promote. If proposal creation itself
    fails, the model is left un-promoted and the failure is logged —
    deliberately does **not** fall back to auto-promoting, which would
    silently defeat the whole point of the flag.
- **`governance/apply_proposal.py`** (new) — the one place an
  `status="approved"` proposal actually takes effect:
  re-validates status is `"approved"` and `proposal_type` is
  `"model_promotion"` (Phase 2 scope, mirrors
  `UpdateReviewAgent`'s own Phase 1 scope note), then calls
  `ModelRegistry.promote()` and reloads `MLAdvisor` if it's the
  `meta_label` model. Marks the proposal `"applied"` on success or
  `"apply_failed"` on any exception — never leaves it silently stuck.
- **`research/dataset_builder.py`** — new `get_lane_breakdown()`
  method (thin wrapper around `governance/lane_breakdown.py`'s
  `compute_lane_breakdown()`, which was already written and already
  said in its own docstring "that's Phase 2's job in
  ml/learning_mode.py"). Attaches `training_rows_by_lane` to a
  proposal's metrics for audit honesty about what the training data
  actually contained (relevant given `feature_store.get_training_rows()`
  has no `execution_lane` filter — LIVE and paper-training rows mix in
  every retrain today, a separate known issue, not fixed here).
- **`api/app.py`** — three new endpoints, the human side of this:
  - `GET /api/governance/proposals?status=&proposal_type=&limit=` —
    list, `VIEWER` role (read-only, same tier as `/api/ml/models`).
  - `POST /api/governance/proposals/approve` `{"proposal_id": N}` —
    `OPERATOR` role. Sets `status="approved"`, then for
    `model_promotion` proposals immediately calls `apply_proposal()`
    (approve+apply is one atomic operator action, not two separate
    steps — see the endpoint's own docstring for why). Returns 409 if
    the proposal isn't `"pending"`, 500 (with the approval already
    recorded) if apply fails.
  - `POST /api/governance/proposals/reject` `{"proposal_id": N,
    "reason": "..."}` — `OPERATOR` role. Pure status write; a
    rejected model_promotion's registered-but-inactive model is left
    on disk for audit purposes.
  - `("POST", ".../approve")` and `("POST", ".../reject")` added to
    `_AUTH_OPERATOR_ROUTES` — same trust tier as arming a risk
    override (`api/app.py`'s own comment there says why: this makes a
    new model start driving real trading decisions with real money).
    Uses a body field (`proposal_id`), not a path parameter, because
    `_AUTH_OPERATOR_ROUTES` matches on exact `request.url.path` and
    can't express a `{proposal_id}` template — same shape as the
    existing `override-next-trade` endpoint's `reason` body field.

## Known follow-up (not this phase — flagged, not built)

**No dashboard UI.** This phase is Track A (backend) only, per this
project's own `docs/SEPARATION_POLICY.md` two-track discipline. An
operator can review and act on pending proposals today via
`GET /api/governance/proposals` and the two POST endpoints (curl,
Postman, or any HTTP client) — there is no button in
`dashboard_src/` yet. Building that is a separate, dedicated
Track B/frontend phase (React component, `npm run build`, its own
quality gates) and was not started here.

**Proposal apply is scoped to `model_promotion` only.** Approving any
other `proposal_type` (e.g. a future `agent_weight` proposal) sets
`status="approved"` and stops there with no further effect — see the
approve endpoint's response `note` field and
`governance/apply_proposal.py`'s own docstring. This mirrors
`UpdateReviewAgent`'s pre-existing Phase 1 scope limitation, not a new
gap introduced here.

## Tests

New: `tests/test_governance_phase2.py` — 23 tests across
`_register_and_gate_promotion()`/`run_nightly_retrain()` wiring,
`apply_proposal()` (not-found, wrong status, wrong type, missing
metadata, success, failure-marks-apply_failed), and all three API
endpoints (list/filter, approve success + applies immediately, approve
on a non-`model_promotion` type leaves it unapplied, approve/reject
validation and 404/409 handling, operator-route registration).

Full suite: `pytest tests/` → **3046 passed, 4 skipped, 45
deselected**. Same 3 pre-existing `tests/test_dashboard_serving.py`
failures as every prior phase this week (missing frontend build
artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on every changed file.
`python -c "import main"` → succeeds.

## Files changed

`config/settings.py`, `ml/learning_mode.py` (rewritten),
`governance/apply_proposal.py` (new), `research/dataset_builder.py`,
`api/app.py`, `tests/test_governance_phase2.py` (new), `PATCH_NOTES.md`,
`MIGRATION.md`, `CHANGELOG.md`, `docs/architecture.md` (§58).
