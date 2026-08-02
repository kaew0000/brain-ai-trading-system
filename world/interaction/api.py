"""world.interaction.api — Phase W9. The one public surface most callers
should use, mirroring `world.runtime.api` (Phase W5) and
`world.simulation.api` (Phase W7)'s shape: wraps one shared set of
manager instances so repeated calls share the same selection/history/
event-bus state, the same way both earlier modules wrap one shared
provider/engine. Construct the individual `world.interaction.*` classes
directly instead if you need an isolated instance (as every test in
`world/tests/` does).

Nothing in this module, or anything it wraps, can mutate the trading
engine, `world.runtime`, or `world.simulation`'s underlying data — the
only two calls with any side effect at all are `pause_simulation`/
`resume_simulation` (via `command_dispatcher`), both of which are the
same read-only-from-the-engine's-perspective `world.simulation.api.
pause`/`resume` Phase W7 already exposed.
"""

from world.interaction.command_dispatcher import CommandDispatcher
from world.interaction.filters import (
    filter_agents_by_state,
    filter_alerts,
    filter_by_room_type,
    filter_meetings,
    filter_rooms_by_department,
    filter_rooms_by_simulation_state,
)
from world.interaction.focus_manager import FocusManager
from world.interaction.hover_manager import HoverManager
from world.interaction.inspector import build_inspector_report
from world.interaction.interaction_events import EventBus
from world.interaction.interaction_history import InteractionHistory
from world.interaction.models import CommandResult, HoverInfo, InspectorReport, Selection
from world.interaction.notification_center import build_notifications, filter_by_category
from world.interaction.search import search
from world.interaction.selection_manager import SelectionManager
from world.interaction.timeline_controller import TimelineController
from world.interaction.tooltip import build_tooltip_text

_history = InteractionHistory()
_events = EventBus()
_focus = FocusManager()
_timeline = TimelineController()
_selection = SelectionManager()
_hover = HoverManager()
_dispatcher = CommandDispatcher(
    focus_manager=_focus, timeline_controller=_timeline, event_bus=_events, history=_history,
)


def select(kind: str, target_id: str) -> Selection:
    result = _selection.select(kind, target_id)
    _history.record_selection(kind, target_id)
    _events.publish("SelectionChanged", result.to_dict())
    return result


def clear_selection() -> None:
    _selection.clear()


def current_selection() -> Selection | None:
    return _selection.current


def hover(kind: str, target_id: str) -> HoverInfo:
    result = _hover.hover(kind, target_id)
    _events.publish("HoverChanged", result.to_dict())
    return result


def tooltip_for(kind: str, target_id: str) -> str:
    return build_tooltip_text(hover(kind, target_id))


def inspect(kind: str, target_id: str) -> InspectorReport:
    return build_inspector_report(kind, target_id)


def dispatch(command: str, **kwargs) -> CommandResult:
    return _dispatcher.dispatch(command, **kwargs)


def get_notifications() -> tuple:
    return build_notifications()


def get_notifications_by_category(category: str) -> tuple:
    return filter_by_category(build_notifications(), category)


def search_world(query: str) -> tuple:
    return search(query)


def get_event_history(event_type: str | None = None) -> tuple:
    return _events.history(event_type)


def get_interaction_history() -> tuple:
    return _history.all()


__all__ = [
    "select", "clear_selection", "current_selection",
    "hover", "tooltip_for", "inspect", "dispatch",
    "get_notifications", "get_notifications_by_category", "search_world",
    "get_event_history", "get_interaction_history",
    "filter_rooms_by_department", "filter_by_room_type", "filter_agents_by_state",
    "filter_rooms_by_simulation_state", "filter_alerts", "filter_meetings",
]
