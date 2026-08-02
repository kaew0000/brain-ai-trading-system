"""Phase W7: SimulationEngine — integration across Parts A-F using the
real, merged Phase W1/W2/W6 canon (16 characters, 17 rooms) but a fake
`get_world_state` so tests are deterministic and don't depend on
`world/data/runtime/*.json`'s actual (empty) contents."""
from world.runtime.models import AgentState, EventState, RoomState, WorldState
from world.simulation.engine import SimulationEngine


def _fake_world_state(sequence=1, active_agents=()):
    agents = tuple(
        AgentState(agent_id=aid, agent_ref=aid.upper(), current_room_id="ceo-tower" if aid == "primus" else "risk-fortress",
                   is_active=(aid in active_agents), status="working" if aid in active_agents else "idle")
        for aid in ("primus", "bastion")
    )
    rooms = (
        RoomState(room_id="ceo-tower", name="CEO Office", occupant_agent_ids=("primus",)),
        RoomState(room_id="risk-fortress", name="Risk Department", occupant_agent_ids=("bastion",)),
    )
    return WorldState(sequence=sequence, agents=agents, rooms=rooms)


def test_engine_produces_a_state_for_every_agent_and_room():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    sim_state = engine.step()
    assert {c.agent_id for c in sim_state.characters} == {"primus", "bastion"}
    assert {r.room_id for r in sim_state.rooms} == {"ceo-tower", "risk-fortress"}


def test_engine_reflects_working_status_from_world_state():
    state = _fake_world_state(active_agents=("primus",))
    engine = SimulationEngine(get_world_state=lambda: state)
    sim_state = engine.step()
    primus = next(c for c in sim_state.characters if c.agent_id == "primus")
    bastion = next(c for c in sim_state.characters if c.agent_id == "bastion")
    assert primus.behavior == "working"
    assert bastion.behavior in ("idle", "walking")  # patrol may be mid-step


def test_engine_reacts_to_critical_event_next_tick():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    engine.step()

    critical_state = WorldState(
        sequence=2,
        agents=state.agents,
        rooms=state.rooms,
        events=(EventState(event_id="e1", timestamp="t", event_type="risk_alert",
                            district="ceo-tower", severity="critical"),),
    )
    engine2 = SimulationEngine(get_world_state=lambda: critical_state)
    sim_state = engine2.step()
    primus = next(c for c in sim_state.characters if c.agent_id == "primus")
    assert primus.behavior == "emergency"


def test_tick_number_advances_each_step():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    s1 = engine.step()
    s2 = engine.step()
    s3 = engine.step()
    assert [s1.tick.tick_number, s2.tick.tick_number, s3.tick.tick_number] == [1, 2, 3]


def test_pause_sets_running_false_on_subsequent_states():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    engine.step()
    engine.pause()
    sim_state = engine.step()
    assert sim_state.running is False
    assert engine.is_running is False


def test_resume_sets_running_true_again():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    engine.step()
    engine.pause()
    engine.resume()
    sim_state = engine.step()
    assert sim_state.running is True


def test_reset_restarts_tick_numbering_and_clears_timeline():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    engine.step()
    engine.step()
    engine.reset()
    assert len(engine.timeline) == 0
    sim_state = engine.step()
    assert sim_state.tick.tick_number == 1


def test_timeline_records_every_step():
    state = _fake_world_state()
    engine = SimulationEngine(get_world_state=lambda: state)
    for _ in range(5):
        engine.step()
    assert len(engine.timeline) == 5


def test_engine_works_against_the_real_merged_world_state_provider():
    """No fake — exercises the real Phase W5 `world.runtime.api.
    get_world_state` (16 real characters, 17 real rooms) end to end."""
    engine = SimulationEngine()
    sim_state = engine.step()
    assert len(sim_state.characters) == 16
    assert len(sim_state.rooms) == 17
