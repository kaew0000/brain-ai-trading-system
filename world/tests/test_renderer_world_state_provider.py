"""Phase W8: RenderWorldStateProvider — the concrete implementation of
the Phase W3 `WorldStateProvider` ABC, projecting Phase W5 runtime
state + Phase W7 simulation state down to the Phase W3 renderer-facing
`WorldState` shape.
"""

import inspect

from world.frontend.interfaces.world_state import WorldStateProvider
from world.frontend.renderer.world_state import WorldState as FrontendWorldState
from world.frontend.renderer.world_state_provider import RenderWorldStateProvider
from world.runtime.models import AgentState, RoomState, WorldState as RuntimeWorldState
from world.simulation.models import (
    CharacterActivity,
    EventDescriptor,
    Position,
    RoomActivityState,
    SimulationState,
    SimulationTick,
)


def _fake_runtime_state():
    return RuntimeWorldState(
        rooms=(
            RoomState(room_id="risk-fortress", name="Risk Department", is_active=True,
                      active_mission_ids=("m1",)),
            RoomState(room_id="lobby", name="Lobby", is_active=False),
        ),
        agents=(
            AgentState(agent_id="bastion", agent_ref="BASTION", current_room_id="risk-fortress", status="working"),
        ),
    )


def _fake_simulation_state():
    return SimulationState(
        tick=SimulationTick(tick_number=42, simulated_seconds=42.0, world_sequence=42),
        running=True,
        characters=(
            CharacterActivity(
                agent_id="bastion", agent_ref="BASTION", behavior="meeting",
                room_id="risk-fortress", position=Position(x=0.7, y=0.5),
            ),
        ),
        rooms=(
            RoomActivityState(room_id="risk-fortress", activity="meeting", occupant_count=2),
            RoomActivityState(room_id="lobby", activity="quiet", occupant_count=0),
        ),
        events=(
            EventDescriptor(event_id="evt-1", kind="risk_alert", room_id="risk-fortress",
                             agent_id="bastion", message="risk flagged"),
        ),
    )


def test_render_world_state_provider_is_a_real_world_state_provider():
    assert inspect.isabstract(WorldStateProvider)
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    assert isinstance(provider, WorldStateProvider)


def test_get_current_state_returns_frontend_world_state():
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    state = provider.get_current_state()
    assert isinstance(state, FrontendWorldState)


def test_district_status_merges_runtime_identity_with_simulation_activity():
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    state = provider.get_current_state()
    risk = state.district_status["risk-fortress"]
    assert risk["name"] == "Risk Department"
    assert risk["activity"] == "meeting"
    assert risk["occupantCount"] == 2
    assert risk["isActive"] is True
    assert risk["activeMissionIds"] == ["m1"]


def test_character_states_carries_raw_seven_state_behavior_unmapped():
    """Documented deviation: `character_states` holds the raw Phase W7
    behaviour label (here `"meeting"`, which is not one of the five
    `STANDARD_ANIMATION_STATES`) — mapping to a real animation state is
    `sprite_mapper`'s job, one layer down, not this provider's."""
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    state = provider.get_current_state()
    assert state.character_states["bastion"] == "meeting"


def test_character_positions_shape():
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    state = provider.get_current_state()
    pos = state.character_positions["bastion"]
    assert pos == {"room_id": "risk-fortress", "x": 0.7, "y": 0.5}


def test_sequence_is_the_simulation_tick_number():
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    state = provider.get_current_state()
    assert state.sequence == 42


def test_recent_events_are_serialized_event_descriptors():
    provider = RenderWorldStateProvider(
        get_runtime_state=_fake_runtime_state, get_simulation_state=_fake_simulation_state,
    )
    state = provider.get_current_state()
    assert len(state.recent_events) == 1
    assert state.recent_events[0]["eventId"] == "evt-1"
    assert state.recent_events[0]["roomId"] == "risk-fortress"


def test_default_construction_uses_real_live_apis_and_does_not_raise():
    """No fakes injected — exercises the real
    `world.runtime.api.get_world_state` /
    `world.simulation.api.get_simulation_state` read path end to
    end."""
    provider = RenderWorldStateProvider()
    state = provider.get_current_state()
    assert isinstance(state, FrontendWorldState)
    assert len(state.district_status) == 17
