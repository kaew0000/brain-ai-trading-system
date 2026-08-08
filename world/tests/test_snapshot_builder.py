"""Phase W4: SnapshotBuilder output must validate against the real
`world/data/schemas/*.schema.json` files — not a copy of them — so
this test catches drift at the source."""

import json
import os

import jsonschema

from world.adapter.engine_snapshot import EngineSnapshot
from world.adapter.snapshot_builder import SnapshotBuilder
from world.readers.event_reader import Event
from world.readers.journal_reader import JournalEntry
from world.readers.mission_reader import Mission
from world.readers.order_reader import OrderTimelineEntry, ReconciliationSnapshot
from world.readers.portfolio_reader import PortfolioPosition
from world.readers.telemetry_reader import TelemetryPoint

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")


def _schema(name):
    with open(os.path.join(SCHEMAS_DIR, name)) as f:
        return json.load(f)


def _sample_snapshot() -> EngineSnapshot:
    return EngineSnapshot(
        captured_at="2026-07-30T00:00:00+00:00",
        journal_entries=[JournalEntry("j1", "t", "BTCUSDT", "open")],
        telemetry_points=[TelemetryPoint("lag", 0.5, "seconds", "data-center")],
        portfolio_positions=[PortfolioPosition("BTCUSDT", "portfolio-garden", "medium")],
        missions=[Mission("m1", "Title", "recovery-center", "active")],
        events=[
            Event("e1", "t", "trade_fill", "execution-forge", "success", "FORGE", "filled"),
            Event("e2", "t", "risk_flag", "risk-fortress", "warning", "BASTION", "elevated exposure"),
        ],
        order_states=[OrderTimelineEntry("BTCUSDT", "OPEN")],
        sources_available={
            "journal": True, "telemetry": True, "portfolio": True,
            "missions": True, "events": True, "orders": True,
        },
    )


def test_build_world_matches_schema():
    data = SnapshotBuilder().build_world(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("world.schema.json"))
    assert data["engineStatus"] == "active"
    assert "execution-forge" in data["activeDistricts"]
    assert "FORGE" in data["activeAgents"]


def test_build_world_idle_when_nothing_available():
    empty = EngineSnapshot(captured_at="t", sources_available={"journal": False})
    data = SnapshotBuilder().build_world(empty)
    assert data["engineStatus"] == "idle"


def test_build_events_matches_schema():
    data = SnapshotBuilder().build_events(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("events.schema.json"))
    assert len(data) == 2


def test_build_missions_matches_schema():
    data = SnapshotBuilder().build_missions(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("missions.schema.json"))


def test_build_portfolio_matches_schema():
    data = SnapshotBuilder().build_portfolio(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("portfolio.schema.json"))
    assert data["totalPositions"] == 1


def test_build_portfolio_has_no_summary_key_when_snapshot_has_none():
    """The exact pre-W11 output shape, byte for byte, when there's
    nothing to add."""
    data = SnapshotBuilder().build_portfolio(_sample_snapshot())
    assert "summary" not in data


def test_build_portfolio_includes_summary_when_present():
    from world.readers.portfolio_reader import PortfolioSummary

    snapshot = _sample_snapshot()
    snapshot.portfolio_summary = PortfolioSummary(
        daily_pnl=10.5, floating_pnl=-2.0, drawdown=0.08, win_rate=0.6, avg_rr=1.4,
    )
    data = SnapshotBuilder().build_portfolio(snapshot)
    jsonschema.validate(instance=data, schema=_schema("portfolio.schema.json"))
    assert data["summary"] == {
        "dailyPnl": 10.5, "floatingPnl": -2.0, "drawdown": 0.08, "winRate": 0.6, "avgRr": 1.4,
    }


def test_build_portfolio_omits_individual_none_summary_fields():
    """A summary field the trading engine didn't supply is left out
    entirely, never written as 0 or null."""
    from world.readers.portfolio_reader import PortfolioSummary

    snapshot = _sample_snapshot()
    snapshot.portfolio_summary = PortfolioSummary(drawdown=0.05)  # everything else None
    data = SnapshotBuilder().build_portfolio(snapshot)
    assert data["summary"] == {"drawdown": 0.05}
    jsonschema.validate(instance=data, schema=_schema("portfolio.schema.json"))


def test_build_telemetry_matches_schema():
    data = SnapshotBuilder().build_telemetry(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("telemetry.schema.json"))


def test_build_notifications_matches_schema_and_derives_from_warning_and_critical_only():
    data = SnapshotBuilder().build_notifications(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("notifications.schema.json"))
    # sample snapshot has one "success" event and one "warning" event -
    # only the warning should become a notification
    assert len(data) == 1
    assert data[0]["severity"] == "warning"


def test_build_all_keys_match_runtime_filenames():
    outputs = SnapshotBuilder().build_all(_sample_snapshot())
    assert set(outputs.keys()) == {
        "world", "events", "missions", "portfolio", "telemetry", "notifications", "orders",
    }


def test_build_orders_matches_schema():
    data = SnapshotBuilder().build_orders(_sample_snapshot())
    jsonschema.validate(instance=data, schema=_schema("orders.schema.json"))
    assert data["activeCount"] == 1
    assert data["states"] == [{"symbol": "BTCUSDT", "state": "OPEN"}]


def test_build_orders_no_reconciliation_key_when_snapshot_has_none():
    """Same discipline build_portfolio()'s `summary` key uses: absent
    entirely, never fabricated as nulls/zeros."""
    data = SnapshotBuilder().build_orders(_sample_snapshot())
    assert "reconciliation" not in data


def test_build_orders_includes_reconciliation_when_present():
    snapshot = _sample_snapshot()
    snapshot.reconciliation = ReconciliationSnapshot(
        last_run="2026-07-30T00:00:00+00:00", last_result="clean",
        event_count=3, suppressed_repeat_count=1,
    )
    data = SnapshotBuilder().build_orders(snapshot)
    jsonschema.validate(instance=data, schema=_schema("orders.schema.json"))
    assert data["reconciliation"] == {
        "lastRun": "2026-07-30T00:00:00+00:00", "lastResult": "clean",
        "eventCount": 3, "suppressedRepeatCount": 1,
    }


def test_build_orders_omits_individual_none_reconciliation_fields():
    snapshot = _sample_snapshot()
    snapshot.reconciliation = ReconciliationSnapshot(last_result="clean")  # everything else None
    data = SnapshotBuilder().build_orders(snapshot)
    assert data["reconciliation"] == {"lastResult": "clean"}
    jsonschema.validate(instance=data, schema=_schema("orders.schema.json"))


def test_build_orders_empty_when_no_order_states():
    empty = EngineSnapshot(captured_at="t")
    data = SnapshotBuilder().build_orders(empty)
    jsonschema.validate(instance=data, schema=_schema("orders.schema.json"))
    assert data["activeCount"] == 0
    assert data["states"] == []
    assert "reconciliation" not in data
