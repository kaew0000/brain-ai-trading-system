"""PollingWatcher — content-hash-based `Watcher`. More expensive
(reads the whole file every check) but exact: only reports a change
when the bytes actually differ, immune to mtime-only touches."""

import hashlib
import os

from world.watchers.base import Watcher


class PollingWatcher(Watcher):
    def __init__(self) -> None:
        self._last_hash: dict[str, str] = {}

    def has_changed(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "rb") as f:
            current = hashlib.sha256(f.read()).hexdigest()
        previous = self._last_hash.get(path)
        self._last_hash[path] = current
        return previous is None or current != previous

    def reset(self, path: str) -> None:
        self._last_hash.pop(path, None)
