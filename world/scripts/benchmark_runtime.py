"""Phase W5, Part L — performance benchmark.

Runs the World State Provider pipeline for 10, 100, 1,000, and 10,000
sequential updates, each update changing `world.json`'s timestamp (forcing
a real rebuild every time — the worst case for the cache). Measures:

- total wall-clock time and average per-update rebuild time
- peak memory via `tracemalloc`
- cache hit ratio achieved by an interleaved "read without changing
  anything" pass after each batch, to also report the best case

Run directly: `python3 world/scripts/benchmark_runtime.py`
This never touches anything outside a temporary directory it creates and
cleans up itself — it does not write to `world/data/runtime/`.
"""

import json
import shutil
import tempfile
import time
import tracemalloc

from world.runtime.state_builder import StateBuilder
from world.runtime.update_manager import UpdateManager

BATCH_SIZES = (10, 100, 1_000, 10_000)


def _write_world_json(runtime_dir: str, i: int) -> None:
    with open(f"{runtime_dir}/world.json", "w") as f:
        json.dump({
            "engineStatus": "active" if i % 2 == 0 else "idle",
            "version": "0.1.0",
            "timestamp": f"2026-08-01T00:00:{i % 60:02d}Z",
            "activeAgents": ["primus"] if i % 2 == 0 else [],
            "activeDistricts": ["ceo-tower"] if i % 2 == 0 else [],
        }, f)


def run_batch(n: int) -> dict:
    runtime_dir = tempfile.mkdtemp(prefix="w5_benchmark_")
    try:
        manager = UpdateManager(builder=StateBuilder(runtime_dir=runtime_dir),
                                 runtime_dir=runtime_dir)

        tracemalloc.start()
        started = time.perf_counter()
        for i in range(n):
            _write_world_json(runtime_dir, i)
            manager.get_state()
        rebuild_elapsed = time.perf_counter() - started
        _, peak_rebuild = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Second pass: read without changing anything (best case, all hits)
        tracemalloc.start()
        started_cached = time.perf_counter()
        for _ in range(n):
            manager.get_state()
        cached_elapsed = time.perf_counter() - started_cached
        _, peak_cached = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        return {
            "n": n,
            "rebuild_total_seconds": rebuild_elapsed,
            "rebuild_avg_ms": (rebuild_elapsed / n) * 1000,
            "cached_total_seconds": cached_elapsed,
            "cached_avg_ms": (cached_elapsed / n) * 1000,
            "peak_memory_rebuild_kb": peak_rebuild / 1024,
            "peak_memory_cached_kb": peak_cached / 1024,
            "cache_hit_ratio": manager.cache.metrics.hit_ratio,
            "refresh_count": manager.cache.metrics.refresh_count,
        }
    finally:
        shutil.rmtree(runtime_dir, ignore_errors=True)


def main() -> None:
    print(f"{'N':>7} | {'rebuild total (s)':>18} | {'rebuild avg (ms)':>16} | "
          f"{'cached avg (ms)':>15} | {'peak mem rebuild (KB)':>21} | {'hit ratio':>9}")
    print("-" * 100)
    for n in BATCH_SIZES:
        r = run_batch(n)
        print(
            f"{r['n']:>7} | {r['rebuild_total_seconds']:>18.4f} | "
            f"{r['rebuild_avg_ms']:>16.4f} | {r['cached_avg_ms']:>15.4f} | "
            f"{r['peak_memory_rebuild_kb']:>21.1f} | {r['cache_hit_ratio']:>9.3f}"
        )


if __name__ == "__main__":
    main()
