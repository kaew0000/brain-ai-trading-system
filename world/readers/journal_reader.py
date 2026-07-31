"""JournalReader — turns raw journal-shaped rows/records into
`JournalEntry` dataclasses. Source-agnostic: works against any
`DataSource` (JSON/CSV/SQLite/log) that yields dict-like rows with the
expected keys.

Read-only, generic. Does not import from or know the path of the
trading engine's real `journal/` module."""

from dataclasses import dataclass

from world.readers.base import Reader


@dataclass
class JournalEntry:
    entry_id: str
    timestamp: str
    symbol: str
    action: str
    note: str = ""


class JournalReader(Reader):
    """Expects `self.source.load_raw()` to return a list of dict-like
    rows, each with at least `id`/`timestamp`/`symbol`/`action` keys
    (missing optional `note` defaults to empty string). Rows missing a
    required key are skipped, not raised — a single malformed row must
    never break the whole snapshot."""

    def read(self) -> list[JournalEntry]:
        raw = self.source.load_raw()
        entries = []
        for row in raw:
            try:
                entries.append(
                    JournalEntry(
                        entry_id=str(row["id"]),
                        timestamp=str(row["timestamp"]),
                        symbol=str(row["symbol"]),
                        action=str(row["action"]),
                        note=str(row.get("note", "")),
                    )
                )
            except (KeyError, TypeError):
                continue
        return entries
