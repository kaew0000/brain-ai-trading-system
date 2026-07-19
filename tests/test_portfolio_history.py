"""tests/test_portfolio_history.py — V16 Phase 2B

Persistence tests use the same `:memory:` DATABASE_PATH pattern as
tests/test_opportunity_ranker.py::TestRankingHistory. Note: `:memory:`
is a shared cached connection across every test in the run (see
database/db.py's module docstring) — same reasoning as
test_opportunity_ranker.py's own note, an "empty database" isn't a
reliably reachable state here, so these tests always read back via
ORDER BY decided_at DESC / get_latest_decisions(limit=1) rather than
counting total rows.
"""
from __future__ import annotations

import time

import pytest

from portfolio import portfolio_history
from portfolio.portfolio_models import OrchestratedDecision, PortfolioAllocation, CorrelationTier

pytestmark = pytest.mark.unit


def _make_decision(blocked=False, block_reason=None, selected=None, portfolio_score=0.0,
                    diversification_score=100.0) -> OrchestratedDecision:
    return OrchestratedDecision(
        generated_at=time.time(), blocked=blocked, block_reason=block_reason,
        selected=selected or [], rejected=[], replacements=[],
        sector_exposure={"Layer1": 1000.0}, diversification_score=diversification_score,
        total_capital_allocated=sum(a.capital_amount for a in (selected or [])),
        total_risk_allocated=0.0, portfolio_score=portfolio_score,
        explanation="test decision",
    )


def _make_allocation(symbol="BTCUSDT", capital=500.0, final_score=80.0) -> PortfolioAllocation:
    return PortfolioAllocation(
        symbol=symbol, priority=1, allocation_pct=0.3, capital_amount=capital,
        risk_pct=0.01, risk_amount=capital * 0.01, leverage=5,
        correlation_tier=CorrelationTier.LOW, correlation_penalty=1.0,
        coverage=1.0, final_score=final_score, reason="test",
    )


class TestPortfolioHistory:

    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def test_save_and_get_latest_roundtrip(self):
        decision = _make_decision(selected=[_make_allocation()], portfolio_score=80.0)
        portfolio_history.save_decision(decision, sector_exposure={"Layer1": 1000.0}, drawdown=0.05)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert len(rows) == 1
        assert rows[0]["data"]["selected"][0]["symbol"] == "BTCUSDT"

    def test_get_latest_returns_newest_first(self):
        d1 = _make_decision(selected=[_make_allocation("AAAUSDT")])
        d2 = _make_decision(selected=[_make_allocation("ZZZUSDT")])
        portfolio_history.save_decision(d1, sector_exposure={}, drawdown=0.0)
        time.sleep(0.01)
        portfolio_history.save_decision(d2, sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert rows[0]["data"]["selected"][0]["symbol"] == "ZZZUSDT"

    def test_blocked_decision_persists_correctly(self):
        decision = _make_decision(blocked=True, block_reason="daily loss limit exceeded")
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.1)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert rows[0]["blocked"] is True
        assert rows[0]["block_reason"] == "daily loss limit exceeded"

    def test_selected_and_rejected_counts_persisted(self):
        decision = _make_decision(selected=[_make_allocation("BTCUSDT"), _make_allocation("ETHUSDT")])
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert rows[0]["selected_count"] == 2

    def test_portfolio_score_and_diversification_persisted(self):
        decision = _make_decision(portfolio_score=72.5, diversification_score=64.0)
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert rows[0]["portfolio_score"] == pytest.approx(72.5)
        assert rows[0]["diversification_score"] == pytest.approx(64.0)

    def test_drawdown_persisted(self):
        decision = _make_decision()
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.23)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert rows[0]["drawdown"] == pytest.approx(0.23)

    def test_sector_exposure_persisted_in_data_blob(self):
        decision = _make_decision()
        portfolio_history.save_decision(decision, sector_exposure={"Layer1": 4000.0, "DeFi": 1000.0}, drawdown=0.0)
        rows = portfolio_history.get_latest_decisions(limit=1)
        assert rows[0]["data"]["sector_exposure"] == {"Layer1": 4000.0, "DeFi": 1000.0}

    def test_get_latest_decisions_limit_zero_returns_empty_list(self):
        decision = _make_decision()
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.get_latest_decisions(limit=0)
        assert rows == []

    def test_save_decision_failure_is_non_fatal(self, monkeypatch):
        # ManagedConn raising must not propagate out of save_decision.
        monkeypatch.setattr(
            "portfolio.portfolio_history.ManagedConn",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        )
        decision = _make_decision()
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.0)   # must not raise

    def test_get_latest_decisions_failure_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "portfolio.portfolio_history.ReadConn",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        )
        assert portfolio_history.get_latest_decisions(limit=1) == []
