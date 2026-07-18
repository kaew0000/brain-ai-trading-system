"""
tests/test_api.py

25 smoke tests for the Phase-4C Dashboard API (singleton pattern).
All endpoints return {"ok": True, "data": ...}.

Phase-4C api/app.py uses set_state() injection — no create_app() factory.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

def _make_decision(**kwargs):
    d = MagicMock()
    d.action       = kwargs.get("action",       "LONG")
    d.direction    = kwargs.get("direction",     "LONG")
    d.entry_price  = kwargs.get("entry_price",  67_000.0)
    d.stop_loss    = kwargs.get("stop_loss",    65_800.0)
    d.take_profit  = kwargs.get("take_profit",  69_400.0)
    d.confidence   = kwargs.get("confidence",   78)
    d.regime       = kwargs.get("regime",       "TREND")
    d.oi_delta     = kwargs.get("oi_delta",     0.012)
    d.funding_rate = kwargs.get("funding_rate", 0.00010)
    d.to_dict.return_value = {
        "action": d.action, "direction": d.direction,
        "confidence": d.confidence, "entry_price": d.entry_price,
        "stop_loss": d.stop_loss, "take_profit": d.take_profit,
        "blocked": False, "block_reasons": [], "breakdown": {},
        "regime": d.regime, "raw_score": 7, "max_score": 9,
    }
    return d


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """
    Module-scoped TestClient using the singleton app.
    Injects a temp-file TradeJournalV2 via set_state() so tests don't
    pollute the shared :memory: connection.
    """
    from journal.journal_v2 import TradeJournalV2
    from api.app import app, set_state

    db_path = str(tmp_path_factory.mktemp("api_smoke") / "smoke.db")
    jrn = TradeJournalV2(db_path=db_path)

    # Seed minimal data
    jrn.save_signal({
        "action": "LONG", "direction": "LONG", "score": 7,
        "max_score": 9, "confidence": 78.0, "regime": "TREND",
        "mtf_aligned": True, "blocked": False, "block_reasons": [],
        "entry_price": 67000.0, "stop_loss": 65800.0, "take_profit": 69400.0,
    }, confidence_breakdown={"smc": 28, "volume": 18, "oi": 16,
                              "funding": 8, "regime": 8})

    jrn.save_market_regime({
        "regime": "TREND", "confidence": 0.88,
        "adx": 35.0, "bb_width": 0.003, "atr_normalized": 0.002,
        "probabilities": {"TREND": 0.88, "RANGE": 0.12},
    })

    jrn.save_funding(0.0001, mark_price=67000.0)
    jrn.save_oi(15000.0, oi_value=1_000_000_000.0, oi_delta_pct=0.012)

    set_state("journal_v2", jrn)
    set_state("latest_decision", _make_decision())
    set_state("latest_context", {"oi_delta": 0.012, "funding_rate": 0.0001,
                                  "regime": "TREND", "regime_conf": 0.88,
                                  "mtf_direction": "LONG", "mtf_aligned": True})

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    # Cleanup
    set_state("journal_v2", None)
    set_state("latest_decision", None)
    set_state("latest_context", None)


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestHealth:

    def test_health_200(self, client):
        assert client.get("/api/health").status_code == 200

    def test_health_ok_true(self, client):
        assert client.get("/api/health").json()["ok"] is True

    def test_health_data_keys(self, client):
        data = client.get("/api/health").json()["data"]
        assert "status" in data and "uptime_s" in data


class TestConfig:

    def test_config_200(self, client):
        assert client.get("/api/config").status_code == 200

    def test_config_has_symbol(self, client):
        data = client.get("/api/config").json()["data"]
        assert "symbol" in data

    def test_config_no_secrets(self, client):
        data = client.get("/api/config").json()["data"]
        for key in ("api_key", "secret", "password"):
            assert key not in data


class TestDecision:

    def test_decision_200(self, client):
        assert client.get("/api/decision").status_code == 200

    def test_decision_has_decision_key(self, client):
        body = client.get("/api/decision").json()["data"]
        assert "decision" in body

    def test_decision_action_long(self, client):
        body = client.get("/api/decision").json()["data"]
        assert body["decision"]["action"] == "LONG"


class TestSignals:

    def test_signals_200(self, client):
        assert client.get("/api/signals").status_code == 200

    def test_signals_is_list(self, client):
        data = client.get("/api/signals").json()["data"]
        assert isinstance(data["signals"], list)

    def test_signals_nonempty(self, client):
        data = client.get("/api/signals").json()["data"]
        assert len(data["signals"]) >= 1


class TestFutures:

    def test_futures_200(self, client):
        assert client.get("/api/futures").status_code == 200

    def test_futures_has_oi_history(self, client):
        data = client.get("/api/futures").json()["data"]
        assert "oi_history" in data and "funding_history" in data

    def test_futures_oi_nonempty(self, client):
        data = client.get("/api/futures").json()["data"]
        assert len(data["oi_history"]) >= 1


class TestRegime:

    def test_regime_200(self, client):
        assert client.get("/api/regime").status_code == 200

    def test_regime_current_present(self, client):
        data = client.get("/api/regime").json()["data"]
        assert "current" in data and "regime" in data["current"]

    def test_regime_current_is_trend(self, client):
        data = client.get("/api/regime").json()["data"]
        assert data["current"]["regime"] == "TREND"


class TestEvents:

    def test_events_200(self, client):
        assert client.get("/api/events").status_code == 200

    def test_events_has_list(self, client):
        data = client.get("/api/events").json()["data"]
        assert "events" in data and isinstance(data["events"], list)


class TestPaper:

    def test_paper_disabled_when_no_engine(self):
        """Fresh client without paper_engine set → enabled=False."""
        from api.app import app, set_state
        set_state("paper_engine", None)
        with TestClient(app, raise_server_exceptions=False) as c:
            body = c.get("/api/paper").json()
        assert body["data"]["enabled"] is False

    def test_paper_trades_graceful_when_no_engine(self):
        """
        Paper trading disabled/unavailable is a normal runtime state, not a
        server error — must be 200 + enabled=False, never 503.
        """
        from api.app import app, set_state
        set_state("paper_engine", None)
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/paper/trades")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is False
        assert data["trades"] is None
        assert data["reason"] == "Paper trading not initialized"

    def test_paper_metrics_graceful_when_no_engine(self):
        """Same contract as /api/paper/trades."""
        from api.app import app, set_state
        set_state("paper_engine", None)
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/paper/metrics")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is False
        assert data["metrics"] is None
        assert data["reason"] == "Paper trading not initialized"


class TestJournal:

    def test_journal_200(self, client):
        assert client.get("/api/journal").status_code == 200

    def test_journal_has_performance(self, client):
        data = client.get("/api/journal").json()["data"]
        assert "performance" in data

    def test_journal_has_daily(self, client):
        data = client.get("/api/journal").json()["data"]
        assert "daily" in data
