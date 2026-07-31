"""Phase W5, Part J (performance) — fast in-suite sanity checks only. The
full 10/100/1,000/10,000-update benchmark (Part L) lives in
`world/scripts/benchmark_runtime.py` since it's a report-generating tool,
not a pass/fail test."""
import json
import time

from world.runtime.state_builder import StateBuilder
from world.runtime.update_manager import UpdateManager


def test_unchanged_runtime_files_never_trigger_a_rebuild(tmp_path):
    (tmp_path / "world.json").write_text(json.dumps({
        "engineStatus": "idle", "version": "0.1.0", "timestamp": "t",
        "activeAgents": [], "activeDistricts": [],
    }))
    manager = UpdateManager(builder=StateBuilder(runtime_dir=str(tmp_path)),
                             runtime_dir=str(tmp_path))

    first = manager.get_state()
    for _ in range(100):
        again = manager.get_state()
        assert again is first  # same object: no rebuild happened

    assert manager.cache.metrics.refresh_count == 1
    assert manager.cache.metrics.hits == 100


def test_changed_runtime_file_triggers_exactly_one_rebuild(tmp_path):
    world_path = tmp_path / "world.json"
    world_path.write_text(json.dumps({
        "engineStatus": "idle", "version": "0.1.0", "timestamp": "t",
        "activeAgents": [], "activeDistricts": [],
    }))
    manager = UpdateManager(builder=StateBuilder(runtime_dir=str(tmp_path)),
                             runtime_dir=str(tmp_path))
    first = manager.get_state()

    world_path.write_text(json.dumps({
        "engineStatus": "active", "version": "0.1.0", "timestamp": "t2",
        "activeAgents": [], "activeDistricts": [],
    }))
    second = manager.get_state()

    assert second is not first
    assert second.engine_status == "active"
    assert manager.cache.metrics.refresh_count == 2


def test_100_sequential_updates_stay_fast(tmp_path):
    """Not a formal benchmark (see Part L script) — just guards against an
    accidental O(n^2) or unbounded-growth regression in the hot path."""
    world_path = tmp_path / "world.json"
    manager = UpdateManager(builder=StateBuilder(runtime_dir=str(tmp_path)),
                             runtime_dir=str(tmp_path))

    started = time.perf_counter()
    for i in range(100):
        world_path.write_text(json.dumps({
            "engineStatus": "idle", "version": "0.1.0", "timestamp": f"t{i}",
            "activeAgents": [], "activeDistricts": [],
        }))
        manager.get_state()
    elapsed = time.perf_counter() - started

    assert manager.cache.metrics.refresh_count == 100
    assert elapsed < 5.0  # generous ceiling; this is a regression guard, not a benchmark
