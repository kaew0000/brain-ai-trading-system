"""Phase W12: world.workspace.api — Feature 10, the public facade tying
every other feature together. Uses the module-level singletons directly
(matching how every other api.py's own tests exercise it), so a
fixture resets the two purely in-memory ones between tests; layout
persistence writes to the real world/data/runtime/workspace.json, so
tests restore it to the default afterward rather than leaving test
artifacts behind (same discipline used everywhere else data actually
touches disk in this project)."""
import pytest

from world.workspace import api as ws


@pytest.fixture(autouse=True)
def _reset():
    ws._reset_for_tests()
    yield
    ws._reset_for_tests()
    ws.reset_layout()


def test_get_layout_returns_default_panel_count():
    layout = ws.get_layout()
    assert len(layout.panels) == 13


def test_resize_panel_persists_and_reads_back():
    ws.resize_panel("ops-dashboard", 111.0, 222.0)
    layout = ws.get_layout()
    panel = next(p for p in layout.panels if p.panel_id == "ops-dashboard")
    assert (panel.width, panel.height) == (111.0, 222.0)


def test_close_and_restore_panel():
    ws.close_panel("ops-dashboard")
    assert "ops-dashboard" not in ws.get_layout().open_panel_ids
    ws.restore_panel("ops-dashboard")
    assert "ops-dashboard" in ws.get_layout().open_panel_ids


def test_reset_layout_restores_defaults():
    ws.resize_panel("ops-dashboard", 999.0, 999.0)
    ws.reset_layout()
    layout = ws.get_layout()
    panel = next(p for p in layout.panels if p.panel_id == "ops-dashboard")
    assert panel.width == 290.0


def test_get_agent_panels_returns_seven():
    assert len(ws.get_agent_panels()) == 7


def test_get_operations_summary_returns_a_summary():
    summary = ws.get_operations_summary()
    assert summary.engine_status in ("idle", "active", "recovering", "halted")


def test_notification_pin_unpin_clear_roundtrip(monkeypatch):
    from world.interaction import api as interaction_api
    from world.interaction.models import InteractionNotification

    fake = (InteractionNotification(notification_id="n1", category="alert", room_id="risk-fortress",
                                     tick_number=1, message="m"),)
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    ws.pin_notification("n1")
    items = ws.get_notification_dock()
    assert items[0].pinned is True

    ws.unpin_notification("n1")
    items = ws.get_notification_dock()
    assert items[0].pinned is False

    ws.clear_notification("n1")
    assert ws.get_notification_dock() == ()


def test_clear_all_notifications(monkeypatch):
    from world.interaction import api as interaction_api
    from world.interaction.models import InteractionNotification

    fake = (
        InteractionNotification(notification_id="n1", category="alert", room_id="r", tick_number=1, message="a"),
        InteractionNotification(notification_id="n2", category="alert", room_id="r", tick_number=2, message="b"),
    )
    monkeypatch.setattr(interaction_api, "get_notifications", lambda: fake)

    ws.clear_all_notifications()
    assert ws.get_notification_dock() == ()


def test_get_mission_workspace_returns_all_four_buckets():
    grouped = ws.get_mission_workspace()
    assert set(grouped.keys()) == {"waiting", "active", "completed", "blocked"}


def test_search_finds_a_real_character():
    results = ws.search("primus")
    assert any(r.result_id == "primus" for r in results)


def test_quick_nav_finds_a_real_room():
    results = ws.quick_nav("ceo-tower")
    assert any(r.kind == "room" for r in results)


def test_record_and_undo_history():
    entry = ws.record_history("selection", {"roomId": "ceo-tower"})
    assert entry["kind"] == "selection"
    assert len(ws.get_history()) == 1

    ws.record_history("camera", {"roomId": "risk-fortress"})
    prev = ws.undo_navigation()
    assert prev["kind"] == "selection"


def test_get_performance_overlay_returns_positive_fps():
    overlay = ws.get_performance_overlay()
    assert overlay.fps_target > 0
