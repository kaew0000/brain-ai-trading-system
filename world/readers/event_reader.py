"""EventReader — turns raw event rows into `Event` dataclasses
matching the existing `world/data/schemas/events.schema.json` shape
(Phase W1) exactly."""

from dataclasses import dataclass

from world.readers.base import Reader

VALID_SEVERITIES = ("info", "success", "warning", "critical")


@dataclass
class Event:
    event_id: str
    timestamp: str
    event_type: str
    district: str
    severity: str
    agent: str = ""
    message: str = ""


class EventReader(Reader):
    """Expects `self.source.load_raw()` to return a list of dict-like
    rows with at least `id`/`timestamp`/`type`/`district`/`severity`
    keys. Rows with a `severity` outside `VALID_SEVERITIES` are
    skipped, matching `events.schema.json`'s enum."""

    def read(self) -> list[Event]:
        raw = self.source.load_raw()
        events = []
        for row in raw:
            try:
                severity = str(row["severity"])
                if severity not in VALID_SEVERITIES:
                    continue
                events.append(
                    Event(
                        event_id=str(row["id"]),
                        timestamp=str(row["timestamp"]),
                        event_type=str(row["type"]),
                        district=str(row["district"]),
                        severity=severity,
                        agent=str(row.get("agent", "")),
                        message=str(row.get("message", "")),
                    )
                )
            except (KeyError, TypeError):
                continue
        return events
