"""Phase W7, Part A: SimulationScheduler."""
from world.simulation.scheduler import DEFAULT_FPS_TARGET, SimulationScheduler


def test_first_call_always_ticks():
    scheduler = SimulationScheduler()
    assert scheduler.should_tick(world_sequence=1) is True


def test_same_sequence_does_not_need_a_tick():
    scheduler = SimulationScheduler()
    scheduler.mark_ticked(1)
    assert scheduler.should_tick(world_sequence=1) is False


def test_changed_sequence_needs_a_tick():
    scheduler = SimulationScheduler()
    scheduler.mark_ticked(1)
    assert scheduler.should_tick(world_sequence=2) is True


def test_force_always_ticks_regardless_of_sequence():
    scheduler = SimulationScheduler()
    scheduler.mark_ticked(1)
    assert scheduler.should_tick(world_sequence=1, force=True) is True


def test_reset_forgets_last_sequence():
    scheduler = SimulationScheduler()
    scheduler.mark_ticked(1)
    scheduler.reset()
    assert scheduler.should_tick(world_sequence=1) is True


def test_default_fps_target_is_a_positive_logical_constant():
    scheduler = SimulationScheduler()
    assert scheduler.fps_target == DEFAULT_FPS_TARGET
    assert scheduler.fps_target > 0
