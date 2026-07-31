"""Phase W4: SnapshotCache hash-comparison tests."""

import json
import os

from world.runtime.cache import SnapshotCache


def test_first_write_happens(tmp_path):
    path = str(tmp_path / "out.json")
    wrote = SnapshotCache().write_if_changed(path, {"a": 1})
    assert wrote is True
    assert os.path.exists(path)


def test_second_identical_write_is_skipped(tmp_path):
    path = str(tmp_path / "out.json")
    cache = SnapshotCache()
    cache.write_if_changed(path, {"a": 1})
    mtime_after_first = os.stat(path).st_mtime_ns

    wrote_again = cache.write_if_changed(path, {"a": 1})
    assert wrote_again is False
    assert os.stat(path).st_mtime_ns == mtime_after_first


def test_key_order_does_not_matter_for_change_detection(tmp_path):
    """Canonical serialization (sort_keys) means {'a':1,'b':2} and
    {'b':2,'a':1} must be treated as identical content."""
    path = str(tmp_path / "out.json")
    cache = SnapshotCache()
    cache.write_if_changed(path, {"a": 1, "b": 2})
    wrote_again = cache.write_if_changed(path, {"b": 2, "a": 1})
    assert wrote_again is False


def test_changed_content_triggers_a_write(tmp_path):
    path = str(tmp_path / "out.json")
    cache = SnapshotCache()
    cache.write_if_changed(path, {"a": 1})
    wrote = cache.write_if_changed(path, {"a": 2})
    assert wrote is True
    assert json.load(open(path))["a"] == 2


def test_creates_parent_directories(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "out.json")
    wrote = SnapshotCache().write_if_changed(path, {"a": 1})
    assert wrote is True
    assert os.path.exists(path)


def test_recovers_correctly_across_separate_cache_instances(tmp_path):
    """Stateless-across-restart guarantee: a brand new SnapshotCache
    instance must still detect 'unchanged' by reading the file, not
    by relying on in-memory history from a previous instance."""
    path = str(tmp_path / "out.json")
    SnapshotCache().write_if_changed(path, {"a": 1})
    wrote = SnapshotCache().write_if_changed(path, {"a": 1})  # fresh instance
    assert wrote is False
