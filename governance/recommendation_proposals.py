"""governance/recommendation_proposals.py — V16 §72 (AI Self-Improvement
Governance Layer, Phase 3 / G5): the proposal *producer* for learning/
recommendations, mirroring ml/learning_mode.py's
_register_and_gate_promotion() (§58, Phase 2) but for
proposal_type="recommendation_param" instead of "model_promotion".

Called from main.py::run_learning_recommendation_refresh() only — same
"thin scheduler wrapper, real logic lives in a dedicated module"
convention _register_and_gate_promotion() itself established, and the
same convention every other module main.py's scheduled jobs delegate
to already uses (journal/fee_backfill.py, intelligence/news_sentiment_feed.py).

Why this lives in governance/, not learning/ or learning/application/:
learning/__init__.py's package-wide constraint is that core learning/
modules are read-only and "never mutate ... any other live
trading-behavior setting". This module writes to the update_proposals
table (via ProposalStore) — exactly the "propose, never apply
directly" half of that constraint, not a violation of it — and never
imports from execution/, portfolio/, or risk/. It imports
learning.recommendation_engine.Recommendation (a plain dataclass) and
nothing else from learning/; learning/ does not import governance/, so
there is no cycle.

Root cause this phase closes: main.py::run_learning_recommendation_refresh()
(daily @ 02:30) wrote every generated Recommendation straight into the
in-memory "learning_recommendations" state that the live CEO-gated
decision path (agents/multi_symbol_adapter.py) reads from — zero human
checkpoint, the same unattended-nightly-batch shape §58 (G2) already
fixed for model_promotion, just for a different producer. Full
root-cause writeup in docs/architecture.md §72.

Design note — why a recommendation's *governance approval* has the
same lifetime as the recommendation's own TTL, not a longer one: a
still-recurring pattern gets a fresh Recommendation (same deterministic
`id`, new `expires_at`) every single day this job runs. Once that
day's underlying proposal's own `expires_at` has passed, an approval
against it no longer covers today's fresh occurrence, and a new
proposal is created requiring approval again. This is deliberate, not
an oversight: it matches "hold every change for explicit human
confirmation" (§48's own founding request) literally, for every batch,
rather than letting one approval silently stand in for an indefinitely
recurring pattern. RECOMMENDATION_TTL_HOURS controls this window —
raise it if daily re-approval of a persistent pattern is unwanted.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from config.settings import settings
from utils.logger import get_logger

from learning.recommendation_engine import Recommendation

logger = get_logger(__name__)


def _proposal_target(rec: Recommendation) -> str:
    """rec.id is a deterministic hash of (category, based_on.kind,
    based_on.subject) — see learning/recommendation_engine.py's
    _stable_recommendation_id() — so the same underlying pattern
    always maps to the same target across days, which is what makes
    the dedup/reuse logic in gate_recommendations() below correct."""
    return f"recommendation.{rec.id}"


def _recommendation_metrics(rec: Recommendation) -> dict:
    return {
        "category": rec.category,
        "confidence": rec.confidence,
        "based_on": rec.based_on,
        "symbol": rec.symbol,
        "regime": rec.regime,
    }


def _is_expired(after: dict, now: datetime) -> bool:
    expires_at = after.get("expires_at") if isinstance(after, dict) else None
    if not expires_at:
        return False
    try:
        expires = datetime.fromisoformat(expires_at)
    except (TypeError, ValueError):
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires <= now


def gate_recommendations(
    recommendations: list[Recommendation], *, now: datetime | None = None
) -> list[Recommendation]:
    """The proposal producer + live-eligibility reader, called once per
    run_learning_recommendation_refresh() cycle.

    Mirrors ml/learning_mode.py's _register_and_gate_promotion() (§58):
    a freshly generated recommendation is always a *candidate*
    (proposed, recorded); it only becomes eligible to influence a live
    decision once a human has approved its proposal — the same
    register-then-gate shape model_promotion already uses, just with
    no separate "register" step since a Recommendation (unlike a
    trained model) has nothing to save to disk.

    When settings.RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL is False,
    returns `recommendations` completely unchanged — byte-for-byte the
    pre-§72 behavior (every recommendation immediately eligible, no
    proposal created at all), same "flag off = old behavior" guarantee
    every other governance gate in this codebase makes.

    When True (default): for each recommendation with no existing
    non-expired proposal, creates one (proposal_type=
    "recommendation_param", always unscored in this phase — see
    agents/update_review_agent.py's own Phase 1 scope note, still true
    here: no honest metrics source exists yet to score a
    recommendation's *predictive value*, only its sample size, which is
    already surfaced via `confidence`/`based_on`). Returns only the
    subset of `recommendations` whose current (non-expired) proposal
    has status "approved" or "applied" — a recommendation sitting at
    "pending" or "rejected" is excluded, same as an un-promoted
    candidate model never reaches ModelRegistry.get_active().

    Never raises — a failure creating one recommendation's proposal is
    logged and that recommendation is simply excluded this cycle, not a
    reason to fail every other recommendation in the batch (same
    per-item fault isolation intelligence/news_sentiment_feed.py's
    _fetch_one_source() already uses for a different kind of per-item
    batch).
    """
    if not settings.RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL:
        return recommendations

    now = now or datetime.now(timezone.utc)

    from agents.update_review_agent import get_update_review_agent
    from governance.proposal_store import get_proposal_store
    from governance.update_proposal import UpdateProposal

    store = get_proposal_store()
    review_agent = get_update_review_agent()

    # One list() call covers both dedup (pending/approved/applied
    # already exist -> don't re-propose) and the eligibility read
    # (approved/applied -> live) — list() has no target filter, so
    # pull every recommendation_param proposal once and index by
    # target in memory. Daily batch size is small (one Recommendation
    # per surviving Pattern out of _recommend_for()'s <= 12 kinds),
    # nowhere near list()'s default limit.
    existing_by_target: dict[str, UpdateProposal] = {}
    for p in store.list(proposal_type="recommendation_param", limit=200):
        existing_by_target.setdefault(p.target, p)  # list() is id DESC -> newest wins

    eligible: list[Recommendation] = []
    for rec in recommendations:
        target = _proposal_target(rec)
        existing = existing_by_target.get(target)

        if existing is not None and not _is_expired(existing.after, now):
            if existing.status in ("approved", "applied"):
                eligible.append(rec)
            continue  # pending or rejected and still within window -- don't re-propose

        try:
            proposal = UpdateProposal(
                proposal_type="recommendation_param",
                target=target,
                before={},
                after=asdict(rec),
                rationale=rec.text,
                metrics=_recommendation_metrics(rec),
                generated_by="learning.recommendation_engine",
            )
            proposal_id = store.create(proposal)
            proposal.id = proposal_id
            review = review_agent.review(proposal)
            store.set_review(proposal_id, review.verdict, review.reasoning, review.score)
            logger.info(
                f"GOVERNANCE: recommendation {rec.id!r} ({rec.category}) "
                f"proposed as #{proposal_id} -- pending human approval "
                f"(review: {review.verdict or 'unscored'})"
            )
        except Exception as exc:
            logger.error(
                f"governance.recommendation_proposals: failed to create "
                f"proposal for recommendation {rec.id!r} -- excluded this "
                f"cycle, not applied unattended: {exc}", exc_info=True,
            )

    return eligible
