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
        sources_available={"journal": True, "telemetry": True, "portfolio": True, "missions": True, "events": True},
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
    assert set(outputs.keys()) == {"world", "events", "missions", "portfolio", "telemetry", "notifications"}
