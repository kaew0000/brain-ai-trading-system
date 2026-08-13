"""tests/test_account_api.py — V16 Track W14-1 Item 2: Real Account Telemetry"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from config.settings import EXECUTION_MODE
from exchange_state.manager import get_manager, reset_registry
import api.account_api as account_api

pytestmark = pytest.mark.unit


def _mock_dp(
    wallet_balance=1000.0, symbol="BTCUSDT", qty=0.1, entry=65000.0,
    leverage=5, orders=None,
):
    dp = MagicMock()
    dp.get_account_snapshot.return_value = {
        "wallet_balance": wallet_balance, "available_balance": 500.0,
        "unrealized_pnl": 25.0, "total_margin_balance": wallet_balance,
        "maintenance_margin": 10.0, "initial_margin": 50.0,
        "positions": [{
            "symbol": symbol, "side": "LONG", "quantity": qty,
            "entry_price": entry, "mark_price": entry + 100, "unrealized_pnl": 25.0,
            "leverage": leverage, "margin_type": "ISOLATED", "liquidation_price": 40000.0,
        }] if qty else [],
    }
    dp.get_open_orders.return_value = orders or []
    return dp


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry()
    yield
    reset_registry()


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def fake_journal(monkeypatch):
    """Deterministic realized-PnL/performance source, isolated from any
    real DB — verifies account_api reuses journal_v2's existing summary
    rather than computing its own realized PnL or win-rate/PF."""
    fake = MagicMock()
    fake.get_performance_summary.return_value = {
        "total_trades": 3, "wins": 2, "losses": 1, "win_rate": 0.6667,
        "total_pnl": 42.5, "avg_rr": 1.2, "profit_factor": 2.1,
    }
    fake.get_today_pnl.return_value = 7.25
    monkeypatch.setattr(account_api, "_journal", lambda: fake)
    return fake


class TestNoDataYet:
    def test_no_manager_registered_returns_no_data_yet(self, client):
        r = client.get("/api/account/state")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["status"] == "NO_DATA_YET"
        assert data["account"] is None
        assert data["positions"] == []

    def test_no_data_yet_never_fabricates_zero_balance(self, client):
        data = client.get("/api/account/state").json()["data"]
        # Absence must stay null, never a fake 0 that looks like a real balance.
        assert data["account"] is None
        assert data["realized_pnl_total"] is None


class TestLiveState:
    def test_live_snapshot_maps_account_fields(self, client):
        dp = _mock_dp(wallet_balance=1234.5)
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        assert data["status"] == "LIVE"
        assert data["account"]["wallet_balance"] == 1234.5
        assert data["account"]["available_balance"] == 500.0
        assert data["account"]["unrealized_pnl"] == 25.0

    def test_position_mapping(self, client):
        dp = _mock_dp(symbol="BTCUSDT", qty=0.1, entry=65000.0, leverage=5)
        get_manager(dp, mode=EXECUTION_MODE)
        positions = client.get("/api/account/state").json()["data"]["positions"]
        assert len(positions) == 1
        pos = positions[0]
        assert pos["symbol"] == "BTCUSDT"
        assert pos["side"] == "LONG"
        assert pos["quantity"] == 0.1
        assert pos["entry_price"] == 65000.0
        assert pos["mark_price"] == 65100.0
        assert pos["liquidation_price"] == 40000.0
        assert pos["leverage"] == 5

    def test_notional_and_roi_derivation(self, client):
        dp = _mock_dp(symbol="BTCUSDT", qty=0.1, entry=65000.0, leverage=5)
        get_manager(dp, mode=EXECUTION_MODE)
        pos = client.get("/api/account/state").json()["data"]["positions"][0]
        # notional = qty * mark_price = 0.1 * 65100 = 6510.0
        assert pos["notional"] == pytest.approx(6510.0)
        # margin_used = (qty*entry)/leverage = (0.1*65000)/5 = 1300
        # roi_pct = unrealized_pnl / margin_used * 100 = 25/1300*100
        assert pos["roi_pct"] == pytest.approx(25 / 1300 * 100, rel=1e-4)

    def test_open_order_mapping(self, client):
        orders = [{
            "symbol": "BTCUSDT", "order_id": 1, "client_order_id": "sl-1",
            "side": "SELL", "type": "STOP_MARKET", "status": "NEW",
            "stop_price": 60000.0, "orig_qty": 0.1, "executed_qty": 0.0,
            "reduce_only": True,
        }]
        dp = _mock_dp(orders=orders)
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        assert len(data["orders"]) == 1
        assert data["orders"][0]["is_sl"] is True
        assert data["orders"][0]["stop_price"] == 60000.0

    def test_sl_tp_association_on_position(self, client):
        orders = [
            {
                "symbol": "BTCUSDT", "order_id": 1, "client_order_id": "sl-1",
                "side": "SELL", "type": "STOP_MARKET", "status": "NEW",
                "stop_price": 60000.0, "orig_qty": 0.1, "executed_qty": 0.0,
                "reduce_only": True,
            },
            {
                "symbol": "BTCUSDT", "order_id": 2, "client_order_id": "tp-1",
                "side": "SELL", "type": "TAKE_PROFIT_MARKET", "status": "NEW",
                "stop_price": 70000.0, "orig_qty": 0.1, "executed_qty": 0.0,
                "reduce_only": True,
            },
        ]
        dp = _mock_dp(orders=orders)
        get_manager(dp, mode=EXECUTION_MODE)
        pos = client.get("/api/account/state").json()["data"]["positions"][0]
        assert pos["sl_price"] == 60000.0
        assert pos["tp_price"] == 70000.0

    def test_realized_pnl_reuses_journal_source(self, client, fake_journal):
        dp = _mock_dp()
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        assert data["realized_pnl_total"] == 42.5
        assert data["realized_pnl_today"] == 7.25
        assert data["performance"]["win_rate"] == 0.6667
        assert data["performance"]["profit_factor"] == 2.1
        fake_journal.get_performance_summary.assert_called_once()
        fake_journal.get_today_pnl.assert_called_once()

    def test_performance_absent_fields_stay_null_not_zero_when_no_closed_trades(self, client):
        # Real (non-mocked) journal on an account with no closed trades —
        # get_performance_summary() returns no win_rate/profit_factor keys
        # at all in that case; must surface as null, never a fake 0.
        dp = _mock_dp()
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        assert data["performance"]["total_trades"] == 0
        assert data["performance"]["win_rate"] is None
        assert data["performance"]["profit_factor"] is None

    def test_sector_allocation_derived_from_real_positions(self, client):
        dp = _mock_dp(symbol="BTCUSDT", qty=0.1, entry=65000.0, leverage=5)
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        alloc = data["sector_allocation"]
        assert len(alloc) == 1
        assert alloc[0]["pct"] == pytest.approx(100.0)
        assert alloc[0]["notional"] == pytest.approx(6510.0)

    def test_response_contract_has_expected_keys(self, client):
        dp = _mock_dp()
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        for key in (
            "status", "mode", "account", "positions", "orders",
            "sector_allocation", "realized_pnl_total", "realized_pnl_today",
            "performance", "revision", "fetched_at", "age_seconds",
            "degraded", "stale_reason", "health_score",
        ):
            assert key in data


class TestCachedReadNotPerRequestExchangeCall:
    def test_second_request_within_ttl_does_not_call_provider_again(self, client):
        dp = _mock_dp()
        get_manager(dp, mode=EXECUTION_MODE, ttl_seconds=60)
        client.get("/api/account/state")
        client.get("/api/account/state")
        client.get("/api/account/state")
        # One refresh only (constructor doesn't fetch; first GET triggers
        # it) — three requests inside the TTL window must not each hit
        # Binance, confirming the endpoint reads C1's cache, not a fresh
        # call per request.
        assert dp.get_account_snapshot.call_count == 1

    def test_endpoint_never_constructs_its_own_manager(self, client):
        # No get_manager() call at all in this test — if account_api
        # silently constructed one itself (with no data_provider), this
        # would either crash or fabricate data. It must report
        # NO_DATA_YET instead.
        data = client.get("/api/account/state").json()["data"]
        assert data["status"] == "NO_DATA_YET"


class TestDegradedFreshness:
    def test_refresh_failure_after_prior_success_reports_stale_or_offline(self, client):
        dp = _mock_dp()
        mgr = get_manager(dp, mode=EXECUTION_MODE, ttl_seconds=0)
        client.get("/api/account/state")  # first: LIVE, populates snapshot
        dp.get_account_snapshot.side_effect = TimeoutError("read timed out")
        data = client.get("/api/account/state").json()["data"]
        assert data["status"] in ("STALE", "OFFLINE")
        assert data["degraded"] is True
        assert data["stale_reason"] == "timeout"
        # Last known-good numbers are preserved, not replaced with 0/null.
        assert data["account"]["wallet_balance"] == 1000.0

    def test_rate_limit_reason_reports_error_status(self, client):
        dp = _mock_dp()
        mgr = get_manager(dp, mode=EXECUTION_MODE, ttl_seconds=0)
        client.get("/api/account/state")
        dp.get_account_snapshot.side_effect = Exception("-1003 too many requests")
        data = client.get("/api/account/state").json()["data"]
        assert data["status"] == "ERROR"

    def test_failure_with_no_prior_snapshot_is_no_data_yet(self, client):
        dp = _mock_dp()
        dp.get_account_snapshot.side_effect = ConnectionError("network unreachable")
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        assert data["status"] == "NO_DATA_YET"
        assert data["account"] is None


class TestLifecycleIndependence:
    def test_account_state_available_while_lifecycle_stopped(self, client):
        # W14-0 boots into STOPPED and this test never starts anything —
        # account telemetry must still work, proving no coupling to
        # TradingControlState.lifecycle_state.
        lifecycle = client.get("/api/command/state").json()["data"]
        assert lifecycle.get("lifecycle_state") == "STOPPED" or lifecycle.get("state") == "STOPPED" \
            or "STOPPED" in str(lifecycle)

        dp = _mock_dp()
        get_manager(dp, mode=EXECUTION_MODE)
        data = client.get("/api/account/state").json()["data"]
        assert data["status"] == "LIVE"

    def test_telemetry_refreshes_across_every_lifecycle_state(self, client):
        """Item 3 requirement, explicit: STOPPED -> STARTING -> RUNNING ->
        STOPPING -> STOPPED must each still see fresh telemetry. Uses the
        real W14-0 TradingControlState state machine (commander/
        control_state.py), not a mock, so this fails if account_api ever
        gains a lifecycle_state read/gate in the future."""
        from commander.control_state import reset_control_state

        state = reset_control_state()
        try:
            dp = _mock_dp()
            get_manager(dp, mode=EXECUTION_MODE, ttl_seconds=0)  # force a fresh fetch every call

            assert state.lifecycle_state() == "STOPPED"
            assert client.get("/api/account/state").json()["data"]["status"] == "LIVE"

            assert state.mark_starting() is True
            assert state.lifecycle_state() == "STARTING"
            assert client.get("/api/account/state").json()["data"]["status"] == "LIVE"

            assert state.mark_running() is True
            assert state.lifecycle_state() == "RUNNING"
            assert client.get("/api/account/state").json()["data"]["status"] == "LIVE"

            assert state.mark_stopping() is True
            assert state.lifecycle_state() == "STOPPING"
            assert client.get("/api/account/state").json()["data"]["status"] == "LIVE"

            assert state.mark_stopped() is True
            assert state.lifecycle_state() == "STOPPED"
            assert client.get("/api/account/state").json()["data"]["status"] == "LIVE"

            # Every one of the 5 calls above actually re-fetched (ttl=0) —
            # confirms the endpoint's refresh cadence is driven purely by
            # C1's own cache policy, never by lifecycle_state.
            assert dp.get_account_snapshot.call_count == 5
        finally:
            reset_control_state()
