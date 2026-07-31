"""UpdateManager — the one place that decides whether `StateBuilder.build()`
needs to run again. Hashes the six Phase W4 runtime JSON files (the only
part of the world that changes without a code deploy) and only rebuilds
when that hash differs from what's cached — matching the same
hash-before-write discipline `world.runtime.cache.SnapshotCache` already
uses for W4's own writes, applied here to reads instead.

No polling loop: `get_state()` only checks/rebuilds when called."""

import hashlib
import os
import time

from world.runtime.state_builder import DEFAULT_RUNTIME_DIR, StateBuilder
from world.runtime.state_cache import StateCache

_RUNTIME_FILENAMES = (
    "world.json",
    "events.json",
    "missions.json",
    "portfolio.json",
    "telemetry.json",
    "notifications.json",
)


def _hash_runtime_dir(runtime_dir: str) -> str:
    """Hash the concatenation of all six runtime files' raw bytes (missing
    files contribute a fixed sentinel rather than being skipped, so
    "file appeared" / "file disappeared" both count as a change)."""
    hasher = hashlib.sha256()
    for filename in _RUNTIME_FILENAMES:
        path = os.path.join(runtime_dir, filename)
        if os.path.isfile(path):
            with open(path, "rb") as f:
                hasher.update(f.read())
        else:
            hasher.update(b"__missing__")
        hasher.update(b"\x00")
    return hasher.hexdigest()


class UpdateManager:
    def __init__(
        self,
        builder: StateBuilder | None = None,
        cache: StateCache | None = None,
        runtime_dir: str = DEFAULT_RUNTIME_DIR,
    ) -> None:
        self._builder = builder or StateBuilder(runtime_dir=runtime_dir)
        self._cache = cache or StateCache()
        self._runtime_dir = runtime_dir
        self._sequence = 0

    def has_changed(self) -> bool:
        return _hash_runtime_dir(self._runtime_dir) != self._cache.content_hash()

    def get_state(self, force: bool = False):
        """Return the current `WorldState`, rebuilding only if `force` is
        set or the runtime files' content hash has changed since the last
        build. Returns the same cached object (not a copy) when no rebuild
        is needed, to avoid unnecessary allocations."""
        current_hash = _hash_runtime_dir(self._runtime_dir)
        cached = self._cache.get()

        if not force and cached is not None and current_hash == self._cache.content_hash():
            return cached

        started = time.perf_counter()
        self._sequence += 1
        state = self._builder.build(sequence=self._sequence)
        elapsed = time.perf_counter() - started

        self._cache.store(state, current_hash, elapsed)
        return state

    def invalidate(self) -> None:
        self._cache.invalidate()

    @property
    def cache(self) -> StateCache:
        return self._cache
