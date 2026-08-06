"""
tests/test_order_state_api.py

V16 Phase ORDER-01: GET /api/order-state and GET /api/order-state/metrics
(api/app.py), backed by system_health/order_state.py.

Uses the same TestClient(app) singleton-app pattern as tests/test_api.py
(Phase-4C's set_state() injection, no create_app() factory). Resets the
OrderStateManager and ReconciliationEngine singletons around every test
so results never leak between tests despite both being process-wide.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@dataclass
class _FakePortfolioPosition:
    direction: str
    quantity: float


def _dp(has_position: bool, side="LONG", qty=0.1062):
    dp = MagicMock()
    dp.get_position_info.return_value = (
        {"side": side, "positionAmt": qty} if has_position else None
    )
    dp.get_account_snapshot.side_effect = Exception("no live account in this test")
    return dp


def _journal(open_trades=None, total_trades=0):
    jrn = MagicMock()
    jrn.get_open_trades.return_value = open_trades or []
    jrn.get_trades.return_value = [None] * total_trades
    return jrn


@pytest.fixture
def client():
    from api.app import app, set_state
    from system_health.order_state import reset_order_state_manager
    from system_health.reconciliation import reset_reconciliation_engine

    reset_order_state_manager()
    reset_reconciliation_engine()
    for key in ("data_provider", "journal_v2", "portfolio_state", "trade_lifecycle", "event_bus"):
        set_state(key, None)

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    for key in ("data_provider", "journal_v2", "portfolio_state", "trade_lifecycle", "event_bus"):
        set_state(key, None)
    reset_order_state_manager()
    reset_reconciliation_engine()


class TestOrderStateEndpoint:
    def test_no_position_shape(self, client):
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))

        r = client.get("/api/order-state")

        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["canonical_state"] == "NO_POSITION"
        assert body["data"]["ghost_detected"] is False

    def test_ghost_position_shape(self, client):
        """The exact production bug this phase was written for: exchange
        flat, journal empty, runtime PortfolioState still open."""
        from api.app import set_state
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))
        set_state("portfolio_state", ps)

        r = client.get("/api/order-state")

        assert r.status_code == 200
        body = r.json()["data"]
        assert body["canonical_state"] == "GHOST"
        assert body["ghost_detected"] is True
        assert body["runtime_position"]["source"] == "portfolio_state"

    def test_symbol_query_param_accepted(self, client):
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))

        r = client.get("/api/order-state", params={"symbol": "BTCUSDT"})

        assert r.status_code == 200
        assert r.json()["data"]["symbol"] == "BTCUSDT"

    def test_never_500s_even_with_no_state_configured(self, client):
        """Read-only observability endpoint: absence of every dependency
        must degrade to UNKNOWN, never raise past the route handler."""
        r = client.get("/api/order-state")
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestOrderStateMetricsEndpoint:
    def test_metrics_shape(self, client):
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))
        client.get("/api/order-state")  # one poll to populate counters

        r = client.get("/api/order-state/metrics")

        assert r.status_code == 200
        body = r.json()["data"]
        for field in ("sync_count", "desync_count", "ghost_count",
                      "recovery_count", "average_sync_latency_ms"):
            assert field in body
        assert body["sync_count"] >= 1
