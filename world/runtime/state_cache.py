"""StateCache — holds the most recently built `WorldState` plus enough
bookkeeping (TTL expiry, content hash, hit/miss counters, last rebuild
duration) for `UpdateManager` and `world.runtime.statistics` to make
correct, cheap decisions without re-reading disk on every call.

No polling loop lives here (or anywhere in `world/runtime/` — per this
phase's own instructions). This class only reacts when something else
calls it."""

import time
from dataclasses import dataclass

from world.runtime.models import WorldState


@dataclass
class CacheMetrics:
    """Mutable — intentionally not frozen, since these counters are
    incremented in place as the cache is used. Never exposed as part of
    `WorldState` itself; consumed only by `world.runtime.statistics`."""

    hits: int = 0
    misses: int = 0
    refresh_count: int = 0
    last_rebuild_seconds: float = 0.0
    first_refresh_monotonic: float | None = None
    last_refresh_monotonic: float | None = None

    @property
    def hit_ratio(self) -> float:
        total = self.hits + self.misses
        if total == 0:
            return 0.0
        return self.hits / total

    @property
    def update_frequency_per_second(self) -> float:
        """Refreshes per second across the cache's whole lifetime so far
        (first `store()` to most recent `store()`). `0.0` until at least
        two refreshes have happened, since a rate needs a time span."""
        if (
            self.refresh_count < 2
            or self.first_refresh_monotonic is None
            or self.last_refresh_monotonic is None
        ):
            return 0.0
        span = self.last_refresh_monotonic - self.first_refresh_monotonic
        if span <= 0:
            return 0.0
        return (self.refresh_count - 1) / span


class StateCache:
    """`ttl_seconds=None` means "never expire on time alone" — the cache
    then only ever refreshes when `UpdateManager` detects a content-hash
    change (see `world.runtime.update_manager`)."""

    def __init__(self, ttl_seconds: float | None = None) -> None:
        self._ttl_seconds = ttl_seconds
        self._state: WorldState | None = None
        self._content_hash: str | None = None
        self._stored_at: float | None = None
        self.metrics = CacheMetrics()

    def get(self) -> WorldState | None:
        """Return the cached state, or `None` if there is none or it has
        expired by TTL. Counts as a hit/miss for statistics purposes."""
        if self._state is None:
            self.metrics.misses += 1
            return None
        if self._ttl_seconds is not None and self._stored_at is not None:
            if (time.monotonic() - self._stored_at) > self._ttl_seconds:
                self.metrics.misses += 1
                return None
        self.metrics.hits += 1
        return self._state

    def content_hash(self) -> str | None:
        return self._content_hash

    def store(self, state: WorldState, content_hash: str, rebuild_seconds: float) -> None:
        self._state = state
        self._content_hash = content_hash
        self._stored_at = time.monotonic()
        self.metrics.refresh_count += 1
        self.metrics.last_rebuild_seconds = rebuild_seconds
        now = time.monotonic()
        if self.metrics.first_refresh_monotonic is None:
            self.metrics.first_refresh_monotonic = now
        self.metrics.last_refresh_monotonic = now

    def invalidate(self) -> None:
        """Force the next `get()` to miss, without touching accumulated
        hit/miss/refresh counters (those are cumulative statistics, not
        cache state)."""
        self._state = None
        self._content_hash = None
        self._stored_at = None
