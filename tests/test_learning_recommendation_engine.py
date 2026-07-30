"""
tests/test_learning_recommendation_engine.py — V16 Phase 4C Step 1
"""
from __future__ import annotations

import pytest

from learning.pattern_miner import Pattern
from learning.recommendation_engine import Recommendation, RecommendationEngine

pytestmark = pytest.mark.unit


def _pattern(kind, subject="X", metric=None, severity="negative", description="d"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.3, "sample_size": 20},
                   description=description, severity=severity)


class TestBasicShape:

    def test_empty_patterns_gives_empty_recommendations(self):
        assert RecommendationEngine().generate([]) == []

    def test_never_raises_on_unknown_pattern_kind(self):
        recs = RecommendationEngine().generate([_pattern("some_unhandled_kind")])
        assert recs == []  # unknown kinds produce no recommendation, not an error

    def test_recommendation_traces_back_to_pattern(self):
        p = _pattern("worst_symbol", subject="BTCUSDT")
        recs = RecommendationEngine().generate([p])
        assert recs[0].based_on["kind"] == "worst_symbol"
        assert recs[0].based_on["subject"] == "BTCUSDT"
        assert recs[0].based_on["metric"] == p.metric


class TestExampleShapedRecommendations:
    """Task brief's own examples, verified to actually come out of the
    engine in a recognizable shape — not asserting exact string
    equality (the engine fills in real numbers), just the substance."""

    def test_symbol_regime_combo_produces_the_example_sentence(self):
        p = _pattern("worst_symbol_regime_combo", subject="BTCUSDT/HIGH_VOL")
        recs = RecommendationEngine().generate([p])
        assert len(recs) == 1
        assert "BTCUSDT" in recs[0].text
        assert "HIGH_VOL" in recs[0].text
        assert "poorly" in recs[0].text

    def test_confidence_range_produces_threshold_candidate_language(self):
        p = _pattern("worst_confidence_range", subject="0-20")
        recs = RecommendationEngine().generate([p])
        assert "confidence threshold" in recs[0].text.lower()

    def test_ceo_disagreement_produces_correlates_with_losses_language(self):
        p = _pattern("agent_disagreement_quality", subject="ceo", severity="negative",
                      metric={"win_rate": 0.2, "sample_size": 15})
        recs = RecommendationEngine().generate([p])
        assert len(recs) == 1
        assert "CEO" in recs[0].text
        assert "disagreement correlates with losses" in recs[0].text

    def test_positive_agent_disagreement_produces_no_recommendation(self):
        """Only a NEGATIVE agent_disagreement_quality pattern (agent's
        disagreement correlated with losses) becomes a recommendation —
        one where disagreeing still won more often than not isn't
        actionable the same way."""
        p = _pattern("agent_disagreement_quality", subject="ceo", severity="neutral",
                      metric={"win_rate": 0.7, "sample_size": 15})
        assert RecommendationEngine().generate([p]) == []

    def test_latency_increase_produces_the_example_sentence(self):
        p = _pattern("latency_trend", subject="execution_latency",
                      metric={"first_half_avg": 0.1, "second_half_avg": 0.15, "change_pct": 0.5})
        recs = RecommendationEngine().generate([p])
        assert recs[0].text == "Execution latency increased."

    def test_risk_adjusted_return_decrease_produces_the_example_sentence(self):
        p = _pattern("risk_adjusted_return_trend", subject="avg_pnl_per_trade",
                      metric={"first_half_avg": 20.0, "second_half_avg": 5.0, "change_pct": -0.75})
        recs = RecommendationEngine().generate([p])
        assert recs[0].text == "Risk-adjusted return decreased."


class TestPositivePatternsProduceNoRecommendation:

    @pytest.mark.parametrize("kind", ["best_symbol", "best_regime", "best_hour", "best_weekday", "winning_streak"])
    def test_purely_positive_kinds_produce_nothing(self, kind):
        p = _pattern(kind, severity="positive", metric={"win_rate": 0.8, "sample_size": 20, "length": 20})
        assert RecommendationEngine().generate([p]) == []


class TestConfidenceLevel:

    def test_large_sample_gives_high_confidence(self):
        p = _pattern("worst_symbol", metric={"win_rate": 0.3, "sample_size": 50})
        recs = RecommendationEngine().generate([p])
        assert recs[0].confidence == "high"

    def test_small_sample_gives_low_confidence(self):
        p = _pattern("worst_symbol", metric={"win_rate": 0.3, "sample_size": 6})
        recs = RecommendationEngine().generate([p])
        assert recs[0].confidence == "low"

    def test_category_is_set(self):
        p = _pattern("worst_regime", metric={"win_rate": 0.3, "sample_size": 20})
        recs = RecommendationEngine().generate([p])
        assert recs[0].category == "regime"


class TestReturnsRecommendationInstances:

    def test_isinstance_check(self):
        p = _pattern("losing_streak", metric={"length": 6})
        recs = RecommendationEngine().generate([p])
        assert all(isinstance(r, Recommendation) for r in recs)
