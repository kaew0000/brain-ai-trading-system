"""tests/test_world_api.py — Phase W10

REST endpoint tests against the real api.app FastAPI singleton (same
pattern as tests/test_portfolio_api.py), exercising the real
world.runtime/world.simulation/world.interaction/world.frontend.renderer
public APIs — no mocking needed, since those are already deterministic,
already-tested Track B modules. No network, no Binance, no dashboard.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


def test_get_world_state(client):
    r = client.get("/api/world/state")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_get_simulation_state(client):
    r = client.get("/api/world/simulation")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["characters"]) == 16
    assert len(data["rooms"]) == 17


def test_list_rooms(client):
    r = client.get("/api/world/rooms")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 17


def test_get_known_room(client):
    r = client.get("/api/world/rooms/ceo-tower")
    assert r.status_code == 200
    assert r.json()["data"]["roomId"] == "ceo-tower"


def test_get_unknown_room_is_404(client):
    r = client.get("/api/world/rooms/not-a-real-room")
    assert r.status_code == 404


def test_get_known_character(client):
    r = client.get("/api/world/characters/primus")
    assert r.status_code == 200
    assert r.json()["data"]["agentRef"] == "PRIMUS"


def test_get_unknown_character_is_404(client):
    r = client.get("/api/world/characters/not-a-real-agent")
    assert r.status_code == 404


def test_get_events(client):
    r = client.get("/api/world/events")
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


def test_get_room_frame(client):
    r = client.get("/api/world/rooms/ceo-tower/frame")
    assert r.status_code == 200
    assert r.json()["data"]["roomId"] == "ceo-tower"


def test_get_frame_for_unknown_room_is_404(client):
    r = client.get("/api/world/rooms/not-a-real-room/frame")
    assert r.status_code == 404


def test_select_and_read_back_selection(client):
    r = client.post("/api/world/select/room/ceo-tower")
    assert r.status_code == 200
    r2 = client.get("/api/world/selection")
    assert r2.status_code == 200
    assert r2.json()["data"]["targetId"] == "ceo-tower"


def test_select_unknown_kind_is_404(client):
    r = client.post("/api/world/select/not-a-kind/whatever")
    assert r.status_code == 404


def test_hover(client):
    r = client.post("/api/world/hover/character/primus")
    assert r.status_code == 200


def test_inspect_character(client):
    r = client.get("/api/world/inspect/character/primus")
    assert r.status_code == 200


def test_search(client):
    r = client.get("/api/world/search", params={"q": "primus"})
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


def test_search_requires_query(client):
    r = client.get("/api/world/search")
    assert r.status_code == 422


def test_notifications(client):
    r = client.get("/api/world/notifications")
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


def test_get_timeline(client):
    r = client.get("/api/world/timeline")
    assert r.status_code == 200
    assert "length" in r.json()["data"]


def test_timeline_pause_and_resume(client):
    r1 = client.post("/api/world/timeline/pause")
    assert r1.status_code == 200
    assert r1.json()["data"]["isPlaying"] is False
    r2 = client.post("/api/world/timeline/resume")
    assert r2.status_code == 200
    assert r2.json()["data"]["isPlaying"] is True


def test_timeline_seek_unknown_tick_is_404(client):
    r = client.post("/api/world/timeline/seek", params={"tick": 999999})
    assert r.status_code == 404


def test_command_focus_room(client):
    r = client.post("/api/world/command/focus_room", params={"target": "ceo-tower"})
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is True


def test_command_missing_target_is_400(client):
    r = client.post("/api/world/command/focus_room")
    assert r.status_code == 400


def test_command_pause_and_resume_simulation(client):
    r1 = client.post("/api/world/command/pause_simulation")
    assert r1.status_code == 200
    r2 = client.post("/api/world/command/resume_simulation")
    assert r2.status_code == 200


def test_command_set_simulation_speed(client):
    r = client.post("/api/world/command/set_simulation_speed", params={"speed": 2.0})
    assert r.status_code == 200


def test_command_set_simulation_speed_missing_speed_is_400(client):
    r = client.post("/api/world/command/set_simulation_speed")
    assert r.status_code == 400


def test_world_routes_default_to_viewer_role_like_every_other_api_route(client):
    """No auth-specific setup needed here — same as
    tests/test_portfolio_api.py: /api/* defaults to VIEWER via the
    existing prefix-generic _auth_middleware, and API_AUTH_ENABLED is
    false in this test environment, so every request already succeeds.
    This test documents that assumption rather than silently relying on it."""
    from api.app import _AUTH_OPERATOR_ROUTES
    world_operator_routes = [
        (method, path) for (method, path) in _AUTH_OPERATOR_ROUTES if path.startswith("/api/world")
    ]
    assert world_operator_routes == []
