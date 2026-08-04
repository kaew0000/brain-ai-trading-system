"""Phase W5: StateBuilder — merging Phase W4 runtime snapshots plus static
canon into a WorldState."""
import json
import os

import pytest

from world.runtime.state_builder import StateBuilder

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISTRICT_DEFS_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")
CHAR_DEFS_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")
PLACEMENT_PATH = os.path.join(WORLD_ROOT, "data", "characters", "placement.json")


@pytest.fixture
def empty_runtime_dir(tmp_path):
    """No files at all — everything must default cleanly."""
    return str(tmp_path)


@pytest.fixture
def populated_runtime_dir(tmp_path):
    d = tmp_path
    (d / "world.json").write_text(json.dumps({
        "engineStatus": "active", "version": "0.2.0", "timestamp": "2026-08-01T00:00:00Z",
        "activeAgents": ["primus", "forge"], "activeDistricts": ["ceo-tower", "execution-forge"],
    }))
    (d / "missions.json").write_text(json.dumps([
        {"id": "m1", "title": "Stabilize", "district": "recovery-center", "status": "active",
         "description": "test mission"},
    ]))
    (d / "portfolio.json").write_text(json.dumps({
        "positions": [{"symbol": "BTCUSDT", "district": "portfolio-garden", "sizeLabel": "large"}],
        "timestamp": "2026-08-01T00:00:00Z",
    }))
    (d / "telemetry.json").write_text(json.dumps({
        "metrics": [{"name": "latency_ms", "value": 12.5, "unit": "ms", "district": "data-center"}],
        "timestamp": "2026-08-01T00:00:00Z",
    }))
    (d / "notifications.json").write_text(json.dumps([
        {"id": "notif-from-e1", "timestamp": "2026-08-01T00:00:00Z", "message": "fill",
         "severity": "success", "read": False},
    ]))
    (d / "events.json").write_text(json.dumps([
        {"id": "e1", "timestamp": "2026-08-01T00:00:00Z", "type": "trade_fill",
         "district": "execution-forge", "severity": "success", "agent": "FORGE", "message": "filled"},
    ]))
    return str(d)


def _builder(runtime_dir):
    return StateBuilder(
        runtime_dir=runtime_dir,
        district_defs_dir=DISTRICT_DEFS_DIR,
        char_defs_dir=CHAR_DEFS_DIR,
        placement_path=PLACEMENT_PATH,
    )


def test_build_with_no_runtime_files_defaults_cleanly(empty_runtime_dir):
    state = _builder(empty_runtime_dir).build()
    assert state.engine_status == "idle"
    assert len(state.rooms) == 17  # 14 departments + lobby/hallway/elevator
    assert len(state.agents) == 16
    assert state.missions == ()
    assert state.portfolio == ()
    assert state.portfolio_summary is None
    assert state.notifications == ()
    assert state.events == ()
    assert state.telemetry == ()


def test_build_merges_every_populated_source(populated_runtime_dir):
    state = _builder(populated_runtime_dir).build()
    assert state.engine_status == "active"
    assert state.version == "0.2.0"
    assert len(state.missions) == 1
    assert state.missions[0].district == "recovery-center"
    assert len(state.portfolio) == 1
    assert state.portfolio[0].symbol == "BTCUSDT"
    assert len(state.telemetry) == 1
    assert len(state.notifications) == 1
    assert len(state.events) == 1


def test_portfolio_summary_parses_when_present(tmp_path):
    """Phase W11 — the one field state_builder gained."""
    (tmp_path / "portfolio.json").write_text(json.dumps({
        "positions": [],
        "summary": {"dailyPnl": 12.5, "floatingPnl": -1.0, "drawdown": 0.07, "winRate": 0.65, "avgRr": 1.9},
        "timestamp": "2026-08-01T00:00:00Z",
    }))
    state = _builder(str(tmp_path)).build()
    assert state.portfolio_summary is not None
    assert state.portfolio_summary.daily_pnl == 12.5
    assert state.portfolio_summary.floating_pnl == -1.0
    assert state.portfolio_summary.drawdown == 0.07
    assert state.portfolio_summary.win_rate == 0.65
    assert state.portfolio_summary.avg_rr == 1.9
    assert state.to_dict()["portfolioSummary"] == {
        "dailyPnl": 12.5, "floatingPnl": -1.0, "drawdown": 0.07, "winRate": 0.65, "avgRr": 1.9,
    }


def test_portfolio_summary_is_none_when_portfolio_json_has_no_summary_key(populated_runtime_dir):
    """populated_runtime_dir's portfolio.json (above) is the pre-W11
    shape — proves old runtime output still builds a valid WorldState
    with portfolio_summary simply absent, not a fabricated zero."""
    state = _builder(populated_runtime_dir).build()
    assert state.portfolio_summary is None
    assert state.to_dict()["portfolioSummary"] is None


def test_portfolio_summary_with_partial_fields(tmp_path):
    (tmp_path / "portfolio.json").write_text(json.dumps({
        "positions": [], "summary": {"drawdown": 0.03},
    }))
    state = _builder(str(tmp_path)).build()
    assert state.portfolio_summary.drawdown == 0.03
    assert state.portfolio_summary.daily_pnl is None
    assert state.portfolio_summary.win_rate is None


def test_active_agents_marked_active_and_working(populated_runtime_dir):
    state = _builder(populated_runtime_dir).build()
    primus = next(a for a in state.agents if a.agent_id == "primus")
    scribe = next(a for a in state.agents if a.agent_id == "scribe")
    assert primus.is_active is True
    assert primus.status == "working"
    assert scribe.is_active is False
    assert scribe.status == "idle"


def test_room_active_district_reflected(populated_runtime_dir):
    state = _builder(populated_runtime_dir).build()
    ceo_tower = next(r for r in state.rooms if r.room_id == "ceo-tower")
    lobby = next(r for r in state.rooms if r.room_id == "lobby")
    assert ceo_tower.is_active is True
    assert lobby.is_active is False


def test_room_occupants_match_agent_home_rooms(empty_runtime_dir):
    state = _builder(empty_runtime_dir).build()
    ceo_tower = next(r for r in state.rooms if r.room_id == "ceo-tower")
    assert "primus" in ceo_tower.occupant_agent_ids


def test_room_active_mission_ids_match_district(populated_runtime_dir):
    state = _builder(populated_runtime_dir).build()
    recovery = next(r for r in state.rooms if r.room_id == "recovery-center")
    assert "m1" in recovery.active_mission_ids


def test_build_never_mutates_source_files(populated_runtime_dir):
    world_json_path = populated_runtime_dir + "/world.json"
    original_bytes = open(world_json_path, "rb").read()
    _builder(populated_runtime_dir).build()
    after_bytes = open(world_json_path, "rb").read()
    assert original_bytes == after_bytes
