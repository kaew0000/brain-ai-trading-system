"""Phase W4: Watcher contract tests — both concrete strategies must
satisfy the same behavioral contract."""

import time

import pytest

from world.watchers.base import Watcher
from world.watchers.filesystem_watcher import FilesystemWatcher
from world.watchers.polling_watcher import PollingWatcher

WATCHER_CLASSES = [FilesystemWatcher, PollingWatcher]


def test_watcher_is_abstract():
    with pytest.raises(TypeError):
        Watcher()


@pytest.mark.parametrize("watcher_cls", WATCHER_CLASSES, ids=[c.__name__ for c in WATCHER_CLASSES])
def test_missing_file_reports_no_change(watcher_cls, tmp_path):
    watcher = watcher_cls()
    missing = str(tmp_path / "does-not-exist.txt")
    assert watcher.has_changed(missing) is False


@pytest.mark.parametrize("watcher_cls", WATCHER_CLASSES, ids=[c.__name__ for c in WATCHER_CLASSES])
def test_first_check_on_existing_file_is_a_change(watcher_cls, tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("v1")
    watcher = watcher_cls()
    assert watcher.has_changed(str(p)) is True


@pytest.mark.parametrize("watcher_cls", WATCHER_CLASSES, ids=[c.__name__ for c in WATCHER_CLASSES])
def test_unchanged_file_is_not_a_change_on_second_check(watcher_cls, tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("v1")
    watcher = watcher_cls()
    watcher.has_changed(str(p))  # first call - establishes baseline
    assert watcher.has_changed(str(p)) is False


@pytest.mark.parametrize("watcher_cls", WATCHER_CLASSES, ids=[c.__name__ for c in WATCHER_CLASSES])
def test_content_change_is_detected(watcher_cls, tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("v1")
    watcher = watcher_cls()
    watcher.has_changed(str(p))
    time.sleep(0.01)  # ensure mtime resolution can register a difference
    p.write_text("v2 - different length so content hash and mtime both change")
    assert watcher.has_changed(str(p)) is True


@pytest.mark.parametrize("watcher_cls", WATCHER_CLASSES, ids=[c.__name__ for c in WATCHER_CLASSES])
def test_reset_makes_next_check_a_first_check_again(watcher_cls, tmp_path):
    p = tmp_path / "f.txt"
    p.write_text("v1")
    watcher = watcher_cls()
    watcher.has_changed(str(p))
    assert watcher.has_changed(str(p)) is False
    watcher.reset(str(p))
    assert watcher.has_changed(str(p)) is True


def test_polling_watcher_ignores_touch_without_content_change(tmp_path):
    """The defining difference from FilesystemWatcher: a mtime-only
    touch with identical bytes must NOT register as a change."""
    p = tmp_path / "f.txt"
    p.write_text("same content")
    watcher = PollingWatcher()
    watcher.has_changed(str(p))
    time.sleep(0.01)
    p.write_text("same content")  # rewritten, but identical bytes
    assert watcher.has_changed(str(p)) is False
