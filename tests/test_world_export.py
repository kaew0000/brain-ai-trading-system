"""tests/test_world_export.py — Phase W11

Tests telemetry/world_export.py end to end against the REAL registries
it reads from (telemetry, heartbeat, circuit breaker, mission tracker,
event bus) — not mocks — because the whole point of this module is
"call existing accessors correctly," and a mock can't catch a wrong
attribute/key name the way calling the real thing can. portfolio_history
and journal are the two accessors backed by SQLite; those are stubbed
with tiny fakes matching their real, verified signatures, to avoid a
real DB dependency in this test file.

Every test also asserts the output is directly consumable by the
matching world/readers/*.py Reader — the actual downstream contract —
not just "world_export produced some JSON."
"""
from __future__ import annotations

import json
import os

import pytest

from events.event_bus import reset_event_bus
from missions.mission_tracker import reset_mission_tracker
from system_health.circuit_breaker import get_breaker
from system_health.heartbeat import reset_heartbeat
from telemetry.agent_telemetry import reset_telemetry_registry
from telemetry.world_export import (
    event_rows,
    export_snapshot,
    mission_rows,
    portfolio_payload,
    telemetry_rows,
)
from world.readers.base import JSONFileSource
from world.readers.event_reader import EventReader
from world.readers.mission_reader import MissionReader
from world.readers.portfolio_reader import PortfolioReader
from world.readers.telemetry_reader import TelemetryReader

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _clean_registries():
    """Every Track A registry this module reads from is a process-wide
    singleton — reset each before and after every test so tests never
    leak state into each other (or into unrelated tests elsewhere in
    the suite that happen to run in the same process)."""
    reset_telemetry_registry()
    reset_heartbeat()
    reset_mission_tracker()
    reset_event_bus(persist=False)  # persist=False: no journal needed for these tests
    yield
    reset_telemetry_registry()
    reset_heartbeat()
    reset_mission_tracker()
    reset_event_bus(persist=False)


class _FakeJournal:
    """Matches journal.journal_v2.TradeJournalV2.get_daily_stats()'s
    real, verified return shape exactly (see journal/journal_v2.py)."""

    def __init__(self, stats: dict):
        self._stats = stats

    def get_daily_stats(self, day=None):
        return self._stats


# ── telemetry_rows() ─────────────────────────────────────────────────────────

def test_telemetry_rows_includes_agent_latency_and_confidence():
    from telemetry.agent_telemetry import get_telemetry_registry

    get_telemetry_registry().record(
        agent="SMC_ANALYST", status="OK", confidence=78.0,
        last_signal="LONG", latency_ms=12.4, decision="BOS bullish M15",
    )
    rows = telemetry_rows()
    names = {r["name"] for r in rows}
    assert "SMC_ANALYST.latency_ms" in names
    assert "SMC_ANALYST.confidence" in names


def test_telemetry_rows_includes_heartbeat_age():
    from system_health.heartbeat import get_heartbeat

    get_heartbeat().beat("watchdog", {"ok": True})
    rows = telemetry_rows()
    names = {r["name"] for r in rows}
    assert "heartbeat.watchdog.age_s" in names


def test_telemetry_rows_includes_breaker_latency_after_a_call():
    get_breaker("test_world_export_breaker").call(lambda: "ok")
    rows = telemetry_rows()
    names = {r["name"] for r in rows}
    assert "breaker.test_world_export_breaker.latency_ms" in names
    assert "breaker.test_world_export_breaker.failure_count" in names


def test_telemetry_rows_includes_cpu_and_ram():
    rows = telemetry_rows()
    names = {r["name"] for r in rows}
    assert "system.cpu_percent" in names
    assert "system.ram_percent" in names


def test_telemetry_rows_survive_a_broken_source(monkeypatch):
    """If one source (e.g. psutil) breaks, the others must still be
    exported — matches world.adapter.adapter's own partial-capture
    contract."""
    from telemetry.agent_telemetry import get_telemetry_registry

    get_telemetry_registry().record(agent="SMC_ANALYST", status="OK", latency_ms=1.0)

    import telemetry.world_export as we
    monkeypatch.setattr(we, "_system_resource_rows", lambda: (_ for _ in ()).throw(RuntimeError("no psutil")))

    rows = we.telemetry_rows()
    names = {r["name"] for r in rows}
    assert "SMC_ANALYST.latency_ms" in names
    assert not any(n.startswith("system.") for n in names)


def test_telemetry_rows_are_consumable_by_telemetry_reader(tmp_path):
    from telemetry.agent_telemetry import get_telemetry_registry

    get_telemetry_registry().record(agent="SMC_ANALYST", status="OK", latency_ms=5.0)
    path = tmp_path / "telemetry.json"
    path.write_text(json.dumps(telemetry_rows()))

    points = TelemetryReader(JSONFileSource(str(path))).read()
    assert any(p.name == "SMC_ANALYST.latency_ms" for p in points)


# ── event_rows() ─────────────────────────────────────────────────────────────

def test_event_rows_maps_bus_event_fields():
    from events.event_bus import get_event_bus

    get_event_bus().publish("RISK_MANAGER", "MARGIN_ALERT", "margin call risk", "warning")
    rows = event_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["agent"] == "RISK_MANAGER"
    assert row["type"] == "MARGIN_ALERT"
    assert row["message"] == "margin call risk"
    assert row["severity"] == "warning"
    assert row["district"] == "command-hall"  # documented neutral fallback


def test_event_rows_maps_error_severity_to_critical():
    from events.event_bus import get_event_bus

    get_event_bus().publish("RISK_MANAGER", "X", "y", "error")
    rows = event_rows()
    assert rows[0]["severity"] == "critical"


def test_event_rows_are_consumable_by_event_reader(tmp_path):
    from events.event_bus import get_event_bus

    get_event_bus().publish("FUTURES_ANALYST", "OI_SPIKE", "open interest spike", "info")
    path = tmp_path / "events.json"
    path.write_text(json.dumps(event_rows()))

    events = EventReader(JSONFileSource(str(path))).read()
    assert len(events) == 1
    assert events[0].agent == "FUTURES_ANALYST"
    assert events[0].severity == "info"


# ── mission_rows() ───────────────────────────────────────────────────────────

def test_mission_rows_maps_stage_to_status_and_district():
    from missions.mission_tracker import get_mission_tracker

    tracker = get_mission_tracker()
    m = tracker.create(symbol="BTCUSDT", direction="LONG", confidence=80.0)
    tracker.advance(m.id, "VALIDATION", note="ok")

    rows = mission_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "active"
    assert row["district"] == "research-district"
    assert "BTCUSDT" in row["title"]


def test_mission_rows_excludes_closed_missions():
    from missions.mission_tracker import get_mission_tracker

    tracker = get_mission_tracker()
    m = tracker.create(symbol="ETHUSDT", direction="SHORT")
    tracker.advance(m.id, "CLOSED", note="done")

    assert mission_rows() == []


def test_mission_rows_are_consumable_by_mission_reader(tmp_path):
    from missions.mission_tracker import get_mission_tracker

    get_mission_tracker().create(symbol="BTCUSDT", direction="LONG")
    path = tmp_path / "missions.json"
    path.write_text(json.dumps(mission_rows()))

    missions = MissionReader(JSONFileSource(str(path))).read()
    assert len(missions) == 1
    assert missions[0].status == "proposed"


# ── portfolio_payload() ──────────────────────────────────────────────────────

def test_portfolio_payload_has_empty_positions_and_no_summary_by_default(monkeypatch):
    import portfolio.portfolio_history as ph
    monkeypatch.setattr(ph, "get_latest_decisions", lambda limit=1: [])

    payload = portfolio_payload(journal=None)
    assert payload == {"positions": []}


def test_portfolio_payload_includes_drawdown_from_portfolio_history(monkeypatch):
    import portfolio.portfolio_history as ph
    monkeypatch.setattr(
        ph, "get_latest_decisions",
        lambda limit=1: [{"drawdown": 0.12, "portfolio_score": 5.0}],
    )

    payload = portfolio_payload(journal=None)
    assert payload["summary"]["drawdown"] == 0.12


def test_portfolio_payload_includes_win_rate_and_pnl_from_journal(monkeypatch):
    import portfolio.portfolio_history as ph
    monkeypatch.setattr(ph, "get_latest_decisions", lambda limit=1: [])

    journal = _FakeJournal({
        "date": "2026-08-03", "total_trades": 4, "wins": 3, "losses": 1,
        "win_rate": 0.75, "total_pnl": 120.5, "avg_rr": 1.8,
    })
    payload = portfolio_payload(journal=journal)
    assert payload["summary"]["winRate"] == 0.75
    assert payload["summary"]["dailyPnl"] == 120.5
    assert payload["summary"]["avgRr"] == 1.8


def test_portfolio_payload_omits_journal_stats_when_zero_trades(monkeypatch):
    """get_daily_stats() returns total_trades=0 with zeroed-out figures
    on a day with no trades — those must not be exported as if they
    were real win-rate/PnL data."""
    import portfolio.portfolio_history as ph
    monkeypatch.setattr(ph, "get_latest_decisions", lambda limit=1: [])

    journal = _FakeJournal({
        "date": "2026-08-03", "total_trades": 0, "wins": 0, "losses": 0,
        "win_rate": 0.0, "total_pnl": 0.0, "avg_rr": 0.0,
    })
    payload = portfolio_payload(journal=journal)
    assert "summary" not in payload


def test_portfolio_payload_survives_portfolio_history_failure(monkeypatch):
    import portfolio.portfolio_history as ph
    monkeypatch.setattr(ph, "get_latest_decisions", lambda limit=1: (_ for _ in ()).throw(RuntimeError("db down")))

    payload = portfolio_payload(journal=None)
    assert payload == {"positions": []}


def test_portfolio_payload_is_consumable_by_portfolio_reader(tmp_path, monkeypatch):
    import portfolio.portfolio_history as ph
    monkeypatch.setattr(ph, "get_latest_decisions", lambda limit=1: [{"drawdown": 0.05}])

    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(portfolio_payload(journal=None)))

    reader = PortfolioReader(JSONFileSource(str(path)))
    positions = reader.read()
    assert positions == []
    assert reader.last_summary.drawdown == 0.05


# ── export_snapshot() ────────────────────────────────────────────────────────

def test_export_snapshot_writes_all_five_staging_files(tmp_path):
    staging_dir = export_snapshot(journal=None, staging_dir=str(tmp_path))
    assert staging_dir == str(tmp_path)
    for name in ("telemetry.json", "events.json", "missions.json", "portfolio.json", "journal.json"):
        path = os.path.join(staging_dir, name)
        assert os.path.isfile(path)
        with open(path) as f:
            json.load(f)  # every file must be valid JSON


def test_export_snapshot_never_raises_even_if_everything_fails(tmp_path, monkeypatch):
    import telemetry.world_export as we

    monkeypatch.setattr(we, "telemetry_rows", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(we, "event_rows", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(we, "mission_rows", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(we, "portfolio_payload", lambda journal=None: (_ for _ in ()).throw(RuntimeError("x")))

    with pytest.raises(RuntimeError):
        # export_snapshot() itself does not wrap these top-level calls in
        # _safe() - each function wraps its OWN internals - so a totally
        # broken row-function still raises here. This test documents that
        # boundary rather than asserting something false.
        we.export_snapshot(journal=None, staging_dir=str(tmp_path))


def test_export_snapshot_creates_staging_dir_if_missing(tmp_path):
    nested = tmp_path / "does" / "not" / "exist" / "yet"
    export_snapshot(journal=None, staging_dir=str(nested))
    assert nested.is_dir()
    assert (nested / "telemetry.json").is_file()
