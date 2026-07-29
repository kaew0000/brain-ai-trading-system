"""tests/test_lifecycle_api.py — V16 Phase 4B Step 3D, Part G"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from execution.trade_lifecycle import (
    get_default_trade_lifecycle,
    reset_default_trade_lifecycle,
    CloseSource,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset():
    reset_default_trade_lifecycle()
    yield
    reset_default_trade_lifecycle()


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


class TestLifecycleStateEndpoint:
    def test_empty_state_returns_empty_list(self, client):
        r = client.get("/api/lifecycle/state")
        assert r.status_code == 200
        assert r.json()["data"]["positions"] == []
        assert r.json()["data"]["count"] == 0

    def test_open_position_appears_in_state(self, client):
        lc = get_default_trade_lifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        r = client.get("/api/lifecycle/state")
        data = r.json()["data"]
        assert data["count"] == 1
        assert data["positions"][0]["symbol"] == "BTCUSDT"
        assert data["positions"][0]["state"] == "MONITORING"

    def test_closed_position_excluded_from_state(self, client):
        lc = get_default_trade_lifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        r = client.get("/api/lifecycle/state")
        assert r.json()["data"]["positions"] == []


class TestLifecycleStateForSymbolEndpoint:
    def test_unknown_symbol_returns_null_state_not_404(self, client):
        r = client.get("/api/lifecycle/state/NEVERUSDT")
        assert r.status_code == 200
        assert r.json()["data"]["state"] is None

    def test_known_symbol_returns_its_state(self, client):
        lc = get_default_trade_lifecycle()
        h = lc.open_pending("ETHUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=2)
        r = client.get("/api/lifecycle/state/ETHUSDT")
        data = r.json()["data"]
        assert data["symbol"] == "ETHUSDT"
        assert data["state"] == "MONITORING"

    def test_exit_reason_and_source_exposed(self, client):
        lc = get_default_trade_lifecycle()
        h = lc.open_pending("ETHUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=2)
        lc.request_exit("ETHUSDT", CloseSource.STOP_LOSS, "sl_hit")
        r = client.get("/api/lifecycle/state/ETHUSDT")
        data = r.json()["data"]
        assert data["exit_reason"] == "sl_hit"
        assert data["exit_source"] == "SL"
