"""world/workspace/api.py — Phase W12, Feature 10. The only public
surface most callers should use, matching every prior phase's
convention (`world.runtime.api`, `world.simulation.api`,
`world.interaction.api`, `world.frontend.renderer.api`). No direct
renderer access — nothing here imports `world.frontend.renderer`.

Wraps module-level singletons for the three genuinely stateful pieces
(layout, notification pin/clear tracking, navigation history) so
repeated calls share state, same reasoning every prior `api.py` module
gives for its own module-level instance.
"""

from world.runtime import api as runtime_api
from world.runtime.update_manager import UpdateManager
from world.workspace import (
    agent_workspace,
    mission_workspace,
    notification_dock,
    operations_dashboard,
    performance_overlay,
    search_index,
)
from world.workspace import quick_nav as quick_nav_module
from world.workspace.history import NavigationHistory
from world.workspace.layout_manager import LayoutManager
from world.workspace.models import (
    AgentPanelState,
    MissionWorkspaceItem,
    NotificationDockItem,
    OperationsSummary,
    PerformanceOverlayState,
    SearchResult,
    WorkspaceLayout,
)
from world.workspace.notification_dock import NotificationDockStore

_layout_manager = LayoutManager()
_notification_store = NotificationDockStore()
_history = NavigationHistory()


# ── Feature 1: layout ────────────────────────────────────────────────────

def get_layout() -> WorkspaceLayout:
    return _layout_manager.load()


def save_layout(layout: WorkspaceLayout) -> None:
    _layout_manager.save(layout)


def resize_panel(panel_id: str, width: float, height: float) -> WorkspaceLayout:
    layout = _layout_manager.resize_panel(_layout_manager.load(), panel_id, width, height)
    _layout_manager.save(layout)
    return layout


def move_panel(panel_id: str, x: float, y: float) -> WorkspaceLayout:
    layout = _layout_manager.move_panel(_layout_manager.load(), panel_id, x, y)
    _layout_manager.save(layout)
    return layout


def set_panel_collapsed(panel_id: str, collapsed: bool) -> WorkspaceLayout:
    layout = _layout_manager.set_collapsed(_layout_manager.load(), panel_id, collapsed)
    _layout_manager.save(layout)
    return layout


def close_panel(panel_id: str) -> WorkspaceLayout:
    layout = _layout_manager.close_panel(_layout_manager.load(), panel_id)
    _layout_manager.save(layout)
    return layout


def restore_panel(panel_id: str) -> WorkspaceLayout:
    layout = _layout_manager.restore_panel(_layout_manager.load(), panel_id)
    _layout_manager.save(layout)
    return layout


def reset_layout() -> WorkspaceLayout:
    layout = _layout_manager.reset()
    _layout_manager.save(layout)
    return layout


# ── Feature 2: agent panels ──────────────────────────────────────────────

def get_agent_panels() -> tuple[AgentPanelState, ...]:
    return agent_workspace.build_agent_panels(runtime_api.get_world_state())


# ── Feature 3: operations dashboard ──────────────────────────────────────

def get_operations_summary() -> OperationsSummary:
    return operations_dashboard.build_operations_summary(runtime_api.get_world_state())


# ── Feature 4: notification dock ─────────────────────────────────────────

def get_notification_dock(category: str | None = None, unread_only: bool = False) -> tuple[NotificationDockItem, ...]:
    return notification_dock.build_dock_items(_notification_store, category=category, unread_only=unread_only)


def pin_notification(notification_id: str) -> None:
    _notification_store.pin(notification_id)


def unpin_notification(notification_id: str) -> None:
    _notification_store.unpin(notification_id)


def clear_notification(notification_id: str) -> None:
    _notification_store.clear(notification_id)


def clear_all_notifications() -> None:
    _notification_store.clear_all(get_notification_dock())


# ── Feature 5: mission workspace ─────────────────────────────────────────

def get_mission_workspace() -> dict[str, tuple[MissionWorkspaceItem, ...]]:
    items = mission_workspace.build_mission_workspace(runtime_api.get_world_state())
    return mission_workspace.group_by_bucket(items)


# ── Feature 6: search ─────────────────────────────────────────────────────

def search(query: str, kinds: tuple[str, ...] | None = None) -> tuple[SearchResult, ...]:
    return search_index.search(runtime_api.get_world_state(), query, kinds=kinds)


# ── Feature 7: quick navigation ──────────────────────────────────────────

def quick_nav(query: str) -> tuple[SearchResult, ...]:
    return quick_nav_module.quick_nav_entries(runtime_api.get_world_state(), query)


# ── Feature 8: history ────────────────────────────────────────────────────

def record_history(kind: str, payload: dict) -> dict:
    state = runtime_api.get_world_state()
    entry = _history.record(kind, payload, state.captured_at)
    return entry.to_dict()


def undo_navigation() -> dict | None:
    entry = _history.undo()
    return entry.to_dict() if entry else None


def get_history() -> tuple[dict, ...]:
    return tuple(e.to_dict() for e in _history.all_entries())


# ── Feature 9: performance overlay ───────────────────────────────────────

def get_performance_overlay(update_manager: UpdateManager | None = None) -> PerformanceOverlayState:
    return performance_overlay.measure_performance(update_manager)


# ── Test/reset support (matches every prior phase's own convention) ─────

def _reset_for_tests() -> None:  # pragma: no cover
    _notification_store.reset()
    _history.reset()
