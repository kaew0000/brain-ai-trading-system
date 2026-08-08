"""ReadOnlyIngestionAdapter — the only class that calls all six
readers (five from Phase W4 plus Phase W13-1's OrderReader). Read-only
by construction: it holds `Reader` instances (each already bound to a
`DataSource`) and does nothing but call `.read()` on each and assemble
an `EngineSnapshot`. It never opens a file itself, never writes
anything, and never imports a real engine module."""

from datetime import UTC, datetime

from world.adapter.engine_snapshot import EngineSnapshot
from world.readers.base import Reader


class ReadOnlyIngestionAdapter:
    """Every reader argument is optional so this adapter is usable
    with any subset of the sources wired up — 'without assuming any
    one exists today' (Phase W4 requirement, extended by Phase W13-1
    to the new order reader). A reader whose `.read()` raises (e.g.
    its `DataSource` points at a file that doesn't exist yet) is
    treated as 'no data from that source this capture', not as a
    fatal error — the other readers still run and the adapter still
    returns a valid (partial) `EngineSnapshot`."""

    def __init__(
        self,
        journal_reader: Reader | None = None,
        telemetry_reader: Reader | None = None,
        portfolio_reader: Reader | None = None,
        mission_reader: Reader | None = None,
        event_reader: Reader | None = None,
        order_reader: Reader | None = None,
    ) -> None:
        self._readers = {
            "journal": journal_reader,
            "telemetry": telemetry_reader,
            "portfolio": portfolio_reader,
            "missions": mission_reader,
            "events": event_reader,
            "orders": order_reader,
        }

    def capture_snapshot(self) -> EngineSnapshot:
        results: dict[str, list] = {}
        available: dict[str, bool] = {}
        portfolio_summary = None
        reconciliation = None

        for name, reader in self._readers.items():
            if reader is None:
                results[name] = []
                available[name] = False
                continue
            try:
                results[name] = reader.read()
                available[name] = True
                if name == "portfolio":
                    # Phase W11 — optional side-channel set by
                    # PortfolioReader.read() itself; absent on readers
                    # that don't define it (e.g. in older tests using a
                    # stub Reader), which is exactly why getattr's
                    # default is used rather than a direct attribute
                    # access.
                    portfolio_summary = getattr(reader, "last_summary", None)
                if name == "orders":
                    # Phase W13-1 — same side-channel pattern, for
                    # OrderReader.last_reconciliation.
                    reconciliation = getattr(reader, "last_reconciliation", None)
            except Exception:
                # Any failure to read (missing file, malformed source,
                # unavailable DB, etc.) is "no data this capture," per
                # this adapter's read-only/never-fatal contract - not
                # re-raised, not logged to a production system (this
                # package has no logging dependency on anything
                # outside world/).
                results[name] = []
                available[name] = False

        return EngineSnapshot(
            captured_at=datetime.now(UTC).isoformat(),
            journal_entries=results["journal"],
            telemetry_points=results["telemetry"],
            portfolio_positions=results["portfolio"],
            missions=results["missions"],
            events=results["events"],
            order_states=results["orders"],
            sources_available=available,
            portfolio_summary=portfolio_summary,
            reconciliation=reconciliation,
        )
