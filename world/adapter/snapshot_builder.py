"""SnapshotBuilder — the only place that knows how an `EngineSnapshot`
maps onto the six `world/data/runtime/*.json` shapes. Every `build_*`
method's output is validated against its schema in
`world/tests/test_snapshot_builder.py`, so this file and
`world/data/schemas/*.schema.json` cannot silently drift apart.

Design note on `notifications.json`: the Phase W4 task lists five
readers (journal/telemetry/portfolio/mission/event) but six runtime
output files. There is no `notification_reader.py` — notifications
are *derived* from events (`warning`/`critical` severity becomes a
notification) rather than read from a sixth source, since nothing in
the task's reader list suggests a distinct notification source
exists. See `world/docs/SNAPSHOT_FORMAT.md`."""

from typing import Any

from world.adapter.engine_snapshot import EngineSnapshot

SNAPSHOT_FORMAT_VERSION = "0.1.0"
NOTIFICATION_SEVERITIES = ("warning", "critical")


class SnapshotBuilder:
    def build_world(self, snapshot: EngineSnapshot) -> dict[str, Any]:
        any_source_available = any(snapshot.sources_available.values())
        districts = set()
        for e in snapshot.events:
            districts.add(e.district)
        for m in snapshot.missions:
            districts.add(m.district)
        for p in snapshot.portfolio_positions:
            districts.add(p.district)

        agents = {e.agent for e in snapshot.events if e.agent}

        return {
            "version": SNAPSHOT_FORMAT_VERSION,
            "timestamp": snapshot.captured_at,
            "engineStatus": "active" if any_source_available else "idle",
            "activeDistricts": sorted(districts),
            "activeAgents": sorted(agents),
        }

    def build_events(self, snapshot: EngineSnapshot) -> list[dict[str, Any]]:
        return [
            {
                "id": e.event_id,
                "timestamp": e.timestamp,
                "type": e.event_type,
                "district": e.district,
                "agent": e.agent,
                "severity": e.severity,
                "message": e.message,
            }
            for e in snapshot.events
        ]

    def build_missions(self, snapshot: EngineSnapshot) -> list[dict[str, Any]]:
        return [
            {
                "id": m.mission_id,
                "title": m.title,
                "description": m.description,
                "district": m.district,
                "status": m.status,
            }
            for m in snapshot.missions
        ]

    def build_portfolio(self, snapshot: EngineSnapshot) -> dict[str, Any]:
        return {
            "timestamp": snapshot.captured_at,
            "totalPositions": len(snapshot.portfolio_positions),
            "positions": [
                {
                    "symbol": p.symbol,
                    "district": p.district,
                    "sizeLabel": p.size_label,
                }
                for p in snapshot.portfolio_positions
            ],
        }

    def build_telemetry(self, snapshot: EngineSnapshot) -> dict[str, Any]:
        return {
            "timestamp": snapshot.captured_at,
            "metrics": [
                {
                    "name": t.name,
                    "value": t.value,
                    "unit": t.unit,
                    "district": t.district,
                }
                for t in snapshot.telemetry_points
            ],
        }

    def build_notifications(self, snapshot: EngineSnapshot) -> list[dict[str, Any]]:
        return [
            {
                "id": f"notif-from-{e.event_id}",
                "timestamp": e.timestamp,
                "message": e.message,
                "severity": e.severity,
                "read": False,
            }
            for e in snapshot.events
            if e.severity in NOTIFICATION_SEVERITIES
        ]

    def build_all(self, snapshot: EngineSnapshot) -> dict[str, Any]:
        """Convenience: every output keyed by its runtime filename
        (without extension) - what `RuntimeManager` iterates over."""
        return {
            "world": self.build_world(snapshot),
            "events": self.build_events(snapshot),
            "missions": self.build_missions(snapshot),
            "portfolio": self.build_portfolio(snapshot),
            "telemetry": self.build_telemetry(snapshot),
            "notifications": self.build_notifications(snapshot),
        }
