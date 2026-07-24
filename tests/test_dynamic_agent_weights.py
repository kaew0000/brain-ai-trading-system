"""
tests/test_dynamic_agent_weights.py

Phase 4B proper (architecture.md §28): CEOAgent._effective_weights() /
_get_agent_performance_cached(), which blend CEOAgent.WEIGHTS toward each
agent's measured win-rate from journal.get_agent_performance() (Phase 4B
Step 1) once that agent clears DYNAMIC_WEIGHT_MIN_SAMPLES.

Reuses the FakeAgent/reset_event_bus fixtures from
tests/test_ceo_ensemble_fusion.py's style rather than build_agent_layer's
real engines, so each agent's confidence/signal is exact and deterministic.
"""

from __future__ import annotations

import pytest

from agents.base_agent import BaseAgent, AgentReport
from agents.ceo_agent import CEOAgent
from config.settings import settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_event_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


class FakeAgent(BaseAgent):
    def __init__(self, name: str, signal: str, confidence: float):
        self.AGENT_NAME = name
        super().__init__()
        self._report = AgentReport(agent=name, signal=signal, confidence=confidence,
                                    summary=f"{name} says {signal}", raw={})

    def analyse(self, market_context: dict) -> AgentReport:
        return self._report

    def answer(self, question: str, market_context=None) -> str:
        return "stub"


class FakeJournal:
    """Stub with the one method CEOAgent's dynamic weighting calls."""

    def __init__(self, rows=None, raise_on_call=False):
        self._rows = rows or []
        self._raise = raise_on_call
        self.call_count = 0

    def get_agent_performance(self, limit: int = 500):
        self.call_count += 1
        if self._raise:
            raise RuntimeError("db unavailable")
        return self._rows


def _agents():
    return {
        "smc":     FakeAgent("SMC_ANALYST", "LONG", 80.0),
        "futures": FakeAgent("FUTURES_ANALYST", "LONG", 70.0),
    }


class TestDynamicWeightsDisabledByDefault:

    def test_setting_defaults_to_disabled(self):
        assert settings.DYNAMIC_AGENT_WEIGHTS_ENABLED is False

    def test_static_weights_used_when_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", False)
        journal = FakeJournal(rows=[{"agent": "SMC_ANALYST", "total_trades": 100,
                                      "wins": 99, "losses": 1, "win_rate": 0.99,
                                      "total_pnl": 1000.0}])
        ceo = CEOAgent(agents=_agents(), journal=journal)
        dec = ceo.decide({})
        assert dec.weights_used == CEOAgent.WEIGHTS
        assert journal.call_count == 0  # never even queried when disabled


class TestDynamicWeightsFallbackSafety:

    def test_no_journal_falls_back_to_static(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        ceo = CEOAgent(agents=_agents(), journal=None)
        dec = ceo.decide({})
        assert dec.weights_used == CEOAgent.WEIGHTS

    def test_journal_exception_falls_back_to_static(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        journal = FakeJournal(raise_on_call=True)
        ceo = CEOAgent(agents=_agents(), journal=journal)
        dec = ceo.decide({})  # must not raise
        assert dec.weights_used == CEOAgent.WEIGHTS

    def test_insufficient_samples_keeps_static_weight_for_that_agent(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_MIN_SAMPLES", 20)
        journal = FakeJournal(rows=[{"agent": "SMC_ANALYST", "total_trades": 3,
                                      "wins": 3, "losses": 0, "win_rate": 1.0,
                                      "total_pnl": 300.0}])
        ceo = CEOAgent(agents=_agents(), journal=journal)
        dec = ceo.decide({})
        # 3 < 20 min samples -> smc weight untouched relative to futures'
        # untouched weight, i.e. their ratio still matches the static ratio.
        static_ratio  = CEOAgent.WEIGHTS["smc"] / CEOAgent.WEIGHTS["futures"]
        used_ratio    = dec.weights_used["smc"] / dec.weights_used["futures"]
        assert used_ratio == pytest.approx(static_ratio, rel=1e-6)


class TestDynamicWeightsBlending:

    def test_weights_always_sum_to_one(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_MIN_SAMPLES", 5)
        journal = FakeJournal(rows=[
            {"agent": "SMC_ANALYST", "total_trades": 30, "wins": 27, "losses": 3,
             "win_rate": 0.9, "total_pnl": 2000.0},
            {"agent": "FUTURES_ANALYST", "total_trades": 30, "wins": 3, "losses": 27,
             "win_rate": 0.1, "total_pnl": -900.0},
        ])
        ceo = CEOAgent(agents=_agents(), journal=journal)
        dec = ceo.decide({})
        assert sum(dec.weights_used.values()) == pytest.approx(1.0, rel=1e-6)

    def test_high_win_rate_agent_gains_relative_weight(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_MIN_SAMPLES", 5)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_BLEND", 1.0)  # fully performance-driven, easiest to reason about
        journal = FakeJournal(rows=[
            {"agent": "SMC_ANALYST", "total_trades": 30, "wins": 30, "losses": 0,
             "win_rate": 1.0, "total_pnl": 3000.0},
            {"agent": "FUTURES_ANALYST", "total_trades": 30, "wins": 0, "losses": 30,
             "win_rate": 0.0, "total_pnl": -3000.0},
        ])
        ceo = CEOAgent(agents=_agents(), journal=journal)
        dec = ceo.decide({})

        static_ratio = CEOAgent.WEIGHTS["smc"] / CEOAgent.WEIGHTS["futures"]
        used_ratio   = dec.weights_used["smc"] / dec.weights_used["futures"]
        # 100% win-rate agent (multiplier 1.5) vs 0% win-rate agent
        # (multiplier 0.5) at full blend -> smc:futures ratio should widen
        # to 3x the static ratio (1.5 / 0.5 == 3). rel=1e-2 tolerance
        # accounts for weights_used being rounded to 4dp for display.
        assert used_ratio == pytest.approx(static_ratio * 3.0, rel=1e-2)

    def test_no_agent_zeroed_out_even_at_zero_win_rate(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_MIN_SAMPLES", 5)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_BLEND", 1.0)
        journal = FakeJournal(rows=[
            {"agent": "FUTURES_ANALYST", "total_trades": 50, "wins": 0, "losses": 50,
             "win_rate": 0.0, "total_pnl": -5000.0},
        ])
        ceo = CEOAgent(agents=_agents(), journal=journal)
        dec = ceo.decide({})
        assert dec.weights_used["futures"] > 0.0


class TestDynamicWeightsCaching:

    def test_performance_fetched_once_within_refresh_window(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
        monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_REFRESH_SECONDS", 300)
        journal = FakeJournal(rows=[{"agent": "SMC_ANALYST", "total_trades": 30,
                                      "wins": 20, "losses": 10, "win_rate": 0.67,
                                      "total_pnl": 500.0}])
        ceo = CEOAgent(agents=_agents(), journal=journal)
        ceo.decide({})
        ceo.decide({})
        ceo.decide({})
        assert journal.call_count == 1

    def test_weights_used_present_in_to_dict(self, monkeypatch):
        monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", False)
        ceo = CEOAgent(agents=_agents())
        dec = ceo.decide({})
        d = dec.to_dict()
        assert "weights_used" in d
        assert d["weights_used"] == CEOAgent.WEIGHTS
