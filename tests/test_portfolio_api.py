"""tests/test_portfolio_api.py — V16 Phase 2C

REST endpoint tests against the real api.app FastAPI singleton (same
pattern as tests/test_api.py), with portfolio_history's read functions
monkeypatched directly rather than hitting a real DB — faster, and
avoids test_portfolio_history.py's own documented caveat that
`:memory:` is a shared cached connection across the whole test run
(so "no decision ever persisted" isn't reliably reachable via a real
DB in this suite). No network, no Binance, no dashboard.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def _row(**overrides) -> dict:
    base = {
        "id": 7,
        "timestamp": "2026-07-19T00:00:00+00:00",
        "decided_at": 1750000000.0,
        "blocked": False,
        "block_reason": None,
        "selected_count": 1,
        "rejected_count": 1,
        "replacement_count": 0,
        "total_capital_allocated": 500.0,
        "total_risk_allocated": 5.0,
        "diversification_score": 100.0,
        "portfolio_score": 80.0,
        "drawdown": 0.0,
        "data": {
            "generated_at": 1750000000.0,
            "blocked": False,
            "block_reason": None,
            "selected": [{"symbol": "BTCUSDT", "capital_amount": 500.0, "priority": 1}],
            "rejected": [{"symbol": "ETHUSDT", "rank": 2, "reason": "sector_exposure_exceeded"}],
            "replacements": [],
            "sector_exposure": {"Layer1": 4000.0},
            "diversification_score": 100.0,
            "portfolio_score": 80.0,
            "total_capital_allocated": 500.0,
            "total_risk_allocated": 5.0,
            "explanation": "test",
        },
    }
    base.update(overrides)
    return base


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


class TestPortfolioStateEndpoint:
    def test_no_decision_ever_persisted_returns_empty_positions(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        r = client.get("/api/portfolio/state")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["positions"] == []
        assert body["data"]["live"] is False

    def test_no_decision_returns_200_not_404(self, client, monkeypatch):
        # Matches this codebase's existing convention (e.g. /api/paper,
        # /api/paper/trades): "no data yet" is a normal 200 state, not
        # a server error.
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        assert client.get("/api/portfolio/state").status_code == 200

    def test_with_decision_returns_positions(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        r = client.get("/api/portfolio/state")
        assert r.json()["data"]["positions"][0]["symbol"] == "BTCUSDT"

    def test_state_payload_never_labeled_live(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        r = client.get("/api/portfolio/state")
        assert r.json()["data"]["live"] is False

    def test_state_reports_source_as_latest_persisted_decision(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        r = client.get("/api/portfolio/state")
        assert r.json()["data"]["source"] == "latest_persisted_decision"


class TestPortfolioDecisionLatestEndpoint:
    def test_no_decision_returns_null(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        r = client.get("/api/portfolio/decision/latest")
        assert r.json()["data"]["decision"] is None

    def test_with_decision_returns_full_payload(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        r = client.get("/api/portfolio/decision/latest")
        d = r.json()["data"]["decision"]
        assert d["selected"][0]["symbol"] == "BTCUSDT"
        assert d["rejected"][0]["symbol"] == "ETHUSDT"

    def test_status_code_200(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        assert client.get("/api/portfolio/decision/latest").status_code == 200


class TestPortfolioAllocationsEndpoint:
    def test_no_decision_returns_empty_list(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        r = client.get("/api/portfolio/allocations")
        assert r.json()["data"]["allocations"] == []

    def test_with_decision_returns_selected_only(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        r = client.get("/api/portfolio/allocations")
        allocs = r.json()["data"]["allocations"]
        assert len(allocs) == 1
        assert allocs[0]["symbol"] == "BTCUSDT"


class TestPortfolioSectorsEndpoint:
    def test_no_decision_returns_empty_exposure(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        r = client.get("/api/portfolio/sectors")
        assert r.json()["data"]["sector_exposure"] == {}
        assert r.json()["data"]["diversification_score"] is None

    def test_with_decision_returns_exposure_and_score(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [_row()])
        r = client.get("/api/portfolio/sectors")
        body = r.json()["data"]
        assert body["sector_exposure"] == {"Layer1": 4000.0}
        assert body["diversification_score"] == 100.0


class TestPortfolioHistoryEndpoint:
    def test_empty_history_returns_empty_entries(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", lambda **kw: [])
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 0)
        r = client.get("/api/portfolio/history")
        assert r.json()["data"]["entries"] == []
        assert r.json()["data"]["pagination"]["total"] == 0

    def test_history_passes_limit_and_offset_through(self, client, monkeypatch):
        captured = {}

        def fake_query(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", fake_query)
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 0)
        client.get("/api/portfolio/history?limit=10&offset=20")
        assert captured["limit"] == 10
        assert captured["offset"] == 20

    def test_history_symbol_filter_passed_through(self, client, monkeypatch):
        captured = {}

        def fake_query(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", fake_query)
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 0)
        client.get("/api/portfolio/history?symbol=BTCUSDT")
        assert captured["symbol"] == "BTCUSDT"

    def test_history_sector_filter_passed_through(self, client, monkeypatch):
        captured = {}

        def fake_query(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", fake_query)
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 0)
        client.get("/api/portfolio/history?sector=Layer1")
        assert captured["sector"] == "Layer1"

    def test_history_filtered_query_skips_count_decisions_call(self, client, monkeypatch):
        # total is None (not a real count) whenever a filter is active —
        # count_decisions must not even be called in that case, since
        # its unfiltered number would be a misleading "total".
        called = {"count": False}

        def fake_count():
            called["count"] = True
            return 999

        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", lambda **kw: [])
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", fake_count)
        r = client.get("/api/portfolio/history?symbol=BTCUSDT")
        assert called["count"] is False
        assert r.json()["data"]["pagination"]["total"] is None

    def test_history_unfiltered_query_calls_count_decisions(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", lambda **kw: [])
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 42)
        r = client.get("/api/portfolio/history")
        assert r.json()["data"]["pagination"]["total"] == 42

    def test_history_with_rows_returns_condensed_entries(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", lambda **kw: [_row()])
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 1)
        r = client.get("/api/portfolio/history")
        entry = r.json()["data"]["entries"][0]
        assert entry["symbols"] == ["BTCUSDT"]
        assert "data" not in entry  # condensed, not the full blob

    def test_history_limit_out_of_range_rejected(self, client):
        r = client.get("/api/portfolio/history?limit=10000")
        assert r.status_code == 422

    def test_history_negative_offset_rejected(self, client):
        r = client.get("/api/portfolio/history?offset=-1")
        assert r.status_code == 422

    def test_history_default_limit_is_50(self, client, monkeypatch):
        captured = {}

        def fake_query(**kw):
            captured.update(kw)
            return []

        monkeypatch.setattr("api.portfolio_api.portfolio_history.query_decisions", fake_query)
        monkeypatch.setattr("api.portfolio_api.portfolio_history.count_decisions", lambda: 0)
        client.get("/api/portfolio/history")
        assert captured["limit"] == 50


class TestPortfolioApiNoFabrication:
    """Cross-endpoint checks that nothing here ever invents position/
    allocation data when the persistence layer has nothing to give."""

    @pytest.mark.parametrize("path", [
        "/api/portfolio/state",
        "/api/portfolio/decision/latest",
        "/api/portfolio/allocations",
        "/api/portfolio/sectors",
    ])
    def test_endpoint_marks_response_as_not_live(self, client, monkeypatch, path):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        r = client.get(path)
        assert r.json()["data"]["live"] is False

    def test_empty_state_contains_no_symbol_keys_anywhere(self, client, monkeypatch):
        monkeypatch.setattr("api.portfolio_api.portfolio_history.get_latest_decisions", lambda limit=1: [])
        r = client.get("/api/portfolio/state")
        assert "BTCUSDT" not in str(r.json())
