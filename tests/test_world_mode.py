"""tests/test_world_mode.py — V16 §94

The Office World must work in every execution mode (paper / testnet / live / training) and
its portfolio figures must follow the process's own journal lane instead of blending lanes.
Production symptom this guards against: the always-on TRAINING lane's paper trades showing
up as the real account's PnL / win rate in the World's System Pulse.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from journal.journal_v2 import TradeJournalV2, TradeRecord
from telemetry.world_export import execution_context, portfolio_payload

pytestmark = pytest.mark.unit

# mode -> (lane, realMoney) exactly as config.settings maps them; "training" is not an
# EXECUTION_MODE value, it exercises the fail-safe (unrecognized -> TRAINING lane).
MODES = {
    "paper": ("TRAINING", False),
    "testnet": ("LIVE", False),
    "live": ("LIVE", True),
    "training": ("TRAINING", False),
}


@pytest.fixture()
def set_mode(monkeypatch):
    import config.settings as cfg

    def _set(mode: str) -> None:
        lane = {"live": "LIVE", "testnet": "LIVE", "paper": "TRAINING"}.get(mode, "TRAINING")
        monkeypatch.setattr(cfg, "EXECUTION_MODE", mode)
        monkeypatch.setattr(cfg, "EXECUTION_LANE", lane)

    return _set


@pytest.fixture()
def client():
    from api.app import app

    return TestClient(app, raise_server_exceptions=False)


def _closed_trade(journal: TradeJournalV2, lane: str, result: str, pnl: float) -> None:
    rec = TradeRecord()
    rec.timestamp = datetime.now(timezone.utc).isoformat()
    rec.symbol, rec.direction = "BTCUSDT", "LONG"
    rec.entry_price, rec.stop_loss, rec.take_profit = 80_000.0, 79_000.0, 82_000.0
    rec.result = "OPEN"
    tid = journal.save_trade(rec, execution_lane=lane)
    journal.update_trade_result(tid, result, 81_000.0, pnl)


@pytest.mark.parametrize("mode", list(MODES))
def test_execution_context_reports_mode_lane_and_real_money(set_mode, mode):
    set_mode(mode)
    ctx = execution_context()
    lane, real = MODES[mode]
    assert ctx["mode"] == mode
    assert ctx["lane"] == lane
    assert ctx["realMoney"] is real
    assert ctx["laneScoped"] is True


@pytest.mark.parametrize("mode", list(MODES))
def test_world_api_serves_every_mode(client, set_mode, mode):
    set_mode(mode)
    mode_resp = client.get("/api/world/mode")
    assert mode_resp.status_code == 200
    assert mode_resp.json()["data"]["mode"] == mode
    for path in ("/api/world/state", "/api/world/simulation", "/api/world/rooms"):
        assert client.get(path).status_code == 200, f"{path} failed in {mode} mode"
    sim = client.get("/api/world/simulation").json()["data"]
    assert len(sim["characters"]) == 16
    assert len(sim["rooms"]) == 17


def test_execution_context_survives_missing_settings(monkeypatch):
    import config.settings as cfg

    monkeypatch.delattr(cfg, "EXECUTION_LANE")
    ctx = execution_context()
    assert ctx == {"mode": "unknown", "lane": None, "laneScoped": False, "realMoney": False}


@pytest.fixture()
def mixed_journal(tmp_path, monkeypatch):
    import portfolio.portfolio_history as ph

    monkeypatch.setattr(ph, "get_latest_decisions", lambda limit=1: [])
    journal = TradeJournalV2(db_path=str(tmp_path / "world_lane.db"))
    _closed_trade(journal, "LIVE", "WIN", 50.0)
    _closed_trade(journal, "TRAINING", "LOSS", -30.0)
    _closed_trade(journal, "TRAINING", "LOSS", -20.0)
    return journal


@pytest.mark.parametrize("mode", list(MODES))
def test_portfolio_summary_is_scoped_to_the_processs_lane(set_mode, mixed_journal, mode):
    set_mode(mode)
    summary = portfolio_payload(journal=mixed_journal)["summary"]
    if MODES[mode][0] == "LIVE":
        assert summary["dailyPnl"] == 50.0
        assert summary["winRate"] == 1.0
    else:
        assert summary["dailyPnl"] == -50.0
        assert summary["winRate"] == 0.0


def test_lane_scoping_can_be_switched_off(set_mode, mixed_journal, monkeypatch):
    import config.settings as cfg

    set_mode("live")
    monkeypatch.setattr(cfg.settings, "WORLD_LANE_SCOPED_PORTFOLIO", False)
    summary = portfolio_payload(journal=mixed_journal)["summary"]
    assert summary["dailyPnl"] == 0.0  # 50 - 30 - 20: every lane combined (legacy view)
