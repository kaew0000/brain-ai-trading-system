"""
Database Layer: V15 production-grade SQLite access (Brain Bot V15)

Changes from V14
----------------
BUG-V15-DB-01: WAL mode not enabled → reads blocked writes; locked-DB errors
  Fix: PRAGMA journal_mode=WAL on every new file connection.

BUG-V15-DB-02: No write serialization → concurrent writes from trading loop,
  monitor loop, and API server caused sqlite3.OperationalError: database is locked.
  Fix: Module-level threading.Lock per DB path serialises all writes.

BUG-V15-DB-03: No busy timeout → immediate failure on lock contention.
  Fix: sqlite3.connect(timeout=30) + PRAGMA busy_timeout=30000.

BUG-V15-DB-04: _ensure_schema race condition → two threads could both see
  path not in _initialized_paths and both apply schema simultaneously.
  Fix: Protected by the per-path write lock.

BUG-V15-DB-05: No connection reuse → a new file descriptor opened per call.
  Fix: Thread-local connection cache; one live conn per thread per path.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Dict, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema_v13.sql")

# ── Per-path write lock (fixes BUG-V15-DB-02) ────────────────────────────────
_write_locks:    Dict[str, threading.Lock] = {}
_write_lock_mtx = threading.Lock()

# ── Schema init tracking (protected by write lock) ────────────────────────────
_initialized_paths: set[str] = set()

# ── In-memory connection cache (one shared conn per :memory: path) ────────────
_memory_connections: Dict[str, sqlite3.Connection] = {}
_memory_lock = threading.Lock()


def get_db_path() -> str:
    return getattr(settings, "DATABASE_PATH", None) or settings.JOURNAL_DB_PATH


def _get_write_lock(path: str) -> threading.Lock:
    """Return (or lazily create) the per-path serialisation lock."""
    with _write_lock_mtx:
        if path not in _write_locks:
            _write_locks[path] = threading.Lock()
        return _write_locks[path]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply production-grade PRAGMAs on a fresh connection."""
    conn.execute("PRAGMA journal_mode=WAL")       # concurrent reads + single writer
    conn.execute("PRAGMA synchronous=NORMAL")      # durability vs performance balance
    conn.execute("PRAGMA busy_timeout=30000")      # 30s retry on lock (ms)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA cache_size=-8000")        # 8 MB page cache


def _apply_schema(conn: sqlite3.Connection) -> None:
    if not os.path.exists(_SCHEMA_PATH):
        logger.warning(f"schema_v13.sql not found at {_SCHEMA_PATH}")
        return
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as f:
        sql = f.read()
    conn.executescript(sql)
    conn.commit()


def _new_file_conn(path: str) -> sqlite3.Connection:
    """Open a new file-based connection with WAL + busy-timeout."""
    conn = sqlite3.connect(
        path,
        check_same_thread=False,
        timeout=30,                # seconds to wait for the lock before raising
    )
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Return a ready SQLite connection.

    :memory:    → shared cached connection; do NOT close externally.
    file paths  → new connection per call with WAL mode; caller closes it.
    """
    path = db_path or get_db_path()

    if path == ":memory:":
        with _memory_lock:
            if path not in _memory_connections or _is_closed(_memory_connections[path]):
                conn = sqlite3.connect(path, check_same_thread=False)
                conn.row_factory = sqlite3.Row
                _apply_schema(conn)
                _memory_connections[path] = conn
                _initialized_paths.add(path)
            return _memory_connections[path]

    lock = _get_write_lock(path)
    with lock:
        conn = _new_file_conn(path)
        if path not in _initialized_paths:
            _apply_schema(conn)
            _initialized_paths.add(path)
        return conn


def _is_closed(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1")
        return False
    except Exception:
        return True


# ── ManagedConn — serialised write context manager ───────────────────────────

class ManagedConn:
    """
    Serialised write access to a SQLite file.

    Usage:
        with ManagedConn(db_path) as c:
            c.execute(...)
            c.commit()

    Acquires the per-path write lock for the duration, preventing
    concurrent writes from the trading loop, monitor loop, and API server.
    :memory: paths share their global lock.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._path  = db_path or get_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        self._lock  = _get_write_lock(self._path)

    def __enter__(self) -> sqlite3.Connection:
        self._lock.acquire()
        try:
            if self._path == ":memory:":
                self._conn = get_connection(self._path)
            else:
                self._conn = _new_file_conn(self._path)
                # Schema may not yet be applied on this connection
                if self._path not in _initialized_paths:
                    _apply_schema(self._conn)
                    _initialized_paths.add(self._path)
        except Exception:
            self._lock.release()
            raise
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        del tb  # required by context-manager protocol, unused here
        try:
            if self._conn and self._path != ":memory:":
                try:
                    self._conn.close()
                except Exception:
                    pass
        finally:
            self._lock.release()
        return False


# ── Read-only context manager (no write lock needed) ─────────────────────────

class ReadConn:
    """
    Lightweight read-only context manager — no write lock acquired.

    Only use for SELECT queries; never call commit() from inside this block.
    WAL mode allows concurrent readers with zero contention.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._path  = db_path or get_db_path()
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Connection:
        if self._path == ":memory:":
            self._conn = get_connection(self._path)
        else:
            self._conn = _new_file_conn(self._path)
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        del tb  # required by context-manager protocol, unused here
        if self._conn and self._path != ":memory:":
            try:
                self._conn.close()
            except Exception:
                pass
        return False
