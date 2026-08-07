"""world/workspace/quick_nav.py — Phase W12, Feature 7.

Ctrl+P-style palette: thin wrapper over `search_index.search`, restricted
to the "jump to" kinds this feature names (room/agent/mission/
notification/camera target). "Camera target" reuses `character`/`room`
results directly — a camera target in this codebase is always a room or
a followed character (see `world.interaction.focus_manager`), not a
distinct entity type.
"""

from world.runtime.models import WorldState
from world.workspace.models import SearchResult
from world.workspace.search_index import search

_QUICK_NAV_KINDS = ("room", "character", "mission", "notification")


def quick_nav_entries(state: WorldState, query: str) -> tuple[SearchResult, ...]:
    return search(state, query, kinds=_QUICK_NAV_KINDS)
