"""Phase W12: LayoutManager — persistence, resize/move/collapse/dock/
close/restore/reset. Uses tmp_path so tests never touch the real
world/data/runtime/workspace.json."""
from world.workspace.layout_manager import DEFAULT_PANEL_IDS, LayoutManager, default_layout


def _manager(tmp_path):
    return LayoutManager(path=str(tmp_path / "workspace.json"))


def test_load_with_no_file_returns_default_layout(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.load()
    assert len(layout.panels) == len(DEFAULT_PANEL_IDS)
    assert set(layout.open_panel_ids) == set(DEFAULT_PANEL_IDS)


def test_save_then_load_round_trips(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.load()
    manager.save(layout)
    reloaded = manager.load()
    assert reloaded.to_dict() == layout.to_dict()


def test_load_with_corrupt_file_falls_back_to_default(tmp_path):
    path = tmp_path / "workspace.json"
    path.write_text("{not valid json")
    manager = LayoutManager(path=str(path))
    layout = manager.load()
    assert len(layout.panels) == len(DEFAULT_PANEL_IDS)


def test_resize_panel_persists(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.resize_panel(manager.load(), "ops-dashboard", 500.0, 400.0)
    manager.save(layout)
    reloaded = manager.load()
    panel = next(p for p in reloaded.panels if p.panel_id == "ops-dashboard")
    assert panel.width == 500.0
    assert panel.height == 400.0


def test_move_panel_persists(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.move_panel(manager.load(), "ops-dashboard", 42.0, 99.0)
    panel = next(p for p in layout.panels if p.panel_id == "ops-dashboard")
    assert (panel.x, panel.y) == (42.0, 99.0)


def test_set_collapsed(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.set_collapsed(manager.load(), "ops-dashboard", True)
    panel = next(p for p in layout.panels if p.panel_id == "ops-dashboard")
    assert panel.collapsed is True


def test_set_docked(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.set_docked(manager.load(), "ops-dashboard", False)
    panel = next(p for p in layout.panels if p.panel_id == "ops-dashboard")
    assert panel.docked is False


def test_close_panel_removes_from_open_ids_but_keeps_layout(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.close_panel(manager.load(), "ops-dashboard")
    assert "ops-dashboard" not in layout.open_panel_ids
    assert any(p.panel_id == "ops-dashboard" for p in layout.panels)


def test_restore_panel_reopens_a_closed_panel(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.close_panel(manager.load(), "ops-dashboard")
    layout = manager.restore_panel(layout, "ops-dashboard")
    assert "ops-dashboard" in layout.open_panel_ids


def test_restore_panel_is_idempotent_when_already_open(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.load()
    before = layout.open_panel_ids
    layout = manager.restore_panel(layout, "ops-dashboard")
    assert layout.open_panel_ids == before


def test_reset_returns_a_fresh_default_layout(tmp_path):
    manager = _manager(tmp_path)
    layout = manager.resize_panel(manager.load(), "ops-dashboard", 999.0, 999.0)
    manager.save(layout)
    reset_layout = manager.reset()
    assert reset_layout.to_dict() == default_layout().to_dict()


def test_panel_layout_round_trips_through_dict():
    layout = default_layout()
    d = layout.to_dict()
    from world.workspace.models import WorkspaceLayout
    rebuilt = WorkspaceLayout.from_dict(d)
    assert rebuilt.to_dict() == d
