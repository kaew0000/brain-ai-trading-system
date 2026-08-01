"""Phase W7, Part K — performance benchmark.

The real office only has 16 characters, so "10/50/100/500 simulated
agents" (as this phase's own spec names) means synthetic `AgentState`/
`RoomState` fixtures at those scales, not the real `WorldState` — the same
approach `world/scripts/benchmark_runtime.py` (Phase W5) took for its
10/100/1,000/10,000-update benchmark against synthetic runtime files.

Measures, per scale: total step() time, average per-agent transition
latency, and peak memory via `tracemalloc`. Never touches
`world/data/runtime/` or any other real file.

Run directly: `PYTHONPATH=. python3 world/scripts/benchmark_simulation.py`
"""

import time
import tracemalloc

from world.runtime.models import AgentState, RoomState, WorldState
from world.simulation.engine import SimulationEngine

AGENT_COUNTS = (10, 50, 100, 500)

_REAL_ROOM_IDS = (
    "ai-council", "ceo-tower", "command-hall", "data-center", "execution-forge",
    "journal-library", "market-intelligence-center", "portfolio-garden",
    "recovery-center", "research-district", "risk-fortress", "simulation-lab",
    "training-arena", "world-gateway",
)


def _synthetic_world_state(n_agents: int, sequence: int) -> WorldState:
    agents = tuple(
        AgentState(
            agent_id=f"synthetic-{i}",
            agent_ref=f"SYNTH{i}",
            current_room_id=_REAL_ROOM_IDS[i % len(_REAL_ROOM_IDS)],
            is_active=(i % 3 == 0),
            status="working" if i % 3 == 0 else "idle",
        )
        for i in range(n_agents)
    )
    rooms = tuple(
        RoomState(
            room_id=room_id,
            name=room_id,
            occupant_agent_ids=tuple(
                a.agent_id for a in agents if a.current_room_id == room_id
            ),
        )
        for room_id in _REAL_ROOM_IDS
    )
    return WorldState(sequence=sequence, agents=agents, rooms=rooms)


def run_benchmark(n_agents: int, n_steps: int = 20) -> dict:
    # Real characters have spatial_placement.json entries; synthetic ones
    # don't, so the engine falls back to (0, 0) — exercised deliberately,
    # since that fallback path must also stay fast at scale.
    sequence = [0]

    def get_state():
        sequence[0] += 1
        return _synthetic_world_state(n_agents, sequence[0])

    engine = SimulationEngine(get_world_state=get_state, history_window=n_steps)

    tracemalloc.start()
    started = time.perf_counter()
    for _ in range(n_steps):
        engine.step()
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return {
        "n_agents": n_agents,
        "n_steps": n_steps,
        "total_seconds": elapsed,
        "avg_step_ms": (elapsed / n_steps) * 1000,
        "avg_per_agent_us": (elapsed / n_steps / n_agents) * 1_000_000,
        "peak_memory_kb": peak / 1024,
    }


def main() -> None:
    print(f"{'agents':>7} | {'total (s)':>10} | {'avg step (ms)':>14} | "
          f"{'avg/agent (us)':>15} | {'peak mem (KB)':>14}")
    print("-" * 75)
    for n in AGENT_COUNTS:
        r = run_benchmark(n)
        print(
            f"{r['n_agents']:>7} | {r['total_seconds']:>10.4f} | "
            f"{r['avg_step_ms']:>14.4f} | {r['avg_per_agent_us']:>15.2f} | "
            f"{r['peak_memory_kb']:>14.1f}"
        )


if __name__ == "__main__":
    main()
