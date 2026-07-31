"""RuntimeManager — the only class that decides *when* to write and
*where*. Composition, not inheritance: it owns a
`ReadOnlyIngestionAdapter`, a `SnapshotBuilder`, and a `SnapshotCache`,
and its `run_once()` is the entire Phase W4 pipeline in one call:
capture -> build -> write-if-changed, once per output file.

Watchers (`world.watchers.*`) are deliberately NOT owned by this
class. Whether to call `run_once()` at all (e.g. only when a
`Watcher.has_changed(source_path)` says something changed) is a
decision for whatever schedules this class - keeping 'do I need to
run' separate from 'what happens when I do run'."""

import os

from world.adapter.adapter import ReadOnlyIngestionAdapter
from world.adapter.snapshot_builder import SnapshotBuilder
from world.runtime.cache import SnapshotCache

DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "runtime"
)


class RuntimeManager:
    def __init__(
        self,
        adapter: ReadOnlyIngestionAdapter,
        builder: SnapshotBuilder | None = None,
        cache: SnapshotCache | None = None,
        output_dir: str = DEFAULT_OUTPUT_DIR,
    ) -> None:
        self._adapter = adapter
        self._builder = builder or SnapshotBuilder()
        self._cache = cache or SnapshotCache()
        self._output_dir = output_dir

    def run_once(self) -> dict[str, bool]:
        """Capture one snapshot, build all six outputs, and write
        each one only if changed. Returns {filename: was_written}."""
        snapshot = self._adapter.capture_snapshot()
        outputs = self._builder.build_all(snapshot)

        written = {}
        for name, data in outputs.items():
            filename = f"{name}.json"
            path = os.path.join(self._output_dir, filename)
            written[filename] = self._cache.write_if_changed(path, data)
        return written
