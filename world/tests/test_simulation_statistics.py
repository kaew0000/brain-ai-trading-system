"""Phase W7, Part H: simulation statistics."""
from world.simulation.engine import SimulationEngine
from world.simulation.statistics import compute_statistics


def test_statistics_counts_are_internally_consistent():
    engine = SimulationEngine()
    state = engine.step()
    stats = compute_statistics(state, engine.timeline, engine.scheduler)

    assert stats.timeline_length == 1
    assert stats.simulation_fps_target > 0
    assert 0.0 <= stats.idle_percentage <= 100.0
    assert 0.0 <= stats.alert_percentage <= 100.0
    assert stats.movement_count >= 0
    assert stats.meeting_count >= 0
    assert stats.active_characters <= len(state.characters)
    assert stats.active_rooms <= len(state.rooms)


def test_timeline_length_grows_with_steps():
    engine = SimulationEngine()
    engine.step()
    engine.step()
    state = engine.step()
    stats = compute_statistics(state, engine.timeline, engine.scheduler)
    assert stats.timeline_length == 3


def test_to_dict_is_json_serializable():
    import json

    engine = SimulationEngine()
    state = engine.step()
    stats = compute_statistics(state, engine.timeline, engine.scheduler)
    json.dumps(stats.to_dict())
    json.dumps(state.to_dict())
