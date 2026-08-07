"""tests/test_workspace_api.py — Phase W12

REST endpoint tests against the real api.app FastAPI singleton (same
pattern as tests/test_world_api.py, Phase W10), exercising the real
world.workspace.api public facade — no mocking needed for the read
paths, since those are already deterministic, already-tested Track B
modules.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_workspace_state():
    from world.workspace import api as workspace_api
    workspace_api._reset_for_tests()
    yield
    workspace_api._reset_for_tests()
    workspace_api.reset_layout()


def test_get_layout(client):
    r = client.get("/api/workspace/layout")
    assert r.status_code == 200
    assert len(r.json()["data"]["panels"]) == 13


def test_resize_panel(client):
    r = client.post("/api/workspace/layout/panels/ops-dashboard/resize", params={"width": 400, "height": 300})
    assert r.status_code == 200
    panel = next(p for p in r.json()["data"]["panels"] if p["panelId"] == "ops-dashboard")
    assert panel["width"] == 400


def test_move_panel(client):
    r = client.post("/api/workspace/layout/panels/ops-dashboard/move", params={"x": 10, "y": 20})
    panel = next(p for p in r.json()["data"]["panels"] if p["panelId"] == "ops-dashboard")
    assert (panel["x"], panel["y"]) == (10, 20)


def test_collapse_panel(client):
    r = client.post("/api/workspace/layout/panels/ops-dashboard/collapse", params={"collapsed": True})
    panel = next(p for p in r.json()["data"]["panels"] if p["panelId"] == "ops-dashboard")
    assert panel["collapsed"] is True


def test_close_and_restore_panel(client):
    r1 = client.post("/api/workspace/layout/panels/ops-dashboard/close")
    assert "ops-dashboard" not in r1.json()["data"]["openPanelIds"]
    r2 = client.post("/api/workspace/layout/panels/ops-dashboard/restore")
    assert "ops-dashboard" in r2.json()["data"]["openPanelIds"]


def test_reset_layout(client):
    client.post("/api/workspace/layout/panels/ops-dashboard/resize", params={"width": 999, "height": 999})
    r = client.post("/api/workspace/layout/reset")
    panel = next(p for p in r.json()["data"]["panels"] if p["panelId"] == "ops-dashboard")
    assert panel["width"] == 290.0


def test_get_agent_panels(client):
    r = client.get("/api/workspace/agents")
    assert r.status_code == 200
    assert len(r.json()["data"]) == 7


def test_get_operations_summary(client):
    r = client.get("/api/workspace/operations")
    assert r.status_code == 200
    assert "engineStatus" in r.json()["data"]


def test_get_notifications(client):
    r = client.get("/api/workspace/notifications")
    assert r.status_code == 200
    assert isinstance(r.json()["data"], list)


def test_pin_unpin_clear_notification(client):
    assert client.post("/api/workspace/notifications/n1/pin").status_code == 200
    assert client.post("/api/workspace/notifications/n1/unpin").status_code == 200
    assert client.post("/api/workspace/notifications/n1/clear").status_code == 200


def test_clear_all_notifications(client):
    r = client.post("/api/workspace/notifications/clear-all")
    assert r.status_code == 200


def test_get_mission_workspace(client):
    r = client.get("/api/workspace/missions")
    assert r.status_code == 200
    assert set(r.json()["data"].keys()) == {"waiting", "active", "completed", "blocked"}


def test_search(client):
    r = client.get("/api/workspace/search", params={"q": "primus"})
    assert r.status_code == 200
    assert any(item["id"] == "primus" for item in r.json()["data"])


def test_search_requires_query(client):
    r = client.get("/api/workspace/search")
    assert r.status_code == 422


def test_search_with_kinds_filter(client):
    r = client.get("/api/workspace/search", params={"q": "ceo-tower", "kinds": "room"})
    assert r.status_code == 200
    assert all(item["kind"] == "room" for item in r.json()["data"])


def test_quick_nav(client):
    r = client.get("/api/workspace/quick-nav", params={"q": "ceo"})
    assert r.status_code == 200


def test_history_record_and_get(client):
    r1 = client.post("/api/workspace/history", params={"kind": "selection"}, json={"roomId": "ceo-tower"})
    assert r1.status_code == 200
    r2 = client.get("/api/workspace/history")
    assert len(r2.json()["data"]) == 1


def test_history_undo_with_nothing_to_undo_is_404(client):
    client.post("/api/workspace/history", params={"kind": "selection"}, json={})
    r = client.post("/api/workspace/history/undo")
    assert r.status_code == 404


def test_history_undo_after_two_entries(client):
    client.post("/api/workspace/history", params={"kind": "a"}, json={})
    client.post("/api/workspace/history", params={"kind": "b"}, json={})
    r = client.post("/api/workspace/history/undo")
    assert r.status_code == 200
    assert r.json()["data"]["kind"] == "a"


def test_get_performance_overlay(client):
    r = client.get("/api/workspace/performance")
    assert r.status_code == 200
    assert r.json()["data"]["fpsTarget"] > 0


def test_workspace_routes_default_to_viewer_role(client):
    """Same documentation pattern as tests/test_world_api.py."""
    from api.app import _AUTH_OPERATOR_ROUTES
    workspace_operator_routes = [
        (method, path) for (method, path) in _AUTH_OPERATOR_ROUTES if path.startswith("/api/workspace")
    ]
    assert workspace_operator_routes == []
