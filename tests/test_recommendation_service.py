"""
tests/test_recommendation_service.py — V16 Phase 4C Step 3
(learning/application/recommendation_service.py)
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.ceo_agent import CEODecision
from events.event_bus import reset_event_bus
from learning.application.recommendation_metrics import reset_recommendation_metrics
from learning.application.recommendation_service import apply_learning_recommendations
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine

pytestmark = pytest.mark.unit


def _pattern(kind, subject, metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.3, "sample_size": 40},
                   description="d", severity=severity)


@pytest.fixture(autouse=True)
def _fresh_state():
    reset_event_bus(persist=False)
    reset_recommendation_metrics()
    yield


class TestApplyLearningRecommendations:

    def test_empty_recommendations_is_a_no_op(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT")
        new_decision, explanations, rset = apply_learning_recommendations(decision, [], symbol="BTCUSDT")
        assert new_decision is decision
        assert explanations == []
        assert rset.applied == []

    def test_none_recommendations_is_a_no_op(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT")
        new_decision, explanations, rset = apply_learning_recommendations(decision, None, symbol="BTCUSDT")
        assert new_decision is decision

    def test_full_cycle_updates_metrics(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.15, "sample_size": 80})], now=now,
        )
        decision = CEODecision(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT")
        new_decision, explanations, rset = apply_learning_recommendations(
            decision, recs, symbol="BTCUSDT", dataset_row_count=500, now=now,
        )
        assert new_decision.confidence < 70.0
        assert len(explanations) == 1

        from learning.application.recommendation_metrics import get_recommendation_metrics
        m = get_recommendation_metrics().to_dict()
        assert m["recommendations_loaded"] == 1
        assert m["recommendations_applied"] == 1
        assert m["average_score"] is not None
        assert m["average_application_latency_ms"] is not None

    def test_full_cycle_publishes_loaded_event(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        decision = CEODecision(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT")
        apply_learning_recommendations(decision, recs, symbol="BTCUSDT", now=now)

        from events.event_bus import get_event_bus
        loaded = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_LOADED")
        assert len(loaded) == 1

    def test_skipped_recommendation_publishes_skipped_event(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "ETHUSDT", metric={"win_rate": 0.1, "sample_size": 1})], now=now,  # insufficient
        )
        decision = CEODecision(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT")
        apply_learning_recommendations(decision, recs, symbol="BTCUSDT", now=now)

        from events.event_bus import get_event_bus
        skipped = get_event_bus().get_recent(agent="LEARNING_RECOMMENDATION", event_type="RECOMMENDATION_SKIPPED")
        assert len(skipped) == 1

    def test_blocked_decision_flows_through_untouched(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        decision = CEODecision(action="BLOCKED", direction="", confidence=0.0, symbol="BTCUSDT")
        new_decision, explanations, rset = apply_learning_recommendations(decision, recs, symbol="BTCUSDT", now=now)
        assert new_decision is decision
