"""world/workspace/performance_overlay.py — Phase W12, Feature 9.

Logical timings only — "no profiling library" per this phase's own
brief. Reuses each layer's own already-tracked timing/memory
bookkeeping rather than adding new instrumentation:

- `world_update_seconds` <- `world.runtime.state_cache.CacheMetrics.
  last_rebuild_seconds` (Phase W5)
- `simulation_update_seconds` <- the Phase W7 `SimulationEngine`'s own
  cache-less per-tick cost isn't separately tracked, so this is measured
  here via `time.perf_counter()` around the one call this function
  itself makes to `world.simulation.api.get_simulation_state()` — a
  real wall-clock measurement of that specific call, not a fabricated
  number, but also not a profiler attached to the whole process.
- `fps_target` <- `SimulationScheduler.fps_target` (Phase W7), a design
  constant, not a measured frame rate — nothing in this Python backend
  renders frames, so there is no real FPS to measure server-side; the
  frontend's own `requestAnimationFrame` loop is the only place an
  actual FPS could be measured, and does so itself (see
  `world/docs/OPERATIONS_WORKSPACE.md` §9).
- `memory_kb` <- `tracemalloc`, already used by Phase W5's and W7's own
  benchmark scripts.
- `render_seconds` is `None` from this backend module — no renderer
  code runs in Python at request time (Phase W8's `SceneGraphRenderer`
  runs once per `/api/world/rooms/{id}/frame` call, timed at that call
  site instead, not duplicated here).
"""

import time
import tracemalloc

from world.runtime.update_manager import UpdateManager
from world.simulation import api as simulation_api
from world.simulation.scheduler import DEFAULT_FPS_TARGET
from world.workspace.models import PerformanceOverlayState


def measure_performance(update_manager: UpdateManager | None = None) -> PerformanceOverlayState:
    tracemalloc.start()
    started = time.perf_counter()
    simulation_api.get_simulation_state()
    simulation_elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    world_update_seconds = 0.0
    if update_manager is not None:
        world_update_seconds = update_manager.cache.metrics.last_rebuild_seconds

    return PerformanceOverlayState(
        fps_target=DEFAULT_FPS_TARGET,
        world_update_seconds=world_update_seconds,
        simulation_update_seconds=simulation_elapsed,
        render_seconds=None,
        memory_kb=peak / 1024,
        cpu_percent=None,
    )
