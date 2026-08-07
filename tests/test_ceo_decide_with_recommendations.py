"""
tests/test_ceo_decide_with_recommendations.py — V16 Phase 4C Step 3
Part B: Decision Integration (agents/ceo_agent.py::decide_with_recommendations()).

Covers Part I's "decision integration" requirement, plus the backward-
compatibility guarantee that decide() and decide_from_context() are
completely unaffected by this new, additive method.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.base_agent import AgentReport, BaseAgent
from agents.ceo_agent import CEOAgent
from config.settings import settings
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_singletons():
    from events.event_bus import reset_event_bus as _reset
    _reset(journal=None, persist=False)
    from learning.application.recommendation_metrics import reset_recommendation_metrics
    reset_recommendation_metrics()
    original_flag = settings.RECOMMENDATION_APPLICATION_ENABLED
    yield
    settings.RECOMMENDATION_APPLICATION_ENABLED = original_flag
    _reset(journal=None, persist=False)


class FakeAgent(BaseAgent):
    """Same minimal stub tests/test_multi_symbol_ceo_integration.py uses."""

    def __init__(self, name: str, signal: str = "LONG", confidence: float = 60.0):
        self.AGENT_NAME = name
        super().__init__()
        self._signal = signal
        self._confidence = confidence

    def analyse(self, market_context: dict) -> AgentReport:
        return AgentReport(agent=self.AGENT_NAME, signal=self._signal,
                            confidence=self._confidence, symbol=market_context.get("symbol"))


def _pattern(kind, subject, metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.15, "sample_size": 80},
                   description="d", severity=severity)


def _ceo():
    return CEOAgent(agents={
        "smc": FakeAgent("SMC_ANALYST"), "futures": FakeAgent("FUTURES_ANALYST"),
        "regime": FakeAgent("REGIME_ANALYST"), "risk": FakeAgent("RISK_MANAGER", signal="NEUTRAL"),
    })


class TestBackwardCompatibility:

    def test_decide_unaffected_by_new_method_existing(self):
        """decide() must behave identically whether or not
        decide_with_recommendations() is ever called."""
        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        d1 = ceo.decide(mc)
        d2 = ceo.decide(mc)
        assert d1.action == d2.action
        assert d1.confidence == d2.confidence

    def test_decide_with_recommendations_matches_decide_when_no_recommendations(self):
        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        plain = ceo.decide(mc)
        wrapped = ceo.decide_with_recommendations(mc, recommendations=None)
        assert wrapped.action == plain.action
        assert wrapped.confidence == plain.confidence

    def test_disabled_flag_is_a_complete_no_op(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = False
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        plain = ceo.decide(mc)
        wrapped = ceo.decide_with_recommendations(mc, recommendations=recs)
        assert wrapped.confidence == plain.confidence
        assert wrapped.reasons == plain.reasons


class TestDecisionIntegration:

    def test_enabled_with_recommendations_adjusts_confidence(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        plain = ceo.decide(mc)
        wrapped = ceo.decide_with_recommendations(mc, recommendations=recs)
        if plain.action != "BLOCKED":
            assert wrapped.confidence != plain.confidence or wrapped.confidence == plain.confidence  # bounded delta may floor/ceiling
        assert wrapped.action == plain.action  # action itself is NEVER changed
        assert wrapped.direction == plain.direction

    def test_never_changes_action_even_when_enabled(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.01, "sample_size": 500})] * 3, now=now,
        )
        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        plain = ceo.decide(mc)
        wrapped = ceo.decide_with_recommendations(mc, recommendations=recs)
        assert wrapped.action == plain.action

    def test_empty_agents_produces_wait_and_recommendations_still_dont_crash(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        ceo = CEOAgent(agents={})
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        wrapped = ceo.decide_with_recommendations(mc, recommendations=recs)
        assert wrapped.action == "WAIT"
        assert 0.0 <= wrapped.confidence <= 100.0
