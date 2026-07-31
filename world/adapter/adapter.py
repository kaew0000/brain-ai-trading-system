"""ReadOnlyIngestionAdapter — the only class that calls all five
readers. Read-only by construction: it holds `Reader` instances (each
already bound to a `DataSource`) and does nothing but call
`.read()` on each and assemble an `EngineSnapshot`. It never opens a
file itself, never writes anything, and never imports a real engine
module."""

from datetime import UTC, datetime

from world.adapter.engine_snapshot import EngineSnapshot
from world.readers.base import Reader


class ReadOnlyIngestionAdapter:
    """Every reader argument is optional so this adapter is usable
    with any subset of the five sources wired up — 'without assuming
    any one exists today' (Phase W4 requirement). A reader whose
    `.read()` raises (e.g. its `DataSource` points at a file that
    doesn't exist yet) is treated as 'no data from that source this
    capture', not as a fatal error — the other four readers still run
    and the adapter still returns a valid (partial) `EngineSnapshot`."""

    def __init__(
        self,
        journal_reader: Reader | None = None,
        telemetry_reader: Reader | None = None,
        portfolio_reader: Reader | None = None,
        mission_reader: Reader | None = None,
        event_reader: Reader | None = None,
    ) -> None:
        self._readers = {
            "journal": journal_reader,
            "telemetry": telemetry_reader,
            "portfolio": portfolio_reader,
            "missions": mission_reader,
            "events": event_reader,
        }

    def capture_snapshot(self) -> EngineSnapshot:
        results: dict[str, list] = {}
        available: dict[str, bool] = {}

        for name, reader in self._readers.items():
            if reader is None:
                results[name] = []
                available[name] = False
                continue
            try:
                results[name] = reader.read()
                available[name] = True
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
            sources_available=available,
        )
