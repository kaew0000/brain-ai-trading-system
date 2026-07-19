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
    yield
    portfolio_ws._reset_for_tests()


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
