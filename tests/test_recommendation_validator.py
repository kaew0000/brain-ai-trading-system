"""
tests/test_recommendation_validator.py — V16 Phase 4C Step 3
(learning/application/recommendation_validator.py)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning.application.recommendation_validator import (
    sample_size_of,
    validate_all,
    validate_recommendation,
)
from learning.pattern_miner import Pattern
from learning.recommendation_engine import Recommendation, RecommendationEngine

pytestmark = pytest.mark.unit


def _pattern(kind="worst_symbol", subject="BTCUSDT", metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.3, "sample_size": 40},
                   description="d", severity=severity)


class TestSampleSizeOf:

    def test_reads_sample_size_key(self):
        assert sample_size_of({"metric": {"sample_size": 12}}) == 12

    def test_falls_back_to_length_key(self):
        assert sample_size_of({"metric": {"length": 7}}) == 7

    def test_none_when_metric_missing(self):
        assert sample_size_of({}) is None

    def test_none_when_metric_not_dict(self):
        assert sample_size_of({"metric": "oops"}) is None

    def test_none_when_neither_key_present(self):
        assert sample_size_of({"metric": {"win_rate": 0.5}}) is None


class TestValidateRecommendation:

    def test_valid_recommendation(self):
        now = datetime.now(timezone.utc)
        rec = RecommendationEngine().generate([_pattern(metric={"win_rate": 0.2, "sample_size": 40})], now=now)[0]
        validated = validate_recommendation(rec, now=now)
        assert validated.validator_status == "valid"

    def test_insufficient_sample_below_threshold(self):
        now = datetime.now(timezone.utc)
        rec = RecommendationEngine().generate([_pattern(metric={"win_rate": 0.2, "sample_size": 2})], now=now)[0]
        validated = validate_recommendation(rec, now=now, min_sample_size=5)
        assert validated.validator_status == "insufficient_sample"

    def test_exactly_at_threshold_is_valid(self):
        now = datetime.now(timezone.utc)
        rec = RecommendationEngine().generate([_pattern(metric={"win_rate": 0.2, "sample_size": 5})], now=now)[0]
        validated = validate_recommendation(rec, now=now, min_sample_size=5)
        assert validated.validator_status == "valid"

    def test_expired_recommendation(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)
        rec = RecommendationEngine().generate([_pattern()], now=old)[0]
        validated = validate_recommendation(rec, now=now)
        assert validated.validator_status == "expired"

    def test_not_yet_expired(self):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(hours=1)
        rec = RecommendationEngine().generate([_pattern()], now=recent)[0]
        validated = validate_recommendation(rec, now=now)
        assert validated.validator_status == "valid"

    def test_invalid_when_based_on_missing_kind(self):
        rec = Recommendation(text="x", category="symbol", confidence="low", based_on={"subject": "BTCUSDT"})
        assert validate_recommendation(rec).validator_status == "invalid"

    def test_invalid_when_based_on_missing_subject(self):
        rec = Recommendation(text="x", category="symbol", confidence="low", based_on={"kind": "worst_symbol"})
        assert validate_recommendation(rec).validator_status == "invalid"

    def test_invalid_when_sample_size_unreadable(self):
        rec = Recommendation(text="x", category="symbol", confidence="low",
                              based_on={"kind": "worst_symbol", "subject": "BTCUSDT", "metric": {}})
        assert validate_recommendation(rec).validator_status == "invalid"

    def test_invalid_when_expires_at_unparseable(self):
        rec = Recommendation(text="x", category="symbol", confidence="low",
                              based_on={"kind": "worst_symbol", "subject": "BTCUSDT",
                                        "metric": {"sample_size": 40}},
                              expires_at="not-a-timestamp")
        assert validate_recommendation(rec).validator_status == "invalid"

    def test_never_mutates_input(self):
        now = datetime.now(timezone.utc)
        rec = RecommendationEngine().generate([_pattern(metric={"win_rate": 0.2, "sample_size": 2})], now=now)[0]
        original_status = rec.validator_status
        validate_recommendation(rec, now=now, min_sample_size=5)
        assert rec.validator_status == original_status == "unvalidated"

    def test_naive_now_treated_as_utc(self):
        """A caller-supplied naive datetime must not raise — treated as UTC."""
        now_aware = datetime.now(timezone.utc)
        rec = RecommendationEngine().generate([_pattern()], now=now_aware)[0]
        naive_now = now_aware.replace(tzinfo=None)
        validated = validate_recommendation(rec, now=naive_now)
        assert validated.validator_status == "valid"


class TestValidateAll:

    def test_validates_every_recommendation_against_same_now(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern(subject="BTCUSDT"), _pattern(subject="ETHUSDT", metric={"win_rate": 0.1, "sample_size": 1})],
            now=now,
        )
        validated = validate_all(recs, now=now, min_sample_size=5)
        statuses = {r.symbol: r.validator_status for r in validated}
        assert statuses["BTCUSDT"] == "valid"
        assert statuses["ETHUSDT"] == "insufficient_sample"

    def test_empty_list(self):
        assert validate_all([]) == []
