"""
tests/test_recommendations_api.py — V16 Phase 4C Step 3 Part F: Dashboard.

Covers Part I's "dashboard API" requirement. Follows
tests/test_ceo_decisions_api.py's own TestClient + honest-empty-state
conventions.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from config.settings import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _auth_disabled():
    original = settings.API_AUTH_ENABLED
    settings.API_AUTH_ENABLED = False
    yield
    settings.API_AUTH_ENABLED = original


@pytest.fixture(autouse=True)
def _reset_singletons():
    from events.event_bus import reset_event_bus
    from learning.application.recommendation_metrics import reset_recommendation_metrics
    reset_event_bus(persist=False)
    reset_recommendation_metrics()
    yield


@pytest.fixture
def client():
    from api.app import app, _state
    _state["learning_recommendations"] = []
    return TestClient(app)


class TestRecommendationsEndpoint:

    def test_honest_empty_state_when_nothing_loaded(self, client):
        resp = client.get("/api/recommendations")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["active"] == []
        assert data["skipped"] == []

    def test_returns_active_recommendations_from_state(self, client):
        from api.app import _state
        from learning.pattern_miner import Pattern
        from learning.recommendation_engine import RecommendationEngine

        now = datetime.now(timezone.utc)
        p = Pattern(kind="worst_symbol", subject="BTCUSDT",
                    metric={"win_rate": 0.2, "sample_size": 60}, description="d", severity="negative")
        recs = RecommendationEngine().generate([p], now=now)
        _state["learning_recommendations"] = recs

        resp = client.get("/api/recommendations")
        data = resp.json()["data"]
        assert len(data["active"]) == 1
        assert data["active"][0]["symbol"] == "BTCUSDT"

    def test_symbol_filter_query_param(self, client):
        from api.app import _state
        from learning.pattern_miner import Pattern
        from learning.recommendation_engine import RecommendationEngine

        now = datetime.now(timezone.utc)
        patterns = [
            Pattern(kind="worst_symbol", subject="BTCUSDT", metric={"win_rate": 0.2, "sample_size": 60},
                    description="d", severity="negative"),
            Pattern(kind="worst_symbol", subject="ETHUSDT", metric={"win_rate": 0.2, "sample_size": 60},
                    description="d", severity="negative"),
        ]
        _state["learning_recommendations"] = RecommendationEngine().generate(patterns, now=now)

        resp = client.get("/api/recommendations", params={"symbol": "BTCUSDT"})
        data = resp.json()["data"]
        assert len(data["active"]) == 1
        assert data["active"][0]["symbol"] == "BTCUSDT"

    def test_skipped_recommendations_carry_reason(self, client):
        from api.app import _state
        from learning.pattern_miner import Pattern
        from learning.recommendation_engine import RecommendationEngine

        now = datetime.now(timezone.utc)
        p = Pattern(kind="worst_symbol", subject="BTCUSDT",
                    metric={"win_rate": 0.2, "sample_size": 1}, description="d", severity="negative")
        _state["learning_recommendations"] = RecommendationEngine().generate([p], now=now)

        resp = client.get("/api/recommendations")
        data = resp.json()["data"]
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["reason"] == "validator_status=insufficient_sample"


class TestRecommendationsMetricsEndpoint:

    def test_honest_zero_state(self, client):
        resp = client.get("/api/recommendations/metrics")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["recommendations_loaded"] == 0
        assert data["average_score"] is None

    def test_reflects_a_completed_application_cycle(self, client):
        from agents.ceo_agent import CEODecision
        from learning.application.recommendation_service import apply_learning_recommendations
        from learning.pattern_miner import Pattern
        from learning.recommendation_engine import RecommendationEngine

        now = datetime.now(timezone.utc)
        p = Pattern(kind="worst_symbol", subject="BTCUSDT",
                    metric={"win_rate": 0.2, "sample_size": 60}, description="d", severity="negative")
        recs = RecommendationEngine().generate([p], now=now)
        decision = CEODecision(action="LONG", direction="LONG", confidence=70.0, symbol="BTCUSDT")
        apply_learning_recommendations(decision, recs, symbol="BTCUSDT", now=now)

        resp = client.get("/api/recommendations/metrics")
        data = resp.json()["data"]
        assert data["recommendations_loaded"] == 1
        assert data["recommendations_applied"] == 1
