"""EngineSnapshot — the in-memory aggregate of every reader's output,
timestamped once as a whole. `SnapshotBuilder`
(`world.adapter.snapshot_builder`) turns this into the six stable JSON
shapes; nothing else in this repo should consume the raw reader output
lists directly."""

from dataclasses import dataclass, field

from world.readers.event_reader import Event
from world.readers.journal_reader import JournalEntry
from world.readers.mission_reader import Mission
from world.readers.order_reader import OrderTimelineEntry, ReconciliationSnapshot
from world.readers.portfolio_reader import PortfolioPosition, PortfolioSummary
from world.readers.telemetry_reader import TelemetryPoint


@dataclass
class EngineSnapshot:
    captured_at: str  # ISO-8601 timestamp string, set by ReadOnlyIngestionAdapter
    journal_entries: list[JournalEntry] = field(default_factory=list)
    telemetry_points: list[TelemetryPoint] = field(default_factory=list)
    portfolio_positions: list[PortfolioPosition] = field(default_factory=list)
    missions: list[Mission] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    #: Phase W13-1 — read-only composite order-timeline rows, sourced
    #: from execution.order_timeline.OrderTimeline via
    #: telemetry/world_export.py only (see world/readers/order_reader.py).
    order_states: list[OrderTimelineEntry] = field(default_factory=list)
    #: Phase W11 — portfolio-wide read-only figures (PnL/drawdown/win
    #: rate), or None if the portfolio reader didn't supply any (either
    #: it's a Phase W4-shaped source, or summary parsing found nothing).
    portfolio_summary: PortfolioSummary | None = None
    #: Phase W13-1 — reconciliation-wide read-only figures, or None if
    #: the order reader's payload had no reconciliation object this
    #: capture (see world/readers/order_reader.py).
    reconciliation: ReconciliationSnapshot | None = None

    #: which of the readers actually returned data this capture (vs.
    #: their source being unavailable) - lets SnapshotBuilder and
    #: callers distinguish "genuinely empty" from "source not wired
    #: yet", and lets tests/docs be honest about partial captures.
    sources_available: dict[str, bool] = field(default_factory=dict)
