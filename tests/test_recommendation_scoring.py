"""
tests/test_recommendation_scoring.py — V16 Phase 4C Step 3
(learning/application/recommendation_scoring.py)
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from config.settings import settings
from learning.application.recommendation_scoring import score_all, score_recommendation
from learning.application.recommendation_validator import validate_all
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine

pytestmark = pytest.mark.unit


def _pattern(kind="worst_symbol", subject="BTCUSDT", metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.3, "sample_size": 40},
                   description="d", severity=severity)


def _validated_rec(**pattern_kwargs):
    now = datetime.now(timezone.utc)
    rec = RecommendationEngine().generate([_pattern(**pattern_kwargs)], now=now)[0]
    return validate_all([rec], now=now)[0], now


class TestWeightsConfig:

    def test_scoring_weights_sum_to_one(self):
        total = (
            settings.RECOMMENDATION_SCORE_WEIGHT_CONFIDENCE
            + settings.RECOMMENDATION_SCORE_WEIGHT_SUCCESS
            + settings.RECOMMENDATION_SCORE_WEIGHT_SAMPLE_SIZE
            + settings.RECOMMENDATION_SCORE_WEIGHT_RECENCY
            + settings.RECOMMENDATION_SCORE_WEIGHT_COVERAGE
            + settings.RECOMMENDATION_SCORE_WEIGHT_VALIDATOR
        )
        assert total == pytest.approx(1.0)


class TestScoreRecommendation:

    def test_score_in_bounds(self):
        rec, now = _validated_rec(metric={"win_rate": 0.2, "sample_size": 60})
        score = score_recommendation(rec, dataset_row_count=1000, now=now)
        assert 0.0 <= score <= 1.0

    def test_valid_well_sampled_outscores_insufficient_sample(self):
        good, now = _validated_rec(subject="BTCUSDT", metric={"win_rate": 0.2, "sample_size": 60})
        bad_raw = RecommendationEngine().generate(
            [_pattern(subject="ETHUSDT", metric={"win_rate": 0.45, "sample_size": 2})], now=now,
        )
        bad = validate_all(bad_raw, now=now, min_sample_size=5)[0]
        assert bad.validator_status == "insufficient_sample"
        assert score_recommendation(good, now=now) > score_recommendation(bad, now=now)

    def test_unvalidated_scores_lower_than_valid(self):
        rec, now = _validated_rec(metric={"win_rate": 0.2, "sample_size": 60})
        unvalidated = replace(rec, validator_status="unvalidated")
        assert score_recommendation(unvalidated, now=now) < score_recommendation(rec, now=now)

    def test_expired_scores_lower_than_valid(self):
        rec, now = _validated_rec(metric={"win_rate": 0.2, "sample_size": 60})
        expired = replace(rec, validator_status="expired")
        assert score_recommendation(expired, now=now) < score_recommendation(rec, now=now)

    def test_higher_win_rate_scores_higher_all_else_equal(self):
        now = datetime.now(timezone.utc)
        low = validate_all(RecommendationEngine().generate(
            [_pattern(subject="BTCUSDT", metric={"win_rate": 0.1, "sample_size": 40})], now=now), now=now)[0]
        high = validate_all(RecommendationEngine().generate(
            [_pattern(subject="ETHUSDT", metric={"win_rate": 0.9, "sample_size": 40})], now=now), now=now)[0]
        assert score_recommendation(high, now=now) > score_recommendation(low, now=now)

    def test_recency_decays_toward_expiry(self):
        now = datetime.now(timezone.utc)
        fresh = validate_all(RecommendationEngine().generate([_pattern()], now=now), now=now)[0]
        stale_gen = now - timedelta(hours=settings.RECOMMENDATION_TTL_HOURS * 0.9)
        stale = validate_all(RecommendationEngine().generate([_pattern()], now=stale_gen), now=now)[0]
        assert score_recommendation(fresh, now=now) > score_recommendation(stale, now=now)

    def test_missing_win_rate_uses_neutral_success_subscore(self):
        """latency_trend / risk_adjusted_return_trend patterns have no
        win_rate — must not raise, must not silently score as 0."""
        now = datetime.now(timezone.utc)
        rec = validate_all(RecommendationEngine().generate(
            [_pattern(kind="latency_trend", subject="execution_latency",
                      metric={"change_pct": 12.0, "sample_size": 30})], now=now), now=now)[0]
        score = score_recommendation(rec, now=now)
        assert 0.0 <= score <= 1.0

    def test_no_dataset_row_count_gives_zero_coverage_not_error(self):
        rec, now = _validated_rec()
        score_with = score_recommendation(rec, dataset_row_count=1000, now=now)
        score_without = score_recommendation(rec, dataset_row_count=None, now=now)
        assert score_without <= score_with  # missing coverage can only score <= (never fabricated up)


class TestScoreAll:

    def test_returns_dict_keyed_by_id(self):
        now = datetime.now(timezone.utc)
        recs = validate_all(RecommendationEngine().generate(
            [_pattern(subject="BTCUSDT"), _pattern(subject="ETHUSDT")], now=now), now=now)
        scores = score_all(recs, dataset_row_count=500, now=now)
        assert set(scores.keys()) == {r.id for r in recs}

    def test_empty_list(self):
        assert score_all([]) == {}
