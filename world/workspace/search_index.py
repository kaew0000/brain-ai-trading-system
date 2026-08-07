"""world/workspace/search_index.py — Phase W12, Feature 6.

"Index in memory" per this phase's own brief — given the real data
volumes involved (16 characters, 17 rooms, a handful of missions/events/
notifications), that means building the searchable list fresh from
`WorldState` + `world.interaction.api` on every call rather than
maintaining a persisted index structure; there's nothing here large
enough to need one. No database.

`kind="building"` is a single fixed entry representing Brain AI Command
World HQ as a whole — useful for Quick Nav's "zoom out" case — not
derived from any per-building runtime data (there's only one building).
"""

from world.runtime.models import WorldState
from world.workspace.models import SearchResult

_BUILDING_ENTRY = SearchResult(kind="building", result_id="brain-ai-hq", label="Brain AI Command World HQ")


def _character_entries(state: WorldState) -> list[SearchResult]:
    return [
        SearchResult(kind="character", result_id=a.agent_id, label=a.agent_ref, detail=a.current_room_id)
        for a in state.agents
    ]


def _room_entries(state: WorldState) -> list[SearchResult]:
    from world.simulation import api as simulation_api

    entries = []
    for r in state.rooms:
        activity_state = simulation_api.get_room_activity(r.room_id)
        activity = activity_state.activity if activity_state else "quiet"
        entries.append(SearchResult(kind="room", result_id=r.room_id, label=r.room_id, detail=activity))
        entries.append(SearchResult(kind="department", result_id=r.room_id, label=r.room_id, detail=activity))
    return entries


def _mission_entries(state: WorldState) -> list[SearchResult]:
    return [
        SearchResult(kind="mission", result_id=m.mission_id, label=m.title, detail=m.status)
        for m in state.missions
    ]


def _event_entries(state: WorldState) -> list[SearchResult]:
    return [
        SearchResult(kind="event", result_id=e.event_id, label=e.message or e.event_type, detail=e.district)
        for e in state.events
    ]


def _notification_entries() -> list[SearchResult]:
    from world.interaction import api as interaction_api
    return [
        SearchResult(kind="notification", result_id=n.notification_id, label=n.message, detail=n.severity)
        for n in interaction_api.get_notifications()
    ]


def build_search_index(state: WorldState) -> tuple[SearchResult, ...]:
    entries: list[SearchResult] = [_BUILDING_ENTRY]
    entries.extend(_character_entries(state))
    entries.extend(_room_entries(state))
    entries.extend(_mission_entries(state))
    entries.extend(_event_entries(state))
    entries.extend(_notification_entries())
    return tuple(entries)


def search(state: WorldState, query: str, kinds: tuple[str, ...] | None = None) -> tuple[SearchResult, ...]:
    q = query.strip().lower()
    if not q:
        return ()
    results = build_search_index(state)
    if kinds:
        results = tuple(r for r in results if r.kind in kinds)
    return tuple(
        r for r in results
        if q in r.label.lower() or q in r.result_id.lower() or q in r.detail.lower()
    )
