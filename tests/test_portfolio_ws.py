"""tests/test_portfolio_ws.py — V16 Phase 2C

Tests both the /ws/portfolio connection handler (via FastAPI's
websocket_connect TestClient) and check_and_broadcast() directly
(async, called via pytest-asyncio-free asyncio.run — no network, no
Binance, no dashboard, no real event loop from api/app.py's own
_broadcast_loop needed).

Module-level dedup/heartbeat state in api.portfolio_ws is reset via
_reset_for_tests() before every test — see that function's docstring
for why it's module-level in the first place.
"""
from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

import api.portfolio_ws as portfolio_ws
from events.event_bus import reset_event_bus
from execution.execution_events import ExecutionEventType, publish_execution_event

pytestmark = pytest.mark.unit


def _row(row_id=1, symbol="BTCUSDT", replacements=None):
    return {
        "id": row_id,
        "timestamp": "2026-07-19T00:00:00+00:00",
        "decided_at": 1750000000.0 + row_id,
        "blocked": False,
        "block_reason": None,
        "selected_count": 1,
        "rejected_count": 0,
        "replacement_count": len(replacements or []),
        "total_capital_allocated": 500.0,
        "total_risk_allocated": 5.0,
        "diversification_score": 100.0,
        "portfolio_score": 80.0,
        "drawdown": 0.0,
        "data": {
            "selected": [{"symbol": symbol, "capital_amount": 500.0, "priority": 1}],
            "rejected": [],
            "replacements": replacements or [],
            "sector_exposure": {"Layer1": 4000.0},
        },
    }


@pytest.fixture(autouse=True)
def _reset():
    portfolio_ws._reset_for_tests()
    reset_event_bus()
    yield
    portfolio_ws._reset_for_tests()
    reset_event_bus()


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


class TestWsPortfolioInitFrame:
    def test_init_frame_sent_immediately_on_connect(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            frame = ws.receive_json()
            assert frame["type"] == "init"

    def test_init_frame_null_decision_when_nothing_persisted(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            frame = ws.receive_json()
            assert frame["decision"]["decision"] is None
            assert frame["state"]["positions"] == []

    def test_init_frame_real_data_when_something_persisted(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: [_row()]
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            frame = ws.receive_json()
            assert frame["decision"]["decision"]["selected"][0]["symbol"] == "BTCUSDT"
            assert frame["state"]["positions"][0]["symbol"] == "BTCUSDT"

    def test_init_frame_reconnect_gets_latest_regardless_of_dedup_state(self, client, monkeypatch):
        # Simulate a decision already having been broadcast to earlier
        # clients (dedup state set) before this NEW connection arrives —
        # it must still get the full current snapshot in its init frame,
        # not "nothing, you already missed it".
        portfolio_ws._last_broadcast_row_id = 99
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: [_row(row_id=99)]
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            frame = ws.receive_json()
            assert frame["decision"]["decision"]["selected"][0]["symbol"] == "BTCUSDT"

    def test_client_registered_after_connect(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        assert portfolio_ws.client_count() == 0
        with client.websocket_connect("/ws/portfolio") as ws:
            ws.receive_json()
            assert portfolio_ws.client_count() == 1

    def test_client_unregistered_after_disconnect(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            ws.receive_json()
        assert portfolio_ws.client_count() == 0


class TestCheckAndBroadcastDedup:
    """These call check_and_broadcast() directly (the function
    api/app.py's existing broadcast loop calls once per tick) against a
    fake connected client, so dedup/heartbeat logic is tested without
    depending on that loop's real 1s cadence."""

    def _fake_ws(self, sink: list):
        class _FakeWS:
            async def send_text(self, msg):
                sink.append(msg)
        return _FakeWS()

    def test_no_data_ever_persisted_stays_idle_besides_heartbeat(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        # Heartbeat fires (first call, elapsed >= interval from epoch 0),
        # but nothing else — no decision/state/sectors/allocations frames.
        types = [__import__("json").loads(m)["type"] for m in sink]
        assert types == ["heartbeat"]

    def test_new_row_broadcasts_all_expected_event_types(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: [_row(row_id=1)]
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        import json as _json
        types = [_json.loads(m)["type"] for m in sink]
        assert "decision" in types
        assert "state" in types
        assert "sectors" in types
        assert "allocations" in types

    def test_unchanged_row_id_does_not_rebroadcast(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: [_row(row_id=5)]
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        first_count = len(sink)
        # Force heartbeat not to fire again this tick so we isolate the
        # decision-dedup behavior specifically.
        portfolio_ws._last_heartbeat_at = time.time()
        asyncio.run(portfolio_ws.check_and_broadcast())
        assert len(sink) == first_count  # nothing new broadcast — same row id

    def test_new_row_id_after_unchanged_triggers_fresh_broadcast(self, monkeypatch):
        state = {"row": _row(row_id=1)}
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions",
            lambda limit=1: [state["row"]],
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        first_count = len(sink)
        state["row"] = _row(row_id=2)
        portfolio_ws._last_heartbeat_at = time.time()
        asyncio.run(portfolio_ws.check_and_broadcast())
        assert len(sink) > first_count

    def test_no_clients_skips_decision_fetch_broadcast_but_heartbeat_state_still_tracked(self, monkeypatch):
        called = {"n": 0}

        def fake_get(limit=1):
            called["n"] += 1
            return []

        monkeypatch.setattr("api.portfolio_ws.portfolio_history.get_latest_decisions", fake_get)
        # No clients registered at all.
        asyncio.run(portfolio_ws.check_and_broadcast())
        # With zero clients, we still don't crash, and we don't bother
        # querying history for a broadcast nobody would receive.
        assert called["n"] == 0

    def test_heartbeat_not_resent_within_interval(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        first_count = len(sink)
        asyncio.run(portfolio_ws.check_and_broadcast())  # immediately again
        assert len(sink) == first_count  # no second heartbeat yet

    def test_heartbeat_resent_after_interval_elapses(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        first_count = len(sink)
        portfolio_ws._last_heartbeat_at -= (portfolio_ws.HEARTBEAT_INTERVAL_SECONDS + 1)
        asyncio.run(portfolio_ws.check_and_broadcast())
        assert len(sink) > first_count

    def test_replacement_proposal_broadcast_when_present(self, monkeypatch):
        proposal = {"incoming_symbol": "SOLUSDT", "outgoing_symbol": "DOGEUSDT", "reason": "test"}
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions",
            lambda limit=1: [_row(row_id=1, replacements=[proposal])],
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        import json as _json
        types = [_json.loads(m)["type"] for m in sink]
        assert "replacement_proposal" in types

    def test_no_replacement_proposal_event_when_none_present(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions",
            lambda limit=1: [_row(row_id=1, replacements=[])],
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        asyncio.run(portfolio_ws.check_and_broadcast())
        import json as _json
        types = [_json.loads(m)["type"] for m in sink]
        assert "replacement_proposal" not in types

    def test_dead_client_is_dropped_on_send_failure(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )

        class _DeadWS:
            async def send_text(self, msg):
                raise RuntimeError("connection closed")

        dead = _DeadWS()
        portfolio_ws._clients.add(dead)
        assert portfolio_ws.client_count() == 1
        asyncio.run(portfolio_ws.check_and_broadcast())
        assert dead not in portfolio_ws._clients


class TestWsPortfolioNoFabrication:
    def test_no_persisted_data_never_invents_a_symbol(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            frame = ws.receive_json()
            assert "BTCUSDT" not in str(frame)

    def test_init_frame_marks_every_section_not_live(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: [_row()]
        )
        with client.websocket_connect("/ws/portfolio") as ws:
            frame = ws.receive_json()
            assert frame["decision"]["live"] is False
            assert frame["state"]["live"] is False
            assert frame["sectors"]["live"] is False
            assert frame["allocations"]["live"] is False


class TestExecutionEventRelay:
    """V16 Phase 2E: check_and_broadcast() must also relay
    execution_orchestrator events published through the shared
    EventBus — independent of whether a portfolio decision changed in
    the same tick (see api/portfolio_ws.py's own module docstring
    addition for why that independence was the actual bug fixed here)."""

    def _fake_ws(self, sink: list):
        class _FakeWS:
            async def send_text(self, msg):
                sink.append(msg)
        return _FakeWS()

    def _no_decisions(self, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: []
        )

    def test_execution_event_relayed_even_with_no_decision_ever_persisted(self, monkeypatch):
        """This is the exact scenario the placement bug broke: no
        portfolio_history row exists at all, yet an execution event
        must still reach the client."""
        self._no_decisions(monkeypatch)
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))

        publish_execution_event(ExecutionEventType.STARTED, execution_id="exec-1", symbol="BTCUSDT")
        asyncio.run(portfolio_ws.check_and_broadcast())

        types = [__import__("json").loads(m)["type"] for m in sink]
        assert "execution_started" in types

    def test_execution_event_relayed_when_decision_row_unchanged(self, monkeypatch):
        """The far more common real scenario: a decision already
        broadcast in an earlier tick hasn't changed, but a NEW execution
        event has arrived since — this was the second way the placement
        bug silently dropped events."""
        monkeypatch.setattr(
            "api.portfolio_ws.portfolio_history.get_latest_decisions", lambda limit=1: [_row(row_id=1)]
        )
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))
        portfolio_ws._last_broadcast_row_id = 1  # simulate "already broadcast this decision"

        publish_execution_event(ExecutionEventType.COMPLETED, execution_id="exec-2", symbol="ETHUSDT")
        asyncio.run(portfolio_ws.check_and_broadcast())

        import json as _json
        types = [_json.loads(m)["type"] for m in sink]
        assert "decision" not in types       # unchanged row correctly NOT re-broadcast
        assert "execution_completed" in types  # but the new execution event still is

    def test_relayed_event_payload_matches_published_payload(self, monkeypatch):
        self._no_decisions(monkeypatch)
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))

        publish_execution_event(
            ExecutionEventType.FAILED, execution_id="exec-3", symbol="SOLUSDT",
            payload={"error": "Invalid qty=0"},
        )
        asyncio.run(portfolio_ws.check_and_broadcast())

        import json as _json
        frames = [_json.loads(m) for m in sink]
        failed = next(f for f in frames if f["type"] == "execution_failed")
        assert failed["data"]["symbol"] == "SOLUSDT"
        assert failed["data"]["error"] == "Invalid qty=0"

    def test_same_event_not_relayed_twice_across_ticks(self, monkeypatch):
        self._no_decisions(monkeypatch)
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))

        publish_execution_event(ExecutionEventType.STARTED, execution_id="exec-1", symbol="BTCUSDT")
        asyncio.run(portfolio_ws.check_and_broadcast())
        asyncio.run(portfolio_ws.check_and_broadcast())  # second tick, nothing new published

        import json as _json
        started_count = sum(1 for m in sink if _json.loads(m)["type"] == "execution_started")
        assert started_count == 1

    def test_multiple_new_events_relayed_in_chronological_order(self, monkeypatch):
        self._no_decisions(monkeypatch)
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))

        publish_execution_event(ExecutionEventType.STARTED, execution_id="exec-1", symbol="BTCUSDT")
        publish_execution_event(ExecutionEventType.COMPLETED, execution_id="exec-1", symbol="BTCUSDT")
        asyncio.run(portfolio_ws.check_and_broadcast())

        import json as _json
        types = [_json.loads(m)["type"] for m in sink if _json.loads(m)["type"].startswith("execution_")]
        assert types == ["execution_started", "execution_completed"]

    def test_no_clients_does_not_crash_and_nothing_relayed(self, monkeypatch):
        self._no_decisions(monkeypatch)
        publish_execution_event(ExecutionEventType.STARTED, execution_id="exec-1", symbol="BTCUSDT")
        asyncio.run(portfolio_ws.check_and_broadcast())  # no clients registered — must not raise

    def test_events_from_other_agents_are_not_relayed(self, monkeypatch):
        """Only EXECUTION_AGENT events go through this relay — an
        unrelated agent publishing to the same shared EventBus must not
        leak onto the portfolio WebSocket."""
        self._no_decisions(monkeypatch)
        sink = []
        portfolio_ws._clients.add(self._fake_ws(sink))

        from events.event_bus import get_event_bus
        get_event_bus().publish(agent="SOME_OTHER_AGENT", event="something_happened", message="x")
        asyncio.run(portfolio_ws.check_and_broadcast())

        import json as _json
        types = [_json.loads(m)["type"] for m in sink]
        assert "something_happened" not in types

