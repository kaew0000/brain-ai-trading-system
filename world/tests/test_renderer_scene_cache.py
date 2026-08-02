"""Phase W8: SceneCache — LRU get-or-build cache."""

import pytest

from world.frontend.renderer.scene_cache import SceneCache


def test_cache_miss_then_hit():
    cache = SceneCache()
    calls = []

    def build():
        calls.append(1)
        return "value-a"

    first = cache.get_or_build("room-a", 1, build)
    second = cache.get_or_build("room-a", 1, build)
    assert first == "value-a"
    assert second == "value-a"
    assert len(calls) == 1  # build only called once
    assert cache.hits == 1
    assert cache.misses == 1


def test_different_sequence_is_a_miss():
    cache = SceneCache()
    cache.get_or_build("room-a", 1, lambda: "v1")
    cache.get_or_build("room-a", 2, lambda: "v2")
    assert cache.misses == 2
    assert cache.hits == 0


def test_different_room_is_a_miss():
    cache = SceneCache()
    cache.get_or_build("room-a", 1, lambda: "v1")
    cache.get_or_build("room-b", 1, lambda: "v2")
    assert cache.misses == 2


def test_invalidate_all_clears_cache():
    cache = SceneCache()
    cache.get_or_build("room-a", 1, lambda: "v1")
    cache.invalidate()
    assert len(cache) == 0
    cache.get_or_build("room-a", 1, lambda: "v1")
    assert cache.misses == 2


def test_invalidate_one_room_leaves_others():
    cache = SceneCache()
    cache.get_or_build("room-a", 1, lambda: "v1")
    cache.get_or_build("room-b", 1, lambda: "v2")
    cache.invalidate("room-a")
    assert len(cache) == 1
    cache.get_or_build("room-b", 1, lambda: "v2")
    assert cache.hits == 1


def test_eviction_at_max_entries():
    cache = SceneCache(max_entries=2)
    cache.get_or_build("room-a", 1, lambda: "v1")
    cache.get_or_build("room-b", 1, lambda: "v2")
    cache.get_or_build("room-c", 1, lambda: "v3")  # evicts room-a (least recently used)
    assert len(cache) == 2
    cache.get_or_build("room-a", 1, lambda: "v1-rebuilt")
    assert cache.misses == 4  # a, b, c, then a again


def test_hit_ratio():
    cache = SceneCache()
    assert cache.hit_ratio == 0.0
    cache.get_or_build("room-a", 1, lambda: "v1")
    cache.get_or_build("room-a", 1, lambda: "v1")
    assert cache.hit_ratio == 0.5


def test_max_entries_must_be_positive():
    with pytest.raises(ValueError):
        SceneCache(max_entries=0)
