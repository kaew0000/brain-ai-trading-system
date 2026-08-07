"""
learning/application/recommendation_scoring.py — V16 Phase 4C Step 3
Part D: Recommendation Scoring.

Deterministic, explainable, arithmetic scoring — no ML model, nothing
trained, nothing that could silently drift. Combines six sub-scores
(each independently clamped to [0.0, 1.0]) into one normalized score
via a fixed weighted sum (weights in config/settings.py, validated to
sum to 1.0 by this module's own tests). Same inputs always produce the
same score.

Sub-scores
----------
confidence  — pattern_miner's own "low"/"medium"/"high" bucket, mapped
              to 0.33/0.66/1.0.
success     — the underlying pattern's win_rate, if based_on.metric has
              one; 0.5 (neutral — "no opinion either way") when it
              doesn't (e.g. latency_trend / risk_adjusted_return_trend
              patterns have no win_rate at all — see pattern_miner.py).
sample_size — based_on.metric's sample_size (or `.length`), saturating
              to 1.0 at RECOMMENDATION_SCORE_SATURATION_N.
recency     — 1.0 at generation time, linearly decaying to 0.0 at
              expires_at. A recommendation already past expiry (this
              function is also called on recommendations
              recommendation_context.py is *about* to skip for being
              expired, for full explainability) floors at 0.0 rather
              than going negative.
coverage    — sample_size as a fraction of the full dataset's row
              count — "how much of everything we know about does this
              pattern actually speak for". 0.0 if dataset_row_count
              isn't supplied or is 0 (honestly "unknown coverage", not
              fabricated).
validator   — validator_status mapped to a fixed score: valid=1.0,
              insufficient_sample=0.2, expired=0.0, invalid=0.0,
              unvalidated=0.0 (never scored before validation ran —
              same "don't apply an unvalidated recommendation" rule
              Part H requires at the application layer too).
"""
from __future__ import annotations

from datetime import datetime, timezone

from config.settings import settings

from ..recommendation_engine import Recommendation
from .recommendation_validator import sample_size_of

_CONFIDENCE_BUCKET_SCORE = {"low": 0.33, "medium": 0.66, "high": 1.0}

_VALIDATOR_STATUS_SCORE = {
    "valid":               1.0,
    "insufficient_sample":  0.2,
    "expired":              0.0,
    "invalid":              0.0,
    "unvalidated":          0.0,
}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _as_aware_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _success_subscore(rec: Recommendation) -> float:
    metric = rec.based_on.get("metric") if isinstance(rec.based_on, dict) else None
    if not isinstance(metric, dict) or "win_rate" not in metric:
        return 0.5
    try:
        return _clamp01(float(metric["win_rate"]))
    except (TypeError, ValueError):
        return 0.5


def _sample_size_subscore(rec: Recommendation, saturation_n: int) -> float:
    if not isinstance(rec.based_on, dict):
        return 0.0
    n = sample_size_of(rec.based_on)
    if n is None or saturation_n <= 0:
        return 0.0
    try:
        return _clamp01(float(n) / float(saturation_n))
    except (TypeError, ValueError):
        return 0.0


def _recency_subscore(rec: Recommendation, now: datetime) -> float:
    if not rec.generated_at or not rec.expires_at:
        return 0.5  # honestly neutral — no lifecycle timestamps to judge recency from
    try:
        generated = _as_aware_utc(datetime.fromisoformat(rec.generated_at))
        expires = _as_aware_utc(datetime.fromisoformat(rec.expires_at))
    except ValueError:
        return 0.5
    total_span = (expires - generated).total_seconds()
    if total_span <= 0:
        return 0.0
    elapsed = (now - generated).total_seconds()
    return _clamp01(1.0 - (elapsed / total_span))


def _coverage_subscore(rec: Recommendation, dataset_row_count: int | None, saturation_n: int) -> float:
    if not dataset_row_count or not isinstance(rec.based_on, dict):
        return 0.0
    n = sample_size_of(rec.based_on)
    if n is None:
        return 0.0
    try:
        return _clamp01(float(n) / float(dataset_row_count))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def score_recommendation(
    rec: Recommendation,
    *,
    dataset_row_count: int | None = None,
    now: datetime | None = None,
) -> float:
    """Returns one normalized score in [0.0, 1.0]. `rec.validator_status`
    should already be set by recommendation_validator.py — an
    "unvalidated" recommendation scores 0.0 on the validator sub-score by
    design, since it hasn't been cleared for use yet."""
    now = _as_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    saturation_n = settings.RECOMMENDATION_SCORE_SATURATION_N

    confidence_s = _CONFIDENCE_BUCKET_SCORE.get(rec.confidence, 0.0)
    success_s    = _success_subscore(rec)
    sample_s     = _sample_size_subscore(rec, saturation_n)
    recency_s    = _recency_subscore(rec, now)
    coverage_s   = _coverage_subscore(rec, dataset_row_count, saturation_n)
    validator_s  = _VALIDATOR_STATUS_SCORE.get(rec.validator_status, 0.0)

    total = (
        settings.RECOMMENDATION_SCORE_WEIGHT_CONFIDENCE * confidence_s
        + settings.RECOMMENDATION_SCORE_WEIGHT_SUCCESS * success_s
        + settings.RECOMMENDATION_SCORE_WEIGHT_SAMPLE_SIZE * sample_s
        + settings.RECOMMENDATION_SCORE_WEIGHT_RECENCY * recency_s
        + settings.RECOMMENDATION_SCORE_WEIGHT_COVERAGE * coverage_s
        + settings.RECOMMENDATION_SCORE_WEIGHT_VALIDATOR * validator_s
    )
    return _clamp01(total)


def score_all(
    recs: list[Recommendation],
    *,
    dataset_row_count: int | None = None,
    now: datetime | None = None,
) -> dict[str, float]:
    """Batch convenience — returns {recommendation.id: score}, all judged
    against the same `now` and `dataset_row_count`."""
    now = _as_aware_utc(now) if now is not None else datetime.now(timezone.utc)
    return {
        rec.id: score_recommendation(rec, dataset_row_count=dataset_row_count, now=now)
        for rec in recs if rec.id is not None
    }
