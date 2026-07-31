"""FilesystemWatcher — mtime-based `Watcher`. Cheap (a single `stat`
call, no file content read) but can miss changes that don't update
mtime, or false-positive after a touch with no content change."""

import os

from world.watchers.base import Watcher


class FilesystemWatcher(Watcher):
    def __init__(self) -> None:
        self._last_mtime: dict[str, float] = {}

    def has_changed(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        current = os.stat(path).st_mtime
        previous = self._last_mtime.get(path)
        self._last_mtime[path] = current
        return previous is None or current != previous

    def reset(self, path: str) -> None:
        self._last_mtime.pop(path, None)
