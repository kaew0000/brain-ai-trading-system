"""
learning/application/recommendation_events.py — V16 Phase 4C Step 3
Part G: EventBus.

Thin publishers over the EXISTING events/event_bus.py::get_event_bus()
singleton — no new EventBus, no new transport, no new persistence path
(EventBus already persists to journal_v2 when constructed with
persist=True, same as every other agent's events). Agent name
"LEARNING_RECOMMENDATION" is new (no prior phase published under it);
everything else about publishing is the existing, unmodified EventBus.

Event names
-----------
RECOMMENDATION_LOADED        — one recommendation batch was loaded for a cycle.
RECOMMENDATION_APPLIED        — one recommendation influenced a CEODecision.
RECOMMENDATION_SKIPPED         — one recommendation was excluded (generic —
                                  covers every skip reason not broken out below).
RECOMMENDATION_EXPIRED          — skipped specifically for validator_status=expired.
RECOMMENDATION_CONTRADICTED      — skipped specifically for a detected contradiction.

Every publish call is wrapped defensively — a logging/eventing failure
must never be able to break a live decision cycle (same posture as
CEOAgent._effective_weights()'s own try/except around dynamic
weighting).
"""
from __future__ import annotations

import logging

from events.event_bus import get_event_bus

logger = logging.getLogger(__name__)

_AGENT = "LEARNING_RECOMMENDATION"


def _publish(event: str, message: str, severity: str, payload: dict | None) -> None:
    try:
        get_event_bus().publish(_AGENT, event, message, severity, payload)
    except Exception as exc:
        logger.warning(f"recommendation_events: publish({event}) failed (non-fatal): {exc}")


def publish_recommendation_loaded(count: int, *, symbol: str | None = None) -> None:
    _publish(
        "RECOMMENDATION_LOADED", f"Loaded {count} recommendation(s)" + (f" for {symbol}" if symbol else ""),
        "debug", {"count": count, "symbol": symbol},
    )


def publish_recommendation_applied(recommendation_id: str | None, *, score: float | None, symbol: str | None = None) -> None:
    _publish(
        "RECOMMENDATION_APPLIED", f"Applied recommendation {recommendation_id}" + (f" to {symbol}" if symbol else ""),
        "info", {"recommendation_id": recommendation_id, "score": score, "symbol": symbol},
    )


def publish_recommendation_skipped(recommendation_id: str | None, *, reason: str, symbol: str | None = None) -> None:
    _publish(
        "RECOMMENDATION_SKIPPED", f"Skipped recommendation {recommendation_id}: {reason}",
        "debug", {"recommendation_id": recommendation_id, "reason": reason, "symbol": symbol},
    )


def publish_recommendation_expired(recommendation_id: str | None, *, symbol: str | None = None) -> None:
    _publish(
        "RECOMMENDATION_EXPIRED", f"Recommendation {recommendation_id} expired",
        "debug", {"recommendation_id": recommendation_id, "symbol": symbol},
    )


def publish_recommendation_contradicted(recommendation_id: str | None, *, reason: str, symbol: str | None = None) -> None:
    _publish(
        "RECOMMENDATION_CONTRADICTED", f"Recommendation {recommendation_id} contradicted: {reason}",
        "warning", {"recommendation_id": recommendation_id, "reason": reason, "symbol": symbol},
    )
