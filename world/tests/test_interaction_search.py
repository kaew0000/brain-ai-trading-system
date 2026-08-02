"""Phase W9: search."""

from world.interaction.search import search
from world.runtime.models import AgentState, RoomState, WorldState
from world.simulation.models import EventDescriptor


def _fake_world_state():
    return WorldState(
        rooms=(
            RoomState(room_id="risk-fortress", name="Risk Department"),
            RoomState(room_id="ai-council", name="AI Council"),
        ),
        agents=(
            AgentState(agent_id="bastion", agent_ref="BASTION", current_room_id="risk-fortress"),
        ),
    )


def _fake_events():
    return (EventDescriptor(event_id="evt-1", kind="risk_alert", room_id="risk-fortress", message="risk flagged"),)


def test_search_matches_room_by_name():
    results = search("risk", get_world_state=_fake_world_state, get_current_events=_fake_events)
    assert any(r.kind == "room" and r.target_id == "risk-fortress" for r in results)


def test_search_matches_agent_by_ref():
    results = search("bastion", get_world_state=_fake_world_state, get_current_events=_fake_events)
    assert any(r.kind == "character" and r.target_id == "bastion" for r in results)


def test_search_matches_event_by_message():
    results = search("flagged", get_world_state=_fake_world_state, get_current_events=_fake_events)
    assert any(r.kind == "event" and r.target_id == "evt-1" for r in results)


def test_search_is_case_insensitive():
    results = search("RISK", get_world_state=_fake_world_state, get_current_events=_fake_events)
    assert len(results) >= 1


def test_search_empty_query_returns_nothing():
    results = search("   ", get_world_state=_fake_world_state, get_current_events=_fake_events)
    assert results == ()


def test_search_no_match_returns_empty_tuple():
    results = search("zzz-nomatch", get_world_state=_fake_world_state, get_current_events=_fake_events)
    assert results == ()
