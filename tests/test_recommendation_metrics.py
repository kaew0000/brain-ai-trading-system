"""
tests/test_recommendation_metrics.py — V16 Phase 4C Step 3
(learning/application/recommendation_metrics.py)
"""
from __future__ import annotations

import pytest

from learning.application.recommendation_advisor import AppliedRecommendationExplanation
from learning.application.recommendation_metrics import (
    RecommendationApplicationMetrics,
    get_recommendation_metrics,
    reset_recommendation_metrics,
)

pytestmark = pytest.mark.unit


def _explanation(**kwargs):
    base = dict(recommendation_id="abc", reason="r", confidence="high", source_pattern="worst_symbol",
                sample_size=40, effect="decrease_confidence", applied=True, skip_reason=None, score=0.5)
    base.update(kwargs)
    return AppliedRecommendationExplanation(**base)


class TestSingleton:

    def test_get_returns_same_instance(self):
        reset_recommendation_metrics()
        a = get_recommendation_metrics()
        b = get_recommendation_metrics()
        assert a is b

    def test_reset_returns_a_fresh_instance(self):
        m1 = get_recommendation_metrics()
        m1.record_loaded(5)
        m2 = reset_recommendation_metrics()
        assert m2 is not m1
        assert m2.recommendations_loaded == 0


class TestCounters:

    def test_record_loaded_accumulates(self):
        m = RecommendationApplicationMetrics()
        m.record_loaded(3)
        m.record_loaded(2)
        assert m.recommendations_loaded == 5

    def test_record_explanations_applied(self):
        m = RecommendationApplicationMetrics()
        m.record_explanations([_explanation(applied=True, score=0.7)])
        d = m.to_dict()
        assert d["recommendations_applied"] == 1
        assert d["recommendations_skipped"] == 0
        assert d["average_score"] == pytest.approx(0.7)

    def test_record_explanations_expired(self):
        m = RecommendationApplicationMetrics()
        m.record_explanations([_explanation(applied=False, skip_reason="validator_status=expired", score=None)])
        d = m.to_dict()
        assert d["recommendations_skipped"] == 1
        assert d["expired"] == 1
        assert d["contradictory"] == 0

    def test_record_explanations_contradictory(self):
        m = RecommendationApplicationMetrics()
        m.record_explanations([_explanation(applied=False, skip_reason="contradicted_by=xyz", score=None)])
        assert m.to_dict()["contradictory"] == 1

    def test_record_explanations_invalid(self):
        m = RecommendationApplicationMetrics()
        m.record_explanations([_explanation(applied=False, skip_reason="validator_status=invalid", score=None)])
        assert m.to_dict()["invalid"] == 1

    def test_record_explanations_insufficient_sample(self):
        m = RecommendationApplicationMetrics()
        m.record_explanations([_explanation(applied=False, skip_reason="validator_status=insufficient_sample", score=None)])
        assert m.to_dict()["insufficient_sample"] == 1

    def test_average_score_none_when_nothing_applied(self):
        m = RecommendationApplicationMetrics()
        assert m.to_dict()["average_score"] is None

    def test_average_score_across_multiple_applications(self):
        m = RecommendationApplicationMetrics()
        m.record_explanations([_explanation(applied=True, score=0.4), _explanation(applied=True, score=0.8)])
        assert m.to_dict()["average_score"] == pytest.approx(0.6)

    def test_latency_tracking(self):
        m = RecommendationApplicationMetrics()
        assert m.to_dict()["average_application_latency_ms"] is None
        m.record_latency_ms(10.0)
        m.record_latency_ms(20.0)
        assert m.to_dict()["average_application_latency_ms"] == pytest.approx(15.0)

    def test_to_dict_has_all_required_keys(self):
        d = RecommendationApplicationMetrics().to_dict()
        for key in ("recommendations_loaded", "recommendations_applied", "recommendations_skipped",
                    "expired", "contradictory", "invalid", "average_score", "average_application_latency_ms"):
            assert key in d
