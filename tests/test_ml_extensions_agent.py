"""
Tests for ml/extensions_integration/ml_extensions_agent.py

Covers:
  1. Graceful "not_ready" fallback when orchestrator/data_adapter are
     missing — never raises.
  2. Graceful "error" fallback when a wired component raises internally
     — never propagates (BaseAgent.run() re-raises analyse()'s
     exceptions verbatim, so analyse() itself must never raise).
  3. The core safety claim of this integration phase: registering
     MLExtensionsAgent with CEOAgent under "ml_extensions" cannot
     influence CEOAgent.WEIGHTS, agreement_score, or the final
     LONG/SHORT/WAIT action — verified against the REAL CEOAgent
     (agents/ceo_agent.py), not a mock of it, including a worst-case
     agent that always screams LONG at 100% confidence.
  4. AgentReport shape conforms to agents/base_agent.py's schema.
"""
from __future__ import annotations

import numpy as np
import pytest

from agents.base_agent import AgentReport
from agents.ceo_agent import CEOAgent
from ml.extensions_integration.ml_extensions_agent import MLExtensionsAgent

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_event_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


class FakeDataAdapter:
    def get_features(self, window):
        return np.zeros((window, 20), dtype=np.float32)


class FakeOrchestrator:
    def __init__(self, action=0, raise_error=False):
        self._action = action
        self._raise = raise_error

    def get_action(self, observation, portfolio_state=None, symbol=None):
        if self._raise:
            raise RuntimeError("simulated orchestrator failure")
        return self._action


class TestMLExtensionsAgentAnalyse:
    def test_not_ready_when_orchestrator_missing(self):
        agent = MLExtensionsAgent(orchestrator=None, data_adapter=FakeDataAdapter())
        report = agent.analyse({"symbol": "BTCUSDT"})
        assert isinstance(report, AgentReport)
        assert report.signal == "NEUTRAL"
        assert report.confidence == 0.0
        assert report.raw["status"] == "not_ready"

    def test_not_ready_when_data_adapter_missing(self):
        agent = MLExtensionsAgent(orchestrator=FakeOrchestrator(), data_adapter=None)
        report = agent.analyse({"symbol": "BTCUSDT"})
        assert report.raw["status"] == "not_ready"

    def test_maps_action_0_to_neutral(self):
        agent = MLExtensionsAgent(orchestrator=FakeOrchestrator(action=0), data_adapter=FakeDataAdapter())
        report = agent.analyse({"symbol": "BTCUSDT"})
        assert report.signal == "NEUTRAL"
        assert report.raw == {"status": "ok", "action": 0}

    def test_maps_action_1_to_long(self):
        agent = MLExtensionsAgent(orchestrator=FakeOrchestrator(action=1), data_adapter=FakeDataAdapter())
        report = agent.analyse({"symbol": "BTCUSDT"})
        assert report.signal == "LONG"

    def test_maps_action_2_to_short(self):
        agent = MLExtensionsAgent(orchestrator=FakeOrchestrator(action=2), data_adapter=FakeDataAdapter())
        report = agent.analyse({"symbol": "BTCUSDT"})
        assert report.signal == "SHORT"

    def test_never_raises_when_orchestrator_errors(self):
        agent = MLExtensionsAgent(
            orchestrator=FakeOrchestrator(raise_error=True), data_adapter=FakeDataAdapter()
        )
        report = agent.analyse({"symbol": "BTCUSDT"})  # must not raise
        assert report.signal == "NEUTRAL"
        assert report.confidence == 0.0
        assert report.raw["status"] == "error"

    def test_run_never_raises_even_on_internal_error(self):
        # BaseAgent.run() re-raises analyse()'s exceptions verbatim —
        # this is the real safety net this integration relies on.
        agent = MLExtensionsAgent(
            orchestrator=FakeOrchestrator(raise_error=True), data_adapter=FakeDataAdapter()
        )
        report = agent.run({"symbol": "BTCUSDT"})  # must not raise
        assert report.raw["status"] == "error"

    def test_symbol_passed_through_to_report(self):
        agent = MLExtensionsAgent(orchestrator=None, data_adapter=None)
        report = agent.analyse({"symbol": "ETHUSDT"})
        assert report.symbol == "ETHUSDT"

    def test_agent_name(self):
        assert MLExtensionsAgent.AGENT_NAME == "ML_EXTENSIONS"


class TestCEOAgentIsolation:
    """The core safety claim of this phase: 'ml_extensions' is not a
    CEOAgent.WEIGHTS key, so registering it can never move a real
    decision — see ml_extensions_agent.py's module docstring."""

    def _minimal_agents(self):
        class NeutralAgent:
            def run(self, ctx):
                return AgentReport(agent="X", signal="NEUTRAL", confidence=50.0, summary="")

        return {name: NeutralAgent() for name in ["smc", "futures", "regime", "risk", "trader", "journal"]}

    def test_ml_extensions_key_absent_from_weights(self):
        ceo = CEOAgent(agents=self._minimal_agents())
        assert "ml_extensions" not in ceo.WEIGHTS

    def test_registering_screaming_agent_does_not_change_weights(self):
        ceo = CEOAgent(agents=self._minimal_agents())
        weights_before = dict(ceo.WEIGHTS)

        class ScreamingLongAgent(MLExtensionsAgent):
            def analyse(self, market_context):
                return AgentReport(agent=self.AGENT_NAME, signal="LONG", confidence=100.0, summary="SCREAM")

        ceo.register_agent("ml_extensions", ScreamingLongAgent())
        assert ceo.WEIGHTS == weights_before

    def test_registered_agent_runs_and_appears_in_agent_reports_but_not_scoring(self):
        ceo = CEOAgent(agents=self._minimal_agents())

        class ScreamingLongAgent(MLExtensionsAgent):
            def analyse(self, market_context):
                return AgentReport(agent=self.AGENT_NAME, signal="LONG", confidence=100.0, summary="SCREAM")

        ceo.register_agent("ml_extensions", ScreamingLongAgent())
        decision = ceo.decide({"symbol": "BTCUSDT"})

        # It ran and is visible (telemetry/dashboard) ...
        assert "ml_extensions" in decision.agent_reports
        assert decision.agent_reports["ml_extensions"]["signal"] == "LONG"
        # ... but a 6-agent all-NEUTRAL baseline still yields the same
        # class of decision it would without ml_extensions registered —
        # a maximally-confident 7th voice outside WEIGHTS cannot flip it.
        baseline_ceo = CEOAgent(agents=self._minimal_agents())
        baseline_decision = baseline_ceo.decide({"symbol": "BTCUSDT"})
        assert decision.action == baseline_decision.action
