"""EngineSnapshot — the in-memory aggregate of every reader's output,
timestamped once as a whole. `SnapshotBuilder`
(`world.adapter.snapshot_builder`) turns this into the six stable JSON
shapes; nothing else in this repo should consume the raw reader output
lists directly."""

from dataclasses import dataclass, field

from world.readers.event_reader import Event
from world.readers.journal_reader import JournalEntry
from world.readers.mission_reader import Mission
from world.readers.portfolio_reader import PortfolioPosition
from world.readers.telemetry_reader import TelemetryPoint


@dataclass
class EngineSnapshot:
    captured_at: str  # ISO-8601 timestamp string, set by ReadOnlyIngestionAdapter
    journal_entries: list[JournalEntry] = field(default_factory=list)
    telemetry_points: list[TelemetryPoint] = field(default_factory=list)
    portfolio_positions: list[PortfolioPosition] = field(default_factory=list)
    missions: list[Mission] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

    #: which of the five readers actually returned data this capture
    #: (vs. their source being unavailable) - lets SnapshotBuilder and
    #: callers distinguish "genuinely empty" from "source not wired
    #: yet", and lets tests/docs be honest about partial captures.
    sources_available: dict[str, bool] = field(default_factory=dict)
