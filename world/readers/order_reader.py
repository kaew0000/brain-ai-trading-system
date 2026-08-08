"""OrderReader — turns raw order-timeline rows into `OrderTimelineEntry`
dataclasses. Source-agnostic, same shape as `portfolio_reader.py`.

Phase W13-1: consumes whatever `telemetry/world_export.py`'s
`orders_payload()` already wrote to the staging directory — that
function is the ONLY place in this codebase that touches
`execution.order_timeline.OrderTimeline` or
`system_health.reconciliation.ReconciliationEngine` directly. This
reader never imports either of those modules; it only interprets the
plain dict/list JSON shape they were serialized into, exactly like
every other reader in this package interprets its own JSON shape.

Reconciliation is a side-channel, same pattern `PortfolioReader.
last_summary` (Phase W11) already established for portfolio-wide
figures riding alongside per-item rows: `self.last_reconciliation` is
set by `read()` and is `None` whenever the payload has no
`reconciliation` object (older shape, or the engine simply hasn't run
yet this capture) — never fabricated.
"""

from dataclasses import dataclass

from world.readers.base import DataSource, Reader


@dataclass
class OrderTimelineEntry:
    symbol: str
    state: str | None = None


@dataclass
class ReconciliationSnapshot:
    """Reconciliation-wide, read-only figures for one capture — mirrors
    `system_health.reconciliation.ReconciliationEngine.status()`'s own
    shape verbatim (last_run/last_result/event_count/
    suppressed_repeat_count). `None` on `EngineSnapshot` when the
    payload has no `reconciliation` object at all."""

    last_run: str | None = None
    last_result: str | None = None
    event_count: int | None = None
    suppressed_repeat_count: int | None = None


class OrderReader(Reader):
    """`self.source.load_raw()` is expected to return the dict shape
    `telemetry.world_export.orders_payload()` produces:
    `{"timestamp": ..., "states": [{"symbol": ..., "state": ...}, ...],
    "reconciliation": {...} | omitted}`.

    Rows missing `symbol` are skipped, same "skip the bad row, keep
    the rest" discipline `TelemetryReader`/`EventReader` use. A
    missing `reconciliation` key, or one that isn't a dict, leaves
    `self.last_reconciliation` as `None` rather than raising."""

    def __init__(self, source: DataSource) -> None:
        super().__init__(source)
        self.last_reconciliation: ReconciliationSnapshot | None = None

    def read(self) -> list[OrderTimelineEntry]:
        raw = self.source.load_raw()
        self.last_reconciliation = None

        if isinstance(raw, dict):
            rows = raw.get("states", [])
            recon_raw = raw.get("reconciliation")
            if isinstance(recon_raw, dict):
                self.last_reconciliation = ReconciliationSnapshot(
                    last_run=recon_raw.get("lastRun", recon_raw.get("last_run")),
                    last_result=recon_raw.get("lastResult", recon_raw.get("last_result")),
                    event_count=recon_raw.get("eventCount", recon_raw.get("event_count")),
                    suppressed_repeat_count=recon_raw.get(
                        "suppressedRepeatCount", recon_raw.get("suppressed_repeat_count")
                    ),
                )
        else:
            rows = raw or []  # defensive: tolerate a bare list too

        entries = []
        for row in rows:
            try:
                entries.append(
                    OrderTimelineEntry(
                        symbol=str(row["symbol"]),
                        state=row.get("state"),
                    )
                )
            except (KeyError, TypeError):
                continue
        return entries
