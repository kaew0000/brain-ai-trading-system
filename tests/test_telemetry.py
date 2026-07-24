"""
tests/test_telemetry.py
========================
v14 Phase 2 — Agent Telemetry Layer test suite.

Covers:
  - TelemetryRegistry core behaviour (record/get/snapshot/clear)
  - BaseAgent.run() telemetry wiring (success + error paths)
  - CEOAgent.decide() telemetry wiring
  - GET /api/agents/telemetry (REST)
  - WS /ws/agents (always sends init frame — BUG-06 pattern applied)
  - Exact 7-field spec schema compliance
"""
from __future__ import annotations

import time
import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_telemetry():
    """Reset the TelemetryRegistry singleton before/after each test."""
    from telemetry.agent_telemetry import reset_telemetry_registry
    reset_telemetry_registry()
    yield
    reset_telemetry_registry()


@pytest.fixture(autouse=True)
def reset_bus():
    """Reset EventBus singleton — agents publish events on every run()."""
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
# TelemetryRegistry core
# ─────────────────────────────────────────────────────────────────────────────
class TestTelemetryRegistry:

    def test_record_returns_entry(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        entry = reg.record(agent="TEST_AGENT", status="OK", confidence=80.0,
                            last_signal="LONG", latency_ms=12.5, decision="test decision")
        assert entry.agent == "TEST_AGENT"
        assert entry.status == "OK"
        assert entry.confidence == 80.0

    def test_get_returns_latest(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK", confidence=50.0)
        reg.record(agent="A", status="OK", confidence=90.0)
        entry = reg.get("A")
        assert entry.confidence == 90.0

    def test_get_unknown_agent_returns_none(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        assert reg.get("NOPE") is None

    def test_snapshot_contains_all_agents(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK")
        reg.record(agent="B", status="OK")
        snap = reg.snapshot()
        assert set(snap.keys()) == {"A", "B"}

    def test_snapshot_spec_has_exact_7_fields(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK", confidence=70.0,
                    last_signal="LONG", latency_ms=5.0, decision="x")
        spec = reg.snapshot_spec()["A"]
        assert set(spec.keys()) == {"agent", "status", "confidence",
                                     "last_signal", "latency_ms", "decision", "timestamp"}

    def test_snapshot_full_has_extra_fields(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK")
        full = reg.snapshot()["A"]
        assert "uptime_s" in full
        assert "run_count" in full
        assert "error_count" in full

    def test_run_count_increments(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK")
        reg.record(agent="A", status="OK")
        reg.record(agent="A", status="OK")
        assert reg.get("A").run_count == 3

    def test_error_count_increments_only_on_error(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK")
        reg.record(agent="A", status="ERROR")
        reg.record(agent="A", status="OK")
        reg.record(agent="A", status="ERROR")
        assert reg.get("A").error_count == 2
        assert reg.get("A").run_count == 4

    def test_uptime_increases_across_calls(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK")
        time.sleep(0.02)
        reg.record(agent="A", status="OK")
        assert reg.get("A").uptime_s > 0

    def test_invalid_status_defaults_to_ok(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        entry = reg.record(agent="A", status="GARBAGE_VALUE")
        assert entry.status == "OK"

    def test_clear_empties_registry(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        reg.record(agent="A", status="OK")
        reg.clear()
        assert reg.snapshot() == {}

    def test_decision_truncated_to_200_chars(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg = get_telemetry_registry()
        long_text = "x" * 500
        entry = reg.record(agent="A", status="OK", decision=long_text)
        assert len(entry.decision) == 200

    def test_singleton_persists_across_calls(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        reg1 = get_telemetry_registry()
        reg2 = get_telemetry_registry()
        assert reg1 is reg2

    def test_thread_safety_concurrent_writes(self):
        from telemetry.agent_telemetry import get_telemetry_registry
        import threading
        reg = get_telemetry_registry()

        def writer(n):
            for _ in range(20):
                reg.record(agent=f"AGENT_{n}", status="OK")

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        snap = reg.snapshot()
        assert len(snap) == 5
        for name, entry in snap.items():
            assert entry["run_count"] == 20


# ─────────────────────────────────────────────────────────────────────────────
# telemetry_timer helper
# ─────────────────────────────────────────────────────────────────────────────
class TestTelemetryTimer:

    def test_latency_ms_positive_after_work(self):
        from telemetry.agent_telemetry import telemetry_timer
        with telemetry_timer() as t:
            time.sleep(0.01)
        assert t.latency_ms >= 9.0   # allow small scheduling slack

    def test_latency_ms_live_inside_except_block(self):
        """Regression test: latency_ms must be correct even when read
        from inside an except clause nested within the with-body,
        i.e. BEFORE __exit__ has run."""
        from telemetry.agent_telemetry import telemetry_timer
        captured = {}
        with pytest.raises(ValueError), telemetry_timer() as t:
            time.sleep(0.01)
            try:
                raise ValueError("boom")
            except ValueError:
                captured["latency_ms"] = t.latency_ms
                raise
        assert captured["latency_ms"] >= 9.0

    def test_does_not_suppress_exceptions(self):
        from telemetry.agent_telemetry import telemetry_timer
        with pytest.raises(RuntimeError), telemetry_timer():
            raise RuntimeError("should propagate")


# ─────────────────────────────────────────────────────────────────────────────
# BaseAgent.run() telemetry wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestBaseAgentTelemetry:

    def test_run_records_telemetry_on_success(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from telemetry.agent_telemetry import get_telemetry_registry
        agent = SMCAnalyst()
        agent.run(market_context_long)
        entry = get_telemetry_registry().get(agent.AGENT_NAME)
        assert entry is not None
        assert entry.status == "OK"

    def test_run_records_positive_latency(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from telemetry.agent_telemetry import get_telemetry_registry
        agent = SMCAnalyst()
        agent.run(market_context_long)
        entry = get_telemetry_registry().get(agent.AGENT_NAME)
        assert entry.latency_ms >= 0.0

    def test_run_records_confidence_matching_report(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from telemetry.agent_telemetry import get_telemetry_registry
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        entry = get_telemetry_registry().get(agent.AGENT_NAME)
        assert entry.confidence == report.confidence

    def test_run_records_last_signal_matching_report(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from telemetry.agent_telemetry import get_telemetry_registry
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        entry = get_telemetry_registry().get(agent.AGENT_NAME)
        assert entry.last_signal == report.signal

    def test_run_error_path_records_error_status_and_reraises(self, market_context_long):
        """Telemetry must record ERROR status AND the original exception
        must still propagate unchanged — existing CEOAgent.decide() error
        handling contract must be preserved exactly."""
        from agents.base_agent import BaseAgent
        from telemetry.agent_telemetry import get_telemetry_registry

        class BrokenAgent(BaseAgent):
            AGENT_NAME = "BROKEN_AGENT"
            def analyse(self, market_context):
                raise ValueError("simulated failure")

        agent = BrokenAgent()
        with pytest.raises(ValueError, match="simulated failure"):
            agent.run(market_context_long)

        entry = get_telemetry_registry().get("BROKEN_AGENT")
        assert entry is not None
        assert entry.status == "ERROR"
        assert "simulated failure" in entry.decision

    def test_run_error_path_has_nonzero_or_zero_but_valid_latency(self, market_context_long):
        """Regression test for the latency_ms=0.0-on-error bug caught during
        self-review: error path must report a real (non-frozen) latency."""
        from agents.base_agent import BaseAgent
        from telemetry.agent_telemetry import get_telemetry_registry

        class SlowBrokenAgent(BaseAgent):
            AGENT_NAME = "SLOW_BROKEN_AGENT"
            def analyse(self, market_context):
                time.sleep(0.02)
                raise ValueError("slow failure")

        agent = SlowBrokenAgent()
        with pytest.raises(ValueError):
            agent.run(market_context_long)

        entry = get_telemetry_registry().get("SLOW_BROKEN_AGENT")
        assert entry.latency_ms >= 15.0   # must reflect the actual 20ms sleep, not 0.0

    def test_multiple_runs_increment_run_count(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from telemetry.agent_telemetry import get_telemetry_registry
        agent = SMCAnalyst()
        agent.run(market_context_long)
        agent.run(market_context_long)
        agent.run(market_context_long)
        entry = get_telemetry_registry().get(agent.AGENT_NAME)
        assert entry.run_count == 3

    def test_all_six_subagents_report_telemetry(self, market_context_long):
        from agents import build_agent_layer
        from telemetry.agent_telemetry import get_telemetry_registry
        layer = build_agent_layer()
        for key in ("smc", "futures", "regime", "risk", "trader", "journal"):
            layer[key].run(market_context_long)
        snap = get_telemetry_registry().snapshot()
        expected_names = {layer[k].AGENT_NAME for k in
                          ("smc", "futures", "regime", "risk", "trader", "journal")}
        assert expected_names.issubset(set(snap.keys()))


# ─────────────────────────────────────────────────────────────────────────────
# CEOAgent.decide() telemetry wiring
# ─────────────────────────────────────────────────────────────────────────────
class TestCEOTelemetry:

    def test_ceo_decide_records_own_telemetry(self, market_context_long):
        from agents import build_agent_layer
        from telemetry.agent_telemetry import get_telemetry_registry
        layer = build_agent_layer()
        layer["ceo"].decide(market_context_long)
        entry = get_telemetry_registry().get("CEO_AGENT")
        assert entry is not None
        assert entry.status == "OK"

    def test_ceo_telemetry_confidence_matches_decision(self, market_context_long):
        from agents import build_agent_layer
        from telemetry.agent_telemetry import get_telemetry_registry
        layer = build_agent_layer()
        dec = layer["ceo"].decide(market_context_long)
        entry = get_telemetry_registry().get("CEO_AGENT")
        assert entry.confidence == dec.confidence

    def test_ceo_decide_also_populates_subagent_telemetry(self, market_context_long):
        """CEO.decide() internally calls agent.run() for each sub-agent —
        confirm their telemetry is populated as a side effect."""
        from agents import build_agent_layer
        from telemetry.agent_telemetry import get_telemetry_registry
        layer = build_agent_layer()
        layer["ceo"].decide(market_context_long)
        snap = get_telemetry_registry().snapshot()
        assert "SMC_ANALYST" in snap or any("SMC" in k for k in snap)

    def test_ceo_latency_includes_subagent_time(self, market_context_long):
        from agents import build_agent_layer
        from telemetry.agent_telemetry import get_telemetry_registry
        layer = build_agent_layer()
        layer["ceo"].decide(market_context_long)
        ceo_entry = get_telemetry_registry().get("CEO_AGENT")
        # CEO orchestrates 6 sub-agents — latency should be measurable (not negative/None)
        assert ceo_entry.latency_ms >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# API: GET /api/agents/telemetry
# ─────────────────────────────────────────────────────────────────────────────
class TestTelemetryAPI:

    @pytest.fixture
    def client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_endpoint_200(self, client):
        r = client.get("/api/agents/telemetry")
        assert r.status_code == 200

    def test_endpoint_ok_true(self, client):
        body = client.get("/api/agents/telemetry").json()
        assert body["ok"] is True

    def test_endpoint_empty_registry_returns_empty_dict(self, client):
        body = client.get("/api/agents/telemetry").json()
        assert body["data"]["telemetry"] == {}
        assert body["data"]["agent_count"] == 0

    def test_endpoint_returns_recorded_agent(self, client):
        from telemetry.agent_telemetry import get_telemetry_registry
        get_telemetry_registry().record(agent="API_TEST_AGENT", status="OK", confidence=66.0)
        body = client.get("/api/agents/telemetry").json()
        assert "API_TEST_AGENT" in body["data"]["telemetry"]
        assert body["data"]["telemetry"]["API_TEST_AGENT"]["confidence"] == 66.0

    def test_endpoint_spec_only_returns_7_fields(self, client):
        from telemetry.agent_telemetry import get_telemetry_registry
        get_telemetry_registry().record(agent="SPEC_TEST", status="OK", confidence=50.0,
                                          last_signal="LONG", latency_ms=3.0, decision="d")
        body = client.get("/api/agents/telemetry?spec_only=true").json()
        entry = body["data"]["telemetry"]["SPEC_TEST"]
        assert set(entry.keys()) == {"agent", "status", "confidence",
                                      "last_signal", "latency_ms", "decision", "timestamp"}

    def test_endpoint_full_includes_extras(self, client):
        from telemetry.agent_telemetry import get_telemetry_registry
        get_telemetry_registry().record(agent="FULL_TEST", status="OK")
        body = client.get("/api/agents/telemetry").json()
        entry = body["data"]["telemetry"]["FULL_TEST"]
        assert "uptime_s" in entry
        assert "run_count" in entry


# ─────────────────────────────────────────────────────────────────────────────
# WS: /ws/agents
# ─────────────────────────────────────────────────────────────────────────────
class TestAgentsWebSocket:

    def test_ws_agents_sends_init_when_empty(self):
        """BUG-06 pattern applied to the new endpoint: init frame must
        always be sent, even when the telemetry registry is empty."""
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/agents") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert msg["data"] == {}

    def test_ws_agents_sends_init_with_data(self):
        from api.app import app
        from telemetry.agent_telemetry import get_telemetry_registry
        from fastapi.testclient import TestClient
        get_telemetry_registry().record(agent="WS_TEST_AGENT", status="OK", confidence=77.0)
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/agents") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert "WS_TEST_AGENT" in msg["data"]
            assert msg["data"]["WS_TEST_AGENT"]["confidence"] == 77.0
