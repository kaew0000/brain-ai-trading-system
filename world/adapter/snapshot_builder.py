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
        out: dict[str, Any] = {
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

        # Phase W11 — optional portfolio-wide figures. Only ever added
        # when the reader actually supplied a summary; a capture with no
        # summary (Phase W4-shaped source, or the field just wasn't in
        # this payload) produces exactly the Phase W4 output shape, byte
        # for byte, so existing consumers of this file see no change.
        s = snapshot.portfolio_summary
        if s is not None:
            summary: dict[str, Any] = {}
            if s.daily_pnl is not None:
                summary["dailyPnl"] = s.daily_pnl
            if s.floating_pnl is not None:
                summary["floatingPnl"] = s.floating_pnl
            if s.drawdown is not None:
                summary["drawdown"] = s.drawdown
            if s.win_rate is not None:
                summary["winRate"] = s.win_rate
            if s.avg_rr is not None:
                summary["avgRr"] = s.avg_rr
            if summary:
                out["summary"] = summary

        return out

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

    def build_orders(self, snapshot: EngineSnapshot) -> dict[str, Any]:
        """Phase W13-1. `states` is the read-only composite view
        `execution.order_timeline.OrderTimeline.current_state()`
        already produces (see world/readers/order_reader.py — this
        module never talks to OrderTimeline directly). `reconciliation`
        is only present when the order reader's payload actually had
        one this capture — omitted, not fabricated as zeros/nulls,
        same discipline `build_portfolio()`'s `summary` key uses."""
        out: dict[str, Any] = {
            "timestamp": snapshot.captured_at,
            "activeCount": len(snapshot.order_states),
            "states": [
                {"symbol": o.symbol, "state": o.state}
                for o in snapshot.order_states
            ],
        }

        r = snapshot.reconciliation
        if r is not None:
            reconciliation: dict[str, Any] = {}
            if r.last_run is not None:
                reconciliation["lastRun"] = r.last_run
            if r.last_result is not None:
                reconciliation["lastResult"] = r.last_result
            if r.event_count is not None:
                reconciliation["eventCount"] = r.event_count
            if r.suppressed_repeat_count is not None:
                reconciliation["suppressedRepeatCount"] = r.suppressed_repeat_count
            if reconciliation:
                out["reconciliation"] = reconciliation

        return out

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
        (without extension) - what `RuntimeManager` iterates over.
        Phase W13-1 adds "orders" as the seventh output; RuntimeManager
        needs no change since it already just iterates this dict."""
        return {
            "world": self.build_world(snapshot),
            "events": self.build_events(snapshot),
            "missions": self.build_missions(snapshot),
            "portfolio": self.build_portfolio(snapshot),
            "telemetry": self.build_telemetry(snapshot),
            "notifications": self.build_notifications(snapshot),
            "orders": self.build_orders(snapshot),
        }
