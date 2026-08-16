"""tests/test_ceo_decisions_api.py — V16 Phase 4B Step 3C (Part F):
Dashboard exposure for CEO Decision / Confidence / Consensus / Top
Reasons / Symbol.

Function-scoped fixture (fresh temp-file TradeJournalV2 per test) rather
than sharing tests/test_api.py's module-scoped one — this endpoint's
whole point is reading rows a specific sequence of save_agent_decision()
calls produced, which needs per-test isolation.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture()
def client_and_journal(tmp_path):
    from journal.journal_v2 import TradeJournalV2
    from api.app import app, set_state

    db_path = str(tmp_path / "ceo_decisions_test.db")
    jrn = TradeJournalV2(db_path=db_path)
    set_state("journal_v2", jrn)

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, jrn

    set_state("journal_v2", None)


class TestCeoDecisionsEmpty:

    def test_returns_200_empty_list_when_nothing_journaled(self, client_and_journal):
        """'Dashboard must remain functional when CEO is disabled' —
        CEO_MULTI_SYMBOL_ENABLED=false means nothing was ever journaled;
        this must be a normal empty response, not an error."""
        client, _ = client_and_journal
        resp = client.get("/api/ceo-decisions")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "data": []}


class TestCeoDecisionsPopulated:

    def _seed(self, jrn, symbol="BTCUSDT", action="LONG", confidence=82.5,
              reasons=None, agreement_score=0.75, direction="LONG"):
        jrn.save_agent_decision(
            agent="CEO_AGENT", decision=action, symbol=symbol, score=confidence,
            details={"reasons": reasons or ["SMC bullish", "funding negative"],
                      "agreement_score": agreement_score, "direction": direction},
            execution_lane="LIVE",
        )

    def test_returns_the_seeded_decision(self, client_and_journal):
        client, jrn = client_and_journal
        self._seed(jrn, symbol="BTCUSDT", action="LONG", confidence=82.5)

        data = client.get("/api/ceo-decisions").json()["data"]
        assert len(data) == 1
        assert data[0]["symbol"] == "BTCUSDT"
        assert data[0]["decision"] == "LONG"
        assert data[0]["score"] == 82.5
        assert data[0]["agent"] == "CEO_AGENT"

    def test_top_reasons_and_agreement_score_present_in_details(self, client_and_journal):
        client, jrn = client_and_journal
        self._seed(jrn, reasons=["strong SMC alignment", "low funding risk"], agreement_score=0.9)

        data = client.get("/api/ceo-decisions").json()["data"]
        assert data[0]["details"]["reasons"] == ["strong SMC alignment", "low funding risk"]
        assert data[0]["details"]["agreement_score"] == 0.9

    def test_only_ceo_agent_rows_returned_not_other_agents(self, client_and_journal):
        client, jrn = client_and_journal
        self._seed(jrn, symbol="BTCUSDT")
        jrn.save_agent_decision(agent="SMC_ANALYST", decision="LONG", symbol="BTCUSDT", score=70.0, details={}, execution_lane="LIVE")

        data = client.get("/api/ceo-decisions").json()["data"]
        assert all(row["agent"] == "CEO_AGENT" for row in data)
        assert len(data) == 1

    def test_symbol_filter(self, client_and_journal):
        client, jrn = client_and_journal
        self._seed(jrn, symbol="BTCUSDT")
        self._seed(jrn, symbol="ETHUSDT")

        data = client.get("/api/ceo-decisions?symbol=ETHUSDT").json()["data"]
        assert len(data) == 1
        assert data[0]["symbol"] == "ETHUSDT"

    def test_no_symbol_filter_returns_every_symbol(self, client_and_journal):
        client, jrn = client_and_journal
        self._seed(jrn, symbol="BTCUSDT")
        self._seed(jrn, symbol="ETHUSDT")
        self._seed(jrn, symbol="SOLUSDT")

        data = client.get("/api/ceo-decisions").json()["data"]
        assert {row["symbol"] for row in data} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def test_newest_first(self, client_and_journal):
        client, jrn = client_and_journal
        self._seed(jrn, symbol="BTCUSDT", action="WAIT")
        self._seed(jrn, symbol="BTCUSDT", action="LONG")

        data = client.get("/api/ceo-decisions").json()["data"]
        assert data[0]["decision"] == "LONG"  # most recently saved

    def test_limit_caps_results(self, client_and_journal):
        client, jrn = client_and_journal
        for i in range(5):
            self._seed(jrn, symbol=f"SYM{i}USDT")

        data = client.get("/api/ceo-decisions?limit=2").json()["data"]
        assert len(data) == 2

    def test_includes_wait_and_blocked_decisions_not_only_executed_trades(self, client_and_journal):
        """Every CEO ruling is journaled — including vetoes — matching
        execution/ceo_gated_signal_provider.py's own Part E behavior
        ('journals even when CEO vetoes')."""
        client, jrn = client_and_journal
        self._seed(jrn, symbol="BTCUSDT", action="WAIT", confidence=30.0)
        self._seed(jrn, symbol="ETHUSDT", action="BLOCKED", confidence=0.0)

        data = client.get("/api/ceo-decisions").json()["data"]
        actions = {row["decision"] for row in data}
        assert actions == {"WAIT", "BLOCKED"}
