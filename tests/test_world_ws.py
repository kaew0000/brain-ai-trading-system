"""tests/test_world_ws.py — Phase W10

Tests both the /ws/world connection handler (via FastAPI's
websocket_connect TestClient) and check_and_broadcast() directly (async,
via asyncio.run — no network, no Binance, no dashboard, no real event
loop from api/app.py's own _broadcast_loop needed). Mirrors
tests/test_portfolio_ws.py's structure exactly.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from api import world_ws

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset():
    world_ws._reset_for_tests()
    yield
    world_ws._reset_for_tests()


def test_connect_receives_init_frame():
    from api.app import app
    client = TestClient(app, raise_server_exceptions=False)
    with client.websocket_connect("/ws/world") as ws:
        data = ws.receive_json()
    assert data["type"] == "init"
    assert "characters" in data["data"]


def test_check_and_broadcast_with_no_clients_is_a_noop():
    asyncio.run(world_ws.check_and_broadcast())  # must not raise


def test_heartbeat_sent_immediately_on_first_check():
    from api.app import app
    client = TestClient(app, raise_server_exceptions=False)
    with client.websocket_connect("/ws/world") as ws:
        ws.receive_json()  # init frame
        asyncio.run(world_ws.check_and_broadcast())
        msg = ws.receive_json()
    assert msg["type"] == "heartbeat"


def test_no_duplicate_broadcast_for_same_tick(monkeypatch):
    from world.simulation import api as simulation_api

    calls: list[dict] = []

    async def _fake_broadcast(message):
        calls.append(message)

    monkeypatch.setattr(world_ws, "_broadcast", _fake_broadcast)
    world_ws._clients.add(object())  # truthy "someone is connected" without a real socket
    world_ws._last_heartbeat_at = 9e18  # suppress heartbeat noise for this check

    simulation_api.step()
    asyncio.run(world_ws.check_and_broadcast())
    asyncio.run(world_ws.check_and_broadcast())

    simulation_calls = [c for c in calls if c["type"] == "simulation"]
    assert len(simulation_calls) == 1
