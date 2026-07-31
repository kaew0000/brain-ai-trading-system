"""Watcher — abstraction for detecting whether a source path has
changed since it was last checked. Two concrete strategies:
`world.watchers.filesystem_watcher.FilesystemWatcher` (mtime-based)
and `world.watchers.polling_watcher.PollingWatcher` (content-hash
based) — interchangeable, same interface, different tradeoffs
(mtime is cheap but can be unreliable across some sync tools/
filesystems; content-hash is exact but reads the whole file)."""

from abc import ABC, abstractmethod


class Watcher(ABC):
    """Stateful: remembers what it last saw for each path, internally
    keyed by path string. Not thread-safe — one `Watcher` instance
    per caller/thread."""

    @abstractmethod
    def has_changed(self, path: str) -> bool:
        """Return True if `path` looks different than the last time
        this method was called for the same path (or if this is the
        first call for `path` and the path exists). Must not raise if
        `path` doesn't exist — return False in that case (nothing to
        report a change from)."""
        raise NotImplementedError

    @abstractmethod
    def reset(self, path: str) -> None:
        """Forget any previously recorded state for `path`, so the
        next `has_changed(path)` call is treated as the first."""
        raise NotImplementedError
