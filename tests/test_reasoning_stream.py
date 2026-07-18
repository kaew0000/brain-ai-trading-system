"""
tests/test_reasoning_stream.py
================================
v14 Phase 2.5 — Agent Reasoning Stream test suite.

Covers:
  - ReasoningStream core behaviour (record/get_recent/get_latest/clear)
  - BaseAgent.run() reasoning wiring (thought/reasoning text generation)
  - CEOAgent.decide() reasoning wiring
  - GET /api/agents/reasoning (REST, all query param modes)
  - Exact 6-field spec schema compliance
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_reasoning():
    from reasoning.reasoning_stream import reset_reasoning_stream
    reset_reasoning_stream()
    yield
    reset_reasoning_stream()


@pytest.fixture(autouse=True)
def reset_telemetry():
    from telemetry.agent_telemetry import reset_telemetry_registry
    reset_telemetry_registry()
    yield
    reset_telemetry_registry()


@pytest.fixture(autouse=True)
def reset_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


@pytest.fixture
def market_context_long():
    return {
        "regime": "TREND", "regime_conf": 0.75,
        "trend_bias": "LONG_BIAS", "trend_strength": "STRONG", "trend_conf": 0.8,
        "mtf_aligned": True, "mtf_direction": "LONG",
        "smc_m15": {
            "bos": True, "bos_dir": "Bullish",
            "choch": False, "choch_dir": "",
            "fvg": True, "fvg_dir": "Bullish",
            "ob": True, "ob_dir": "Bullish",
            "trend_bias": "LONG_BIAS",
            "liquidity_high": 68000.0, "liquidity_low": 64000.0,
            "prev_high": 67500.0, "prev_low": 64500.0,
        },
        "smc_h1":  {"bos": True, "bos_dir": "Bullish", "trend_bias": "LONG_BIAS",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "smc_h4":  {"bos": True, "bos_dir": "Bullish", "trend_bias": "LONG_BIAS",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "futures": {
            "funding":      {"rate": 0.0001, "annualised": 10.0, "extreme": False, "bias": "LONG_PAYING"},
            "open_interest":{"delta_pct": 0.012, "trend": "RISING", "pressure": "BULLISH"},
            "long_short":   {"ratio": 1.15, "crowd_bias": "NEUTRAL", "contrarian_signal": "NEUTRAL"},
            "taker":        {"buy_ratio": 0.58, "sell_ratio": 0.42, "aggressor": "BUY"},
            "liquidation":  {"detected": False, "type": "", "severity": "LOW"},
        },
        "funding_rate": 0.0001,
        "oi_delta": 0.012,
        "mark_price": 67000.0,
        "balance": 10000.0,
        "trend_data": {"ema_stack": "BULLISH", "adx": 32.0, "rsi": 55.0},
    }


# ─────────────────────────────────────────────────────────────────────────────
# ReasoningStream core
# ─────────────────────────────────────────────────────────────────────────────
class TestReasoningStream:

    def test_record_returns_entry(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        entry = stream.record(agent="A", thought="t", reasoning="r",
                               decision="LONG", confidence=70.0)
        assert entry.agent == "A"
        assert entry.thought == "t"
        assert entry.reasoning == "r"
        assert entry.decision == "LONG"
        assert entry.confidence == 70.0

    def test_get_recent_newest_first(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        stream.record(agent="A", thought="first", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="A", thought="second", reasoning="r", decision="LONG", confidence=2)
        recent = stream.get_recent(limit=10)
        assert recent[0]["thought"] == "second"
        assert recent[1]["thought"] == "first"

    def test_get_recent_filters_by_agent(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        stream.record(agent="A", thought="a1", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="B", thought="b1", reasoning="r", decision="LONG", confidence=1)
        recent = stream.get_recent(agent="A")
        assert len(recent) == 1
        assert recent[0]["agent"] == "A"

    def test_get_recent_respects_limit(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        for i in range(10):
            stream.record(agent="A", thought=f"t{i}", reasoning="r", decision="LONG", confidence=1)
        recent = stream.get_recent(limit=3)
        assert len(recent) == 3

    def test_get_latest_overall(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        stream.record(agent="A", thought="old", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="B", thought="new", reasoning="r", decision="LONG", confidence=1)
        latest = stream.get_latest()
        assert latest["thought"] == "new"

    def test_get_latest_for_agent(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        stream.record(agent="A", thought="a-old", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="A", thought="a-new", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="B", thought="b-new", reasoning="r", decision="LONG", confidence=1)
        latest = stream.get_latest(agent="A")
        assert latest["thought"] == "a-new"

    def test_get_latest_unknown_agent_returns_none(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        assert stream.get_latest(agent="NOPE") is None

    def test_get_latest_empty_stream_returns_none(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        assert stream.get_latest() is None

    def test_get_latest_all_returns_one_per_agent(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        stream.record(agent="A", thought="a1", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="A", thought="a2", reasoning="r", decision="LONG", confidence=1)
        stream.record(agent="B", thought="b1", reasoning="r", decision="LONG", confidence=1)
        all_latest = stream.get_latest_all()
        assert set(all_latest.keys()) == {"A", "B"}
        assert all_latest["A"]["thought"] == "a2"

    def test_clear_empties_stream(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        stream.record(agent="A", thought="t", reasoning="r", decision="LONG", confidence=1)
        stream.clear()
        assert stream.get_recent() == []
        assert stream.get_latest() is None

    def test_thought_truncated_to_300_chars(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        entry = stream.record(agent="A", thought="x" * 1000, reasoning="r",
                               decision="LONG", confidence=1)
        assert len(entry.thought) == 300

    def test_reasoning_truncated_to_2000_chars(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        entry = stream.record(agent="A", thought="t", reasoning="x" * 5000,
                               decision="LONG", confidence=1)
        assert len(entry.reasoning) == 2000

    def test_singleton_persists(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        assert get_reasoning_stream() is get_reasoning_stream()

    def test_entry_has_exact_6_fields(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        stream = get_reasoning_stream()
        entry = stream.record(agent="A", thought="t", reasoning="r",
                               decision="LONG", confidence=1)
        d = entry.to_dict()
        assert set(d.keys()) == {"agent", "thought", "reasoning", "decision",
                                  "confidence", "timestamp"}

    def test_thread_safety_concurrent_writes(self):
        from reasoning.reasoning_stream import get_reasoning_stream
        import threading
        stream = get_reasoning_stream()

        def writer(n):
            for i in range(15):
                stream.record(agent=f"AGENT_{n}", thought=f"t{i}", reasoning="r",
                               decision="LONG", confidence=i)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()

        all_latest = stream.get_latest_all()
        assert len(all_latest) == 4


# ─────────────────────────────────────────────────────────────────────────────
# BaseAgent.run() reasoning wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestBaseAgentReasoning:

    def test_run_records_reasoning_entry(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from reasoning.reasoning_stream import get_reasoning_stream
        agent = SMCAnalyst()
        agent.run(market_context_long)
        entry = get_reasoning_stream().get_latest(agent=agent.AGENT_NAME)
        assert entry is not None

    def test_reasoning_decision_matches_report_signal(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from reasoning.reasoning_stream import get_reasoning_stream
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        entry = get_reasoning_stream().get_latest(agent=agent.AGENT_NAME)
        assert entry["decision"] == report.signal

    def test_reasoning_confidence_matches_report(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from reasoning.reasoning_stream import get_reasoning_stream
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        entry = get_reasoning_stream().get_latest(agent=agent.AGENT_NAME)
        assert entry["confidence"] == report.confidence

    def test_reasoning_text_built_from_factors(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from reasoning.reasoning_stream import get_reasoning_stream
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        entry = get_reasoning_stream().get_latest(agent=agent.AGENT_NAME)
        if report.factors:
            # reasoning text should reference at least the first factor's name
            assert report.factors[0]["name"] in entry["reasoning"]

    def test_no_reasoning_recorded_on_error(self, market_context_long):
        from agents.base_agent import BaseAgent
        from reasoning.reasoning_stream import get_reasoning_stream

        class BrokenAgent(BaseAgent):
            AGENT_NAME = "BROKEN_REASONING_AGENT"
            def analyse(self, market_context):
                raise ValueError("boom")

        agent = BrokenAgent()
        with pytest.raises(ValueError):
            agent.run(market_context_long)

        entry = get_reasoning_stream().get_latest(agent="BROKEN_REASONING_AGENT")
        assert entry is None   # no reasoning entry on failure — only telemetry ERROR

    def test_multiple_subagents_each_get_reasoning(self, market_context_long):
        from agents import build_agent_layer
        from reasoning.reasoning_stream import get_reasoning_stream
        layer = build_agent_layer()
        for key in ("smc", "futures", "regime", "risk", "trader", "journal"):
            layer[key].run(market_context_long)
        all_latest = get_reasoning_stream().get_latest_all()
        expected = {layer[k].AGENT_NAME for k in
                    ("smc", "futures", "regime", "risk", "trader", "journal")}
        assert expected.issubset(set(all_latest.keys()))

    def test_default_thought_text_fallback(self, market_context_long):
        """If report.summary is falsy, _thought_text falls back to a generated sentence."""
        from agents.base_agent import BaseAgent, AgentReport

        class BlankSummaryAgent(BaseAgent):
            AGENT_NAME = "BLANK_SUMMARY_AGENT"
            def analyse(self, market_context):
                return AgentReport(agent=self.AGENT_NAME, signal="NEUTRAL",
                                    confidence=0.0, summary="", factors=[], raw={})

        agent = BlankSummaryAgent()
        report = agent.run(market_context_long)
        thought = agent._thought_text(report)
        assert "BLANK_SUMMARY_AGENT" in thought


# ─────────────────────────────────────────────────────────────────────────────
# CEOAgent.decide() reasoning wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestCEOReasoning:

    def test_ceo_decide_records_reasoning(self, market_context_long):
        from agents import build_agent_layer
        from reasoning.reasoning_stream import get_reasoning_stream
        layer = build_agent_layer()
        layer["ceo"].decide(market_context_long)
        entry = get_reasoning_stream().get_latest(agent="CEO_AGENT")
        assert entry is not None

    def test_ceo_reasoning_decision_matches(self, market_context_long):
        from agents import build_agent_layer
        from reasoning.reasoning_stream import get_reasoning_stream
        layer = build_agent_layer()
        dec = layer["ceo"].decide(market_context_long)
        entry = get_reasoning_stream().get_latest(agent="CEO_AGENT")
        assert entry["decision"] == dec.action

    def test_ceo_reasoning_nonempty_text(self, market_context_long):
        from agents import build_agent_layer
        from reasoning.reasoning_stream import get_reasoning_stream
        layer = build_agent_layer()
        layer["ceo"].decide(market_context_long)
        entry = get_reasoning_stream().get_latest(agent="CEO_AGENT")
        assert len(entry["reasoning"]) > 0


# ─────────────────────────────────────────────────────────────────────────────
# API: GET /api/agents/reasoning
# ─────────────────────────────────────────────────────────────────────────────
class TestReasoningAPI:

    @pytest.fixture
    def client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_endpoint_200(self, client):
        r = client.get("/api/agents/reasoning")
        assert r.status_code == 200

    def test_endpoint_empty_stream_returns_empty_list(self, client):
        body = client.get("/api/agents/reasoning").json()
        assert body["data"]["reasoning"] == []
        assert body["data"]["entry_count"] == 0

    def test_endpoint_returns_recorded_entry(self, client):
        from reasoning.reasoning_stream import get_reasoning_stream
        get_reasoning_stream().record(agent="API_TEST", thought="t", reasoning="r",
                                       decision="LONG", confidence=55.0)
        body = client.get("/api/agents/reasoning").json()
        assert body["data"]["entry_count"] == 1
        assert body["data"]["reasoning"][0]["agent"] == "API_TEST"

    def test_endpoint_filter_by_agent(self, client):
        from reasoning.reasoning_stream import get_reasoning_stream
        s = get_reasoning_stream()
        s.record(agent="A", thought="a", reasoning="r", decision="LONG", confidence=1)
        s.record(agent="B", thought="b", reasoning="r", decision="LONG", confidence=1)
        body = client.get("/api/agents/reasoning?agent=A").json()
        assert body["data"]["entry_count"] == 1
        assert body["data"]["reasoning"][0]["agent"] == "A"

    def test_endpoint_limit_param(self, client):
        from reasoning.reasoning_stream import get_reasoning_stream
        s = get_reasoning_stream()
        for i in range(10):
            s.record(agent="A", thought=f"t{i}", reasoning="r", decision="LONG", confidence=1)
        body = client.get("/api/agents/reasoning?limit=3").json()
        assert body["data"]["entry_count"] == 3

    def test_endpoint_latest_only_mode(self, client):
        from reasoning.reasoning_stream import get_reasoning_stream
        s = get_reasoning_stream()
        s.record(agent="A", thought="a1", reasoning="r", decision="LONG", confidence=1)
        s.record(agent="A", thought="a2", reasoning="r", decision="LONG", confidence=1)
        s.record(agent="B", thought="b1", reasoning="r", decision="LONG", confidence=1)
        body = client.get("/api/agents/reasoning?latest_only=true").json()
        assert body["data"]["agent_count"] == 2
        assert body["data"]["reasoning"]["A"]["thought"] == "a2"

    def test_endpoint_latest_only_with_agent_filter(self, client):
        from reasoning.reasoning_stream import get_reasoning_stream
        s = get_reasoning_stream()
        s.record(agent="A", thought="a1", reasoning="r", decision="LONG", confidence=1)
        s.record(agent="B", thought="b1", reasoning="r", decision="LONG", confidence=1)
        body = client.get("/api/agents/reasoning?latest_only=true&agent=A").json()
        assert body["data"]["agent_count"] == 1
        assert "A" in body["data"]["reasoning"]

    def test_endpoint_entries_have_spec_schema(self, client):
        from reasoning.reasoning_stream import get_reasoning_stream
        get_reasoning_stream().record(agent="SCHEMA_TEST", thought="t", reasoning="r",
                                       decision="LONG", confidence=1)
        body = client.get("/api/agents/reasoning").json()
        entry = body["data"]["reasoning"][0]
        assert set(entry.keys()) == {"agent", "thought", "reasoning", "decision",
                                      "confidence", "timestamp"}
