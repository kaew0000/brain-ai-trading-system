"""Phase W12: performance_overlay — logical timings, no profiling lib."""
from world.runtime.update_manager import UpdateManager
from world.workspace.performance_overlay import measure_performance


def test_returns_positive_fps_target():
    result = measure_performance()
    assert result.fps_target > 0


def test_simulation_update_seconds_is_a_real_nonnegative_measurement():
    result = measure_performance()
    assert result.simulation_update_seconds >= 0


def test_memory_kb_is_positive():
    result = measure_performance()
    assert result.memory_kb > 0


def test_render_seconds_is_none_no_renderer_runs_here():
    result = measure_performance()
    assert result.render_seconds is None


def test_world_update_seconds_defaults_to_zero_without_an_update_manager():
    result = measure_performance(update_manager=None)
    assert result.world_update_seconds == 0.0


def test_world_update_seconds_reflects_a_real_update_manager():
    manager = UpdateManager()
    manager.get_state()  # force at least one real rebuild
    result = measure_performance(update_manager=manager)
    assert result.world_update_seconds >= 0.0


def test_serializes_to_dict():
    import json
    json.dumps(measure_performance().to_dict())
