"""
learning/application/recommendation_service.py — V16 Phase 4C Step 3.

The single entry point `agents/ceo_agent.py::CEOAgent.decide_with_recommendations()`
calls. Wires Part A (recommendation_context) + Part B (recommendation_advisor,
which itself uses Part D's recommendation_scoring) + Part E
(recommendation_metrics) + Part G (recommendation_events) into one call,
so the CEO-facing hook stays a thin, additive wrapper — same "thin
wrapper, real logic lives in the dedicated module" pattern
agents/decision_context.py already established for Phase 4B Step 3B.

Nothing here runs an agent, computes a vote, or decides an action —
see recommendation_advisor.py's own safety-ordering docstring, which
this function does not change or add to.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..recommendation_engine import Recommendation
from .recommendation_advisor import apply_recommendations
from .recommendation_context import build_recommendation_set
from .recommendation_events import (
    publish_recommendation_contradicted,
    publish_recommendation_expired,
    publish_recommendation_loaded,
    publish_recommendation_skipped,
)
from .recommendation_metrics import get_recommendation_metrics


def apply_learning_recommendations(
    decision,   # agents.ceo_agent.CEODecision
    recommendations: list[Recommendation],
    *,
    symbol: str | None = None,
    regime: str | None = None,
    direction: str | None = None,
    dataset_row_count: int | None = None,
    now: datetime | None = None,
):
    """Returns (new_decision, explanations, recommendation_set).

    Empty/None `recommendations` is a normal, honest empty state (e.g.
    RECOMMENDATION_APPLICATION_ENABLED is off, or no learning snapshot
    has been generated yet) — returns `decision` completely unchanged,
    same convention every dashboard endpoint in api/app.py already uses
    for "nothing produced yet" (see api/app.py's own /api/ceo-decisions
    docstring)."""
    now = now or datetime.now(timezone.utc)
    if not recommendations:
        return decision, [], build_recommendation_set([], symbol=symbol, regime=regime, direction=direction, now=now)

    t0 = time.perf_counter()
    metrics = get_recommendation_metrics()

    metrics.record_loaded(len(recommendations))
    publish_recommendation_loaded(len(recommendations), symbol=symbol)

    rset = build_recommendation_set(recommendations, symbol=symbol, regime=regime, direction=direction, now=now)

    new_decision, explanations = apply_recommendations(
        decision, rset, dataset_row_count=dataset_row_count, now=now,
    )

    metrics.record_explanations(explanations)
    for e in explanations:
        if e.applied:
            continue
        reason = e.skip_reason or ""
        if reason == "validator_status=expired":
            publish_recommendation_expired(e.recommendation_id, symbol=symbol)
        elif reason.startswith("contradicted_by="):
            publish_recommendation_contradicted(e.recommendation_id, reason=reason, symbol=symbol)
        else:
            publish_recommendation_skipped(e.recommendation_id, reason=reason, symbol=symbol)

    metrics.record_latency_ms((time.perf_counter() - t0) * 1000.0)
    return new_decision, explanations, rset
