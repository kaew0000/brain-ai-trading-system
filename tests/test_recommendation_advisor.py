"""
tests/test_recommendation_advisor.py — V16 Phase 4C Step 3
(learning/application/recommendation_advisor.py)

Covers Part I's "application" + "decision integration" requirements and
Part H's safety-ordering guarantees.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.ceo_agent import CEODecision
from config.settings import settings
from learning.application.recommendation_advisor import apply_recommendations
from learning.application.recommendation_context import RecommendationSet, build_recommendation_set
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine

pytestmark = pytest.mark.unit


def _pattern(kind, subject, metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.3, "sample_size": 40},
                   description="d", severity=severity)


def _decision(**kwargs):
    base = dict(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT", reasons=[], weights_used={})
    base.update(kwargs)
    return CEODecision(**base)


class TestSafetyOrdering:

    def test_blocked_decision_returned_byte_identical(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(action="BLOCKED", confidence=0.0)
        new_decision, explanations = apply_recommendations(decision, rset, now=now)
        assert new_decision is decision
        assert decision.confidence == 0.0  # untouched
        assert all(not e.applied for e in explanations)
        assert all(e.skip_reason == "decision_blocked" for e in explanations)

    def test_blocked_never_touches_action_direction_or_score_breakdown(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(action="BLOCKED", direction="", confidence=0.0, score_breakdown={"x": 1})
        new_decision, _ = apply_recommendations(decision, rset, now=now)
        assert new_decision.action == "BLOCKED"
        assert new_decision.score_breakdown == {"x": 1}

    def test_never_changes_action_or_direction_on_a_live_decision(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT",
                                                           metric={"win_rate": 0.1, "sample_size": 80})], now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(action="LONG", direction="LONG", confidence=70.0)
        new_decision, _ = apply_recommendations(decision, rset, now=now)
        assert new_decision.action == "LONG"
        assert new_decision.direction == "LONG"

    def test_never_mutates_the_original_decision_object(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT",
                                                           metric={"win_rate": 0.1, "sample_size": 80})], now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=70.0, reasons=[])
        apply_recommendations(decision, rset, now=now)
        assert decision.confidence == 70.0
        assert decision.reasons == []

    def test_confidence_adjustment_never_exceeds_configured_max(self):
        now = datetime.now(timezone.utc)
        # Many strongly negative recommendations at once — the clamp must hold.
        patterns = [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.01, "sample_size": 500})] * 1
        patterns += [_pattern("worst_symbol_regime_combo", f"BTCUSDT/REGIME{i}",
                               metric={"win_rate": 0.01, "sample_size": 500}) for i in range(10)]
        recs = RecommendationEngine().generate(patterns, now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=70.0)
        new_decision, _ = apply_recommendations(decision, rset, dataset_row_count=1000, now=now)
        delta = decision.confidence - new_decision.confidence
        assert delta <= settings.RECOMMENDATION_MAX_CONFIDENCE_ADJUSTMENT + 1e-9

    def test_confidence_stays_within_zero_and_hundred(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.01, "sample_size": 500})], now=now,
        )
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=1.0)  # near floor
        new_decision, _ = apply_recommendations(decision, rset, now=now)
        assert 0.0 <= new_decision.confidence <= 100.0


class TestApplicationBehavior:

    def test_negative_pattern_decreases_confidence(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=70.0)
        new_decision, _ = apply_recommendations(decision, rset, now=now)
        assert new_decision.confidence < decision.confidence

    def test_positive_pattern_increases_confidence(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("best_symbol_regime_combo", "BTCUSDT/TREND_UP", severity="positive",
                      metric={"win_rate": 0.85, "sample_size": 80})], now=now,
        )
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=70.0)
        new_decision, _ = apply_recommendations(decision, rset, now=now)
        assert new_decision.confidence > decision.confidence

    def test_empty_applied_set_is_a_no_op(self):
        now = datetime.now(timezone.utc)
        empty = RecommendationSet(symbol="BTCUSDT", regime=None, direction=None, generated_at=now.isoformat())
        decision = _decision(confidence=70.0)
        new_decision, explanations = apply_recommendations(decision, empty, now=now)
        assert new_decision.confidence == 70.0
        assert explanations == []

    def test_reasons_are_appended_not_replaced(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=70.0, reasons=["pre-existing reason"])
        new_decision, _ = apply_recommendations(decision, rset, now=now)
        assert "pre-existing reason" in new_decision.reasons
        assert len(new_decision.reasons) > 1

    def test_max_applied_per_decision_caps_contribution(self):
        now = datetime.now(timezone.utc)
        patterns = [_pattern("worst_symbol_regime_combo", f"BTCUSDT/REGIME{i}",
                              metric={"win_rate": 0.1, "sample_size": 80}) for i in range(20)]
        recs = RecommendationEngine().generate(patterns, now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        assert len(rset.applied) == 20
        decision = _decision(confidence=70.0)
        _, explanations = apply_recommendations(decision, rset, now=now)
        applied_count = sum(1 for e in explanations if e.applied)
        assert applied_count == settings.RECOMMENDATION_MAX_APPLIED_PER_DECISION
        overflow_count = sum(1 for e in explanations if e.skip_reason == "max_applied_per_decision_exceeded")
        assert overflow_count == 20 - settings.RECOMMENDATION_MAX_APPLIED_PER_DECISION


class TestExplainability:

    def test_every_candidate_gets_exactly_one_explanation(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80}),
             _pattern("worst_symbol", "ETHUSDT", metric={"win_rate": 0.1, "sample_size": 1})],  # insufficient sample
            now=now,
        )
        rset = build_recommendation_set(recs, now=now)
        decision = _decision(confidence=70.0, symbol=None)
        _, explanations = apply_recommendations(decision, rset, now=now)
        assert len(explanations) == 2
        ids = {e.recommendation_id for e in explanations}
        assert ids == {r.id for r in recs}

    def test_skipped_explanation_carries_reason(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "ETHUSDT", metric={"win_rate": 0.1, "sample_size": 1})], now=now,
        )
        rset = build_recommendation_set(recs, now=now, min_sample_size=5)
        decision = _decision(confidence=70.0)
        _, explanations = apply_recommendations(decision, rset, now=now)
        assert explanations[0].applied is False
        assert explanations[0].skip_reason == "validator_status=insufficient_sample"

    def test_applied_explanation_carries_source_and_sample_size(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        decision = _decision(confidence=70.0)
        _, explanations = apply_recommendations(decision, rset, now=now)
        e = explanations[0]
        assert e.applied is True
        assert e.source_pattern == "worst_symbol"
        assert e.sample_size == 80
        assert e.effect == "decrease_confidence"
        assert e.score is not None
