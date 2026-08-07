"""
learning/application/recommendation_validator.py — V16 Phase 4C Step 3
(Part A prerequisite).

Deterministic, rule-based validation of a Recommendation — no ML, no
external service, no randomness. Stamps `validator_status` onto a NEW
Recommendation via `dataclasses.replace()`; never mutates the input
(Recommendation is frozen, so mutation isn't even possible, but the
"never edit in place" convention matches learning_snapshot.py's own
"never overwrites" rule for the same underlying reason: an
already-produced, already-explained artifact shouldn't silently change
under a caller holding a reference to it).

validator_status values
------------------------
"valid"                — passed every check below.
"expired"               — `now` is past `expires_at`.
"insufficient_sample"   — based_on.metric's sample_size (or `.length`
                          for streak patterns) is below
                          settings.RECOMMENDATION_MIN_SAMPLE_SIZE.
"invalid"               — based_on is missing required keys, its
                          sample size can't be read, or expires_at
                          can't be parsed. A Recommendation this
                          function can't make sense of is "invalid",
                          not a raised exception — this sits directly
                          upstream of a live decision cycle
                          (recommendation_advisor.py), and one
                          malformed recommendation must never be able
                          to take down that cycle.
"unvalidated"           — the Recommendation dataclass's own default;
                          this module is what moves a recommendation
                          off of it. Never returned by
                          validate_recommendation() itself.

Deliberately NOT handled here: "contradictory" — that's a relationship
between two-or-more recommendations for the same decision context, not
an intrinsic property of one recommendation in isolation. See
recommendation_context.py, which detects it while building a
RecommendationSet.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from config.settings import settings

from ..recommendation_engine import Recommendation


def _as_aware_utc(dt: datetime) -> datetime:
    """Treats a naive datetime as UTC rather than raising — every
    timestamp this module produces or reads (generated_at/expires_at)
    is itself UTC-aware ISO-8601, this only guards a caller-supplied
    `now`."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def sample_size_of(based_on: dict) -> int | None:
    """Shared across the application-layer package (recommendation_scoring.py,
    recommendation_advisor.py) rather than each reimplementing the same
    `metric.sample_size` / `metric.length` lookup — kept here since this
    module's own threshold check was the first to need it."""
    metric = based_on.get("metric")
    if not isinstance(metric, dict):
        return None
    n = metric.get("sample_size", metric.get("length"))
    if n is None:
        return None
    try:
        return int(n)
    except (TypeError, ValueError):
        return None


def validate_recommendation(
    rec: Recommendation,
    *,
    now: datetime | None = None,
    min_sample_size: int | None = None,
) -> Recommendation:
    """Pure function: same (rec, now) in -> same validator_status out.
    Returns a NEW Recommendation; `rec` itself is never modified."""
    now = _as_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    min_n = settings.RECOMMENDATION_MIN_SAMPLE_SIZE if min_sample_size is None else min_sample_size

    if not isinstance(rec.based_on, dict) or not rec.based_on.get("kind") or not rec.based_on.get("subject"):
        return replace(rec, validator_status="invalid")

    n = sample_size_of(rec.based_on)
    if n is None:
        return replace(rec, validator_status="invalid")
    if n < min_n:
        return replace(rec, validator_status="insufficient_sample")

    if rec.expires_at:
        try:
            expires = datetime.fromisoformat(rec.expires_at)
        except ValueError:
            return replace(rec, validator_status="invalid")
        if now > _as_aware_utc(expires):
            return replace(rec, validator_status="expired")

    return replace(rec, validator_status="valid")


def validate_all(
    recs: list[Recommendation],
    *,
    now: datetime | None = None,
    min_sample_size: int | None = None,
) -> list[Recommendation]:
    """Batch convenience — validates every recommendation against the
    SAME `now`, so a whole batch is judged against one consistent
    instant rather than drifting mid-loop."""
    now = _as_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    return [validate_recommendation(r, now=now, min_sample_size=min_sample_size) for r in recs]
