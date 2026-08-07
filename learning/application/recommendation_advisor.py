"""
learning/application/recommendation_advisor.py — V16 Phase 4C Step 3
Part B (Decision Integration) + Part C (Explainability).

Pure function: `apply_recommendations(decision, recommendation_set, ...)`
-> `(new_decision, explanations)`. `decision` is a `CEODecision`
(agents/ceo_agent.py) already produced by the existing, UNCHANGED
`CEOAgent.decide()` — this module never runs agents, never computes a
vote, and never decides LONG/SHORT/WAIT/BLOCKED itself.

Safety ordering (Part H) — Circuit Breaker > Risk Manager > CEO >
Decision Engine > Learning Recommendation:
  - `CEOAgent.decide()` already folds the Risk Manager's report into
    its vote and short-circuits to `action="BLOCKED"` for a genuine
    hard veto (see ceo_agent.py's own `decide()` docstring). This
    module NEVER changes `decision.action` — a BLOCKED decision is
    returned completely unchanged, byte-identical, and every
    recommendation that would have applied is explained as
    "skipped: decision_blocked" instead.
  - Portfolio/capital-level circuit breaking
    (portfolio/capital_manager.py's own RiskEngine circuit-breaker) sits
    downstream of CEODecision entirely — this module has no path to it
    and never touches portfolio/execution modules.
  - The only fields this module ever modifies are `confidence` (bounded
    adjustment, clamped to +/- RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT
    points and re-clamped to [0, 100]), `reasons` (human-readable
    annotations appended, nothing removed), and `weights_used` (an
    additional `_learning_weight_hints` key is added — the ACTUAL
    per-agent weights CEOAgent already computed are never altered,
    since re-running the weighted vote is not this module's job).
    `action`, `direction`, `score_breakdown`, and `agreement_score` are
    never touched.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from config.settings import settings

from ..recommendation_engine import Recommendation
from .recommendation_context import RecommendationSet, SkippedRecommendation
from .recommendation_scoring import score_recommendation
from .recommendation_validator import sample_size_of

_DECREASE_KINDS = {
    "worst_symbol", "worst_symbol_regime_combo", "worst_regime",
    "worst_confidence_range", "worst_hour", "worst_weekday",
    "losing_streak", "agent_disagreement_quality",
    # agent_agreement_quality: recommendation_engine.py only ever
    # generates a Recommendation for this kind when severity=="negative"
    # ("agreement has NOT correlated with wins") — so whenever a
    # Recommendation of this kind exists at all, it's a decrease.
    "agent_agreement_quality",
}
_INCREASE_KINDS = {"best_symbol_regime_combo", "best_confidence_range"}
# latency_trend: an execution-timing observation, not a confidence
# signal either way — surfaced as an execution_note instead (below).


def _as_aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _recommendation_effect(rec: Recommendation) -> str:
    """"increase_confidence" | "decrease_confidence" | "neutral" —
    deterministic from `based_on.kind`, with one exception
    (`risk_adjusted_return_trend`) whose polarity depends on the sign of
    `metric.change_pct`, exactly mirroring recommendation_engine.py's own
    "increased"/"decreased" text logic for that kind."""
    based_on = rec.based_on if isinstance(rec.based_on, dict) else {}
    kind = based_on.get("kind", "")
    if kind in _DECREASE_KINDS:
        return "decrease_confidence"
    if kind in _INCREASE_KINDS:
        return "increase_confidence"
    if kind == "risk_adjusted_return_trend":
        metric = based_on.get("metric", {})
        try:
            return "increase_confidence" if float(metric.get("change_pct", 0)) > 0 else "decrease_confidence"
        except (TypeError, ValueError):
            return "neutral"
    return "neutral"


@dataclass(frozen=True)
class AppliedRecommendationExplanation:
    """One entry per recommendation Part A's RecommendationSet was even
    aware of (applied AND skipped) — satisfies Part C's "if ignored,
    show WHY" for every single candidate, not just the ones that made
    the cut."""
    recommendation_id: str | None
    reason:              str    # the recommendation's own generated text
    confidence:            str    # "low" | "medium" | "high" bucket
    source_pattern:          str    # based_on.kind
    sample_size:              int | None
    effect:                    str    # "increase_confidence" | "decrease_confidence" | "neutral"
    applied:                    bool
    skip_reason:                  str | None
    score:                         float | None

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id, "reason": self.reason,
            "confidence": self.confidence, "source_pattern": self.source_pattern,
            "sample_size": self.sample_size, "effect": self.effect,
            "applied": self.applied, "skip_reason": self.skip_reason, "score": self.score,
        }


def _explanation(rec: Recommendation, *, applied: bool, skip_reason: str | None, score: float | None) -> AppliedRecommendationExplanation:
    based_on = rec.based_on if isinstance(rec.based_on, dict) else {}
    return AppliedRecommendationExplanation(
        recommendation_id=rec.id, reason=rec.text, confidence=rec.confidence,
        source_pattern=based_on.get("kind", ""), sample_size=sample_size_of(based_on),
        effect=_recommendation_effect(rec) if applied else "neutral",
        applied=applied, skip_reason=skip_reason, score=score,
    )


def _explanation_for_skipped(s: SkippedRecommendation) -> AppliedRecommendationExplanation:
    return _explanation(s.recommendation, applied=False, skip_reason=s.reason, score=None)


def apply_recommendations(
    decision,   # agents.ceo_agent.CEODecision — not type-imported to avoid a
                # learning/ -> agents/ import-time dependency in the other
                # direction (agents/ceo_agent.py imports THIS module, not
                # the reverse); duck-typed on the documented CEODecision
                # attributes (action/confidence/reasons/weights_used).
    recommendation_set: RecommendationSet,
    *,
    dataset_row_count: int | None = None,
    now: datetime | None = None,
):
    """Returns (new_decision, explanations). `decision` itself is never
    mutated — a NEW object is returned via `dataclasses.replace()` (or
    the exact same object, unchanged, for the BLOCKED case)."""
    now = _as_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    explanations: list[AppliedRecommendationExplanation] = []

    # Part H: existing protections always win. A BLOCKED CEODecision
    # already reflects Risk Manager's veto (see ceo_agent.py's decide())
    # — untouched, and every recommendation is explained as inapplicable.
    if decision.action == "BLOCKED":
        for rec in recommendation_set.applied:
            explanations.append(_explanation(rec, applied=False, skip_reason="decision_blocked", score=None))
        for s in recommendation_set.skipped:
            explanations.append(_explanation_for_skipped(s))
        return decision, explanations

    scored = [
        (rec, score_recommendation(rec, dataset_row_count=dataset_row_count, now=now))
        for rec in recommendation_set.applied
    ]
    scored.sort(key=lambda pair: pair[1], reverse=True)

    max_applied = settings.RECOMMENDATION_MAX_APPLIED_PER_DECISION
    top, overflow = scored[:max_applied], scored[max_applied:]

    signed_score_sum = 0.0
    risk_notes: list[str] = []
    execution_notes: list[str] = []
    weight_hints: dict[str, list[str]] = {}
    applied_count = 0

    for rec, score in top:
        effect = _recommendation_effect(rec)
        if effect == "increase_confidence":
            signed_score_sum += score
        elif effect == "decrease_confidence":
            signed_score_sum -= score
        if rec.category == "risk":
            risk_notes.append(rec.text)
        elif rec.category == "execution":
            execution_notes.append(rec.text)
        elif rec.category == "agent":
            subject = rec.based_on.get("subject") if isinstance(rec.based_on, dict) else None
            if subject:
                weight_hints.setdefault(subject, []).append(effect)
        applied_count += 1
        explanations.append(_explanation(rec, applied=True, skip_reason=None, score=score))

    for rec, score in overflow:
        explanations.append(_explanation(rec, applied=False, skip_reason="max_applied_per_decision_exceeded", score=score))
    for s in recommendation_set.skipped:
        explanations.append(_explanation_for_skipped(s))

    if applied_count == 0:
        return decision, explanations

    max_adj = settings.RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT
    avg_signed_score = signed_score_sum / applied_count       # in [-1.0, 1.0]
    bounded_delta = max(-max_adj, min(max_adj, avg_signed_score * max_adj))
    new_confidence = max(0.0, min(100.0, decision.confidence + bounded_delta))

    new_reasons = list(decision.reasons)
    sign = "+" if bounded_delta >= 0 else ""
    new_reasons.append(
        f"[learning] applied {applied_count} recommendation(s), confidence {sign}{bounded_delta:.2f}"
    )
    for note in risk_notes:
        new_reasons.append(f"[learning:risk] {note}")
    for note in execution_notes:
        new_reasons.append(f"[learning:execution] {note}")

    new_weights_used = dict(decision.weights_used)
    if weight_hints:
        new_weights_used["_learning_weight_hints"] = weight_hints

    new_decision = replace(decision, confidence=new_confidence, reasons=new_reasons, weights_used=new_weights_used)
    return new_decision, explanations
