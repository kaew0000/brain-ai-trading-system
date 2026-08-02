"""SceneCache — Phase W8.

Avoids rebuilding a room's `world.frontend.scene.scene.Scene` (and,
above it, a `render_state.RenderFrame`) when nothing about that room
changed between two `WorldState` snapshots. Keyed by
`(room_id, sequence)` — `sequence` is `WorldState.sequence`, which
`world_state_provider.RenderWorldStateProvider` sets from the Phase
W7 simulation tick number, so a cache hit means "this exact tick's
data for this room was already built," not a heuristic guess.

Deliberately a small hand-rolled LRU rather than
`functools.lru_cache`: this needs an explicit `invalidate`/size cap
and a cache built from two positional fields, not a single hashable
key derived from function arguments — `lru_cache` decorates a pure
function, this wraps a stateful get-or-build call the same way
`world.runtime.state_cache`/`world.frontend.asset_loader.asset_registry.AssetRegistry`
already do elsewhere in this codebase.
"""

from collections import OrderedDict
from typing import Callable, TypeVar

from world.frontend.renderer.render_config import SCENE_CACHE_MAX_ENTRIES

T = TypeVar("T")


class SceneCache:
    """Generic LRU cache from `(room_id, sequence)` to a built value
    (a `Scene`, a `RenderFrame`, or anything else a caller wants
    cached per room per tick). Kept generic rather than typed to
    `Scene` specifically since `renderer.py` caches full
    `RenderFrame`s, not bare `Scene`s — one cache implementation
    serves both without duplicating LRU logic.
    """

    def __init__(self, max_entries: int = SCENE_CACHE_MAX_ENTRIES) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self._max_entries = max_entries
        self._entries: "OrderedDict[tuple[str, int], object]" = OrderedDict()
        self.hits = 0
        self.misses = 0

    def get_or_build(self, room_id: str, sequence: int, build: Callable[[], T]) -> T:
        """Return the cached value for `(room_id, sequence)`, building
        and storing it via `build()` on a miss. `build` is only called
        on a miss, so it's safe to pass an expensive closure."""
        key = (room_id, sequence)
        if key in self._entries:
            self.hits += 1
            self._entries.move_to_end(key)
            return self._entries[key]  # type: ignore[return-value]

        self.misses += 1
        value = build()
        self._entries[key] = value
        self._entries.move_to_end(key)
        if len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
        return value

    def invalidate(self, room_id: str | None = None) -> None:
        """Drop cached entries. With no argument, clears everything;
        with `room_id`, drops only that room's entries across every
        cached sequence (e.g. if a room's static layout data changes
        underneath a long-lived cache)."""
        if room_id is None:
            self._entries.clear()
            return
        for key in [k for k in self._entries if k[0] == room_id]:
            del self._entries[key]

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0
