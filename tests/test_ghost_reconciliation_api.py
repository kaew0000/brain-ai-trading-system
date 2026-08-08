"""
tests/test_ghost_reconciliation_api.py

Track C3 Phase 2: GET /api/order-state/ghosts (new) and the additive
extension to GET /api/order-state/metrics (api/app.py), backed by
system_health/ghost_reconciliation.py.

Same TestClient(app) singleton-app pattern as tests/test_order_state_api
.py. Resets GhostReconciliationMonitor/OrderStateManager/
ReconciliationEngine singletons around every test so results never leak
between tests despite all three being process-wide.
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
    from system_health.recovery_engine import reset_recovery_engine
    from system_health.ghost_reconciliation import reset_ghost_reconciliation_monitor

    reset_order_state_manager()
    reset_reconciliation_engine()
    reset_recovery_engine()
    reset_ghost_reconciliation_monitor()
    for key in ("data_provider", "journal_v2", "portfolio_state", "trade_lifecycle",
                "event_bus", "order_timeline"):
        set_state(key, None)

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    for key in ("data_provider", "journal_v2", "portfolio_state", "trade_lifecycle",
                "event_bus", "order_timeline"):
        set_state(key, None)
    reset_order_state_manager()
    reset_reconciliation_engine()
    reset_recovery_engine()
    reset_ghost_reconciliation_monitor()


class TestGhostsEndpoint:
    def test_no_position_shape(self, client):
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))

        r = client.get("/api/order-state/ghosts")

        assert r.status_code == 200
        body = r.json()["data"]
        assert body["current"]["status"] == "NO_POSITION"
        assert body["recent"] == [] or isinstance(body["recent"], list)

    def test_ghost_runtime_shape(self, client):
        from api.app import set_state
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))
        set_state("portfolio_state", ps)

        r = client.get("/api/order-state/ghosts")

        assert r.status_code == 200
        body = r.json()["data"]
        assert body["current"]["status"] == "GHOST_RUNTIME"
        assert body["current"]["severity"] == "critical"
        assert len(body["recent"]) >= 1

    def test_symbol_query_param_accepted(self, client):
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))

        r = client.get("/api/order-state/ghosts", params={"symbol": "ETHUSDT"})

        assert r.status_code == 200
        assert r.json()["data"]["current"]["symbol"] == "ETHUSDT"

    def test_never_500s_even_with_no_state_configured(self, client):
        """Read-only observability endpoint: absence of every dependency
        must degrade to UNKNOWN, never raise past the route handler."""
        r = client.get("/api/order-state/ghosts")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_is_read_only_no_mutating_calls_on_data_provider(self, client):
        """No order placement, no cancellation, no forced refresh — only
        the same read calls the existing reconciliation pipeline already
        makes (get_position_info / get_account_balance for orphan-SL
        sizing, both pre-existing, unchanged behavior)."""
        from api.app import set_state
        dp = _dp(True)  # orphan-exchange path, the one that touches recovery most
        set_state("data_provider", dp)
        set_state("journal_v2", _journal([], total_trades=0))

        r = client.get("/api/order-state/ghosts")

        assert r.status_code == 200
        for call in dp.method_calls:
            assert call[0] not in (
                "close_position", "market_close", "place_market_order",
                "place_order", "cancel_order", "cancel_all_orders",
            )


class TestMetricsEndpointBackwardCompatible:
    def test_existing_order_01_fields_still_present(self, client):
        """Extending this endpoint must never remove a working field —
        every key tests/test_order_state_api.py already asserts on must
        still be present and correct."""
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))
        client.get("/api/order-state")  # populate OrderStateManager counters

        r = client.get("/api/order-state/metrics")

        assert r.status_code == 200
        body = r.json()["data"]
        for field in ("sync_count", "desync_count", "ghost_count",
                      "recovery_count", "average_sync_latency_ms"):
            assert field in body
        assert body["sync_count"] >= 1

    def test_c3_2_fields_additively_present(self, client):
        from api.app import set_state
        set_state("data_provider", _dp(False))
        set_state("journal_v2", _journal([], total_trades=5))
        client.get("/api/order-state/ghosts")  # populate GhostReconciliationMonitor counters

        r = client.get("/api/order-state/metrics")

        assert r.status_code == 200
        body = r.json()["data"]
        for field in ("reconciliation_count", "ghost_detected_count", "runtime_mismatch_count",
                      "orphan_exchange_count", "recovery_success_count", "recovery_failure_count",
                      "timeline_desync_count", "reconciliation_latency_ms", "timeline_sync_latency_ms"):
            assert field in body
        assert body["reconciliation_count"] >= 1

    def test_never_500s(self, client):
        r = client.get("/api/order-state/metrics")
        assert r.status_code == 200
        assert r.json()["ok"] is True
