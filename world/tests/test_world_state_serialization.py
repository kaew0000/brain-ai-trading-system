"""Phase W5: WorldState (and every nested model) must be JSON-serializable
via to_dict(), and every model must be frozen/immutable."""
import json
from dataclasses import FrozenInstanceError

import pytest

from world.runtime.models import AgentState, MissionState, RoomState, WorldState
from world.runtime.state_builder import StateBuilder


def test_empty_world_state_to_dict_is_json_serializable():
    state = WorldState()
    json.dumps(state.to_dict())  # raises if not serializable


def test_real_built_state_to_dict_is_json_serializable():
    state = StateBuilder().build()
    payload = json.dumps(state.to_dict())
    assert len(payload) > 0


def test_world_state_is_frozen():
    state = WorldState()
    with pytest.raises(FrozenInstanceError):
        state.engine_status = "active"  # type: ignore[misc]


def test_room_state_is_frozen():
    room = RoomState(room_id="ceo-tower", name="CEO Office")
    with pytest.raises(FrozenInstanceError):
        room.name = "Something Else"  # type: ignore[misc]


def test_agent_state_is_frozen():
    agent = AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="ceo-tower")
    with pytest.raises(FrozenInstanceError):
        agent.status = "emergency"  # type: ignore[misc]


def test_to_dict_round_trips_room_and_agent_data():
    state = StateBuilder().build()
    payload = state.to_dict()
    assert len(payload["rooms"]) == len(state.rooms)
    assert len(payload["agents"]) == len(state.agents)
    assert payload["rooms"][0]["roomId"] == state.rooms[0].room_id


def test_mission_state_to_dict():
    m = MissionState(mission_id="m1", title="X", district="ceo-tower", status="active")
    d = m.to_dict()
    assert d == {
        "missionId": "m1", "title": "X", "district": "ceo-tower",
        "status": "active", "description": "",
    }
