"""DataSource + Reader base abstractions.

Two orthogonal concerns, kept deliberately separate:

- `DataSource` — HOW to get raw parsed content (a JSON file, a CSV
  file, a SQLite table, a log file, a future event bus). Swapping the
  source format never touches a `Reader` subclass.
- `Reader` — WHAT the raw content means (a journal entry, a telemetry
  point, a portfolio snapshot, a mission, an event) and how to turn it
  into a plain dataclass. Every concrete `Reader` in this package
  (`journal_reader.py`, `telemetry_reader.py`, `portfolio_reader.py`,
  `mission_reader.py`, `event_reader.py`) is constructed with a
  `DataSource` instance — never a hardcoded path.

No `DataSource` implementation here assumes any real file exists.
Every implementation is exercised in tests against synthetic fixture
files, never against a real engine path."""

import csv
import json
import sqlite3
from abc import ABC, abstractmethod
from typing import Any


class DataSource(ABC):
    """Contract for reading raw content from one location, in one
    format. Returns whatever shape is natural for that format — a
    `Reader` subclass is responsible for interpreting it."""

    @abstractmethod
    def load_raw(self) -> Any:
        """Return the raw parsed content. Raises if the source is
        unavailable — callers (see `world.adapter.adapter`) are
        expected to catch and treat a missing/unavailable source as
        'no data yet', not as a fatal error."""
        raise NotImplementedError


class JSONFileSource(DataSource):
    """Reads and `json.load`s a single file. `path` is required at
    construction — never defaulted, per the no-hardcoded-paths
    requirement."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load_raw(self) -> Any:
        with open(self.path) as f:
            return json.load(f)


class CSVFileSource(DataSource):
    """Reads a CSV file and returns a list of `dict` rows (via
    `csv.DictReader` — the first row is treated as the header)."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load_raw(self) -> list[dict[str, str]]:
        with open(self.path, newline="") as f:
            return list(csv.DictReader(f))


class SQLiteSource(DataSource):
    """Reads every row of one table from a SQLite database, returned
    as a list of `dict` rows."""

    def __init__(self, db_path: str, table: str) -> None:
        self.db_path = db_path
        self.table = table

    def load_raw(self) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(f"SELECT * FROM {self.table}")  # noqa
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()


class LogFileSource(DataSource):
    """Reads a plain-text log file and returns a list of raw line
    strings (trailing newline stripped). Parsing structure out of log
    lines is a `Reader` subclass's job, not this class's — logs come
    in too many formats to standardize here."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load_raw(self) -> list[str]:
        with open(self.path) as f:
            return [line.rstrip("\n") for line in f]


class EventBusSource(DataSource):
    """Interface-only placeholder. No event bus exists in this
    project today (per the Phase W4 task's own instructions: 'without
    assuming any one exists today') — this class exists purely so the
    `DataSource` abstraction is already open to one being added later
    without any `Reader` subclass changing."""

    def load_raw(self) -> Any:
        raise NotImplementedError(
            "EventBusSource has no implementation yet - no event bus exists in "
            "this project. Implement a concrete subclass when one does."
        )


class Reader(ABC):
    """Contract for turning one `DataSource`'s raw content into plain
    dataclasses or dictionaries. Every `Reader.read()` implementation
    must be safe to call against a `DataSource` whose underlying file
    doesn't exist yet — see each concrete reader's docstring for its
    documented behavior in that case (typically: let the source's
    exception propagate, so `ReadOnlyIngestionAdapter` — the one place
    that decides 'missing source is fine, treat as no data' — can
    catch it explicitly rather than this layer silently swallowing
    errors)."""

    def __init__(self, source: DataSource) -> None:
        self.source = source

    @abstractmethod
    def read(self) -> Any:
        raise NotImplementedError
