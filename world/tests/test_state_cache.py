"""Phase W5: StateCache — TTL expiry, hit/miss counting, invalidation."""
import time

from world.runtime.models import WorldState
from world.runtime.state_cache import StateCache


def test_get_on_empty_cache_is_a_miss():
    cache = StateCache()
    assert cache.get() is None
    assert cache.metrics.misses == 1
    assert cache.metrics.hits == 0


def test_store_then_get_is_a_hit():
    cache = StateCache()
    state = WorldState()
    cache.store(state, content_hash="abc", rebuild_seconds=0.01)
    result = cache.get()
    assert result is state
    assert cache.metrics.hits == 1


def test_invalidate_forces_next_get_to_miss():
    cache = StateCache()
    cache.store(WorldState(), content_hash="abc", rebuild_seconds=0.01)
    cache.invalidate()
    assert cache.get() is None


def test_ttl_expiry():
    cache = StateCache(ttl_seconds=0.05)
    cache.store(WorldState(), content_hash="abc", rebuild_seconds=0.01)
    assert cache.get() is not None
    time.sleep(0.1)
    assert cache.get() is None


def test_hit_ratio_computed_correctly():
    cache = StateCache()
    cache.get()  # miss
    cache.store(WorldState(), content_hash="abc", rebuild_seconds=0.01)
    cache.get()  # hit
    cache.get()  # hit
    assert cache.metrics.hit_ratio == 2 / 3


def test_content_hash_round_trips():
    cache = StateCache()
    cache.store(WorldState(), content_hash="deadbeef", rebuild_seconds=0.01)
    assert cache.content_hash() == "deadbeef"


def test_update_frequency_is_zero_before_two_refreshes():
    cache = StateCache()
    assert cache.metrics.update_frequency_per_second == 0.0
    cache.store(WorldState(), content_hash="a", rebuild_seconds=0.01)
    assert cache.metrics.update_frequency_per_second == 0.0


def test_update_frequency_positive_after_two_refreshes():
    cache = StateCache()
    cache.store(WorldState(), content_hash="a", rebuild_seconds=0.01)
    time.sleep(0.02)
    cache.store(WorldState(), content_hash="b", rebuild_seconds=0.01)
    assert cache.metrics.update_frequency_per_second > 0.0
