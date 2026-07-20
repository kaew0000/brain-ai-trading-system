"""tests/test_execution_api.py — V16 Phase 2E: Execution Wiring & Live Orchestrator

REST endpoint tests against the real api.app FastAPI singleton (same
pattern as tests/test_portfolio_api.py), with execution_state's
process-wide singleton reset per test rather than hitting a real
exchange/orchestrator — these endpoints only ever read whatever a
running ExecutionOrchestrator already recorded.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from execution.execution_state import get_execution_state, reset_execution_state

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_state():
    reset_execution_state()
    yield
    reset_execution_state()


class TestExecutionMetricsEndpoint:

    def test_no_executions_ever_returns_zeroed_metrics(self, client):
        resp = client.get("/api/execution/metrics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["data"]["total"] == 0
        assert body["data"]["success_rate"] == 0.0

    def test_reflects_recorded_executions(self, client):
        state = get_execution_state()
        state.enqueue("e1", "b1", "BTCUSDT")
        state.start("e1")
        state.complete("e1", {})

        resp = client.get("/api/execution/metrics")
        body = resp.json()["data"]
        assert body["total"] == 1
        assert body["completed"] == 1
        assert body["success_rate"] == 1.0


class TestExecutionStatusEndpoint:

    def test_no_executions_ever_returns_zeroed_status(self, client):
        resp = client.get("/api/execution/status")
        assert resp.status_code == 200
        assert resp.json()["data"] == {
            "pending": 0, "running": 0, "completed": 0,
            "failed": 0, "cancelled": 0, "total_tracked": 0,
        }

    def test_reflects_pending_and_running_counts(self, client):
        state = get_execution_state()
        state.enqueue("e1", "b1", "BTCUSDT")
        state.enqueue("e2", "b1", "ETHUSDT")
        state.start("e2")

        body = client.get("/api/execution/status").json()["data"]
        assert body["pending"] == 1
        assert body["running"] == 1
        assert body["total_tracked"] == 2


class TestExecutionListEndpoint:

    def test_empty_by_default(self, client):
        resp = client.get("/api/execution/executions")
        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_lists_all_records_newest_first(self, client):
        state = get_execution_state()
        state.enqueue("e1", "b1", "BTCUSDT")
        state.enqueue("e2", "b1", "ETHUSDT")

        body = client.get("/api/execution/executions").json()["data"]
        assert [r["execution_id"] for r in body] == ["e2", "e1"]

    def test_filters_by_status(self, client):
        state = get_execution_state()
        state.enqueue("e1", "b1", "BTCUSDT")
        state.start("e1")
        state.complete("e1", {})
        state.enqueue("e2", "b1", "ETHUSDT")  # stays PENDING

        body = client.get("/api/execution/executions?status=COMPLETED").json()["data"]
        assert [r["execution_id"] for r in body] == ["e1"]

    def test_status_filter_is_case_insensitive(self, client):
        state = get_execution_state()
        state.enqueue("e1", "b1", "BTCUSDT")
        body = client.get("/api/execution/executions?status=pending").json()["data"]
        assert [r["execution_id"] for r in body] == ["e1"]

    def test_invalid_status_returns_422(self, client):
        resp = client.get("/api/execution/executions?status=NOT_A_STATUS")
        assert resp.status_code == 422
        assert resp.json()["ok"] is False

    def test_limit_caps_results(self, client):
        state = get_execution_state()
        for i in range(5):
            state.enqueue(f"e{i}", "b1", "BTCUSDT")
        body = client.get("/api/execution/executions?limit=2").json()["data"]
        assert len(body) == 2

    def test_limit_out_of_range_returns_422(self, client):
        resp = client.get("/api/execution/executions?limit=0")
        assert resp.status_code == 422


class TestExecutionDetailEndpoint:

    def test_unknown_execution_id_returns_200_null_not_404(self, client):
        """Matches api/portfolio_api.py's own documented convention:
        an execution simply not existing/not-yet-happened is a normal
        state, not a server error."""
        resp = client.get("/api/execution/executions/does-not-exist")
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    def test_known_execution_id_returns_full_record(self, client):
        state = get_execution_state()
        state.enqueue("exec-123", "batch-1", "BTCUSDT")
        state.start("exec-123")
        state.fail("exec-123", "Invalid qty=0")

        body = client.get("/api/execution/executions/exec-123").json()["data"]
        assert body["execution_id"] == "exec-123"
        assert body["status"] == "FAILED"
        assert body["error"] == "Invalid qty=0"


class TestExecutionApiDoesNotAffectPortfolioApi:
    """Sanity check that adding this router didn't disturb the
    existing, already-merged Phase 2C portfolio endpoints."""

    def test_portfolio_state_endpoint_still_reachable(self, client, monkeypatch):
        monkeypatch.setattr(
            "api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: []
        )
        resp = client.get("/api/portfolio/state")
        assert resp.status_code == 200
