"""tests/test_portfolio_history_query.py — V16 Phase 2C

Tests for portfolio_history.query_decisions()/count_decisions() only —
get_latest_decisions() itself is already covered by
tests/test_portfolio_history.py and is untouched by this phase.

Same `:memory:` DATABASE_PATH pattern and same "an empty database isn't
reliably reachable, :memory: is a shared cached connection across the
whole test run" caveat as test_portfolio_history.py — tests read back
what they themselves just wrote rather than asserting on absolute
counts.
"""
from __future__ import annotations

import time

import pytest

from portfolio import portfolio_history
from portfolio.portfolio_models import OrchestratedDecision, PortfolioAllocation, CorrelationTier

pytestmark = pytest.mark.unit


def _make_decision(selected=None, sector_exposure=None) -> OrchestratedDecision:
    return OrchestratedDecision(
        generated_at=time.time(), blocked=False, block_reason=None,
        selected=selected or [], rejected=[], replacements=[],
        sector_exposure=sector_exposure or {}, diversification_score=100.0,
        total_capital_allocated=sum(a.capital_amount for a in (selected or [])),
        total_risk_allocated=0.0, portfolio_score=0.0, explanation="test",
    )


def _alloc(symbol="BTCUSDT", capital=500.0) -> PortfolioAllocation:
    return PortfolioAllocation(
        symbol=symbol, priority=1, allocation_pct=0.3, capital_amount=capital,
        risk_pct=0.01, risk_amount=capital * 0.01, leverage=5,
        correlation_tier=CorrelationTier.LOW, correlation_penalty=1.0,
        coverage=1.0, final_score=80.0, reason="test",
    )


class TestQueryDecisions:
    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def test_query_returns_newest_first(self):
        portfolio_history.save_decision(_make_decision([_alloc("AAAUSDT")]), sector_exposure={}, drawdown=0.0)
        time.sleep(0.01)
        portfolio_history.save_decision(_make_decision([_alloc("ZZZUSDT")]), sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.query_decisions(limit=2, offset=0)
        assert rows[0]["data"]["selected"][0]["symbol"] == "ZZZUSDT"

    def test_query_respects_limit(self):
        for i in range(3):
            portfolio_history.save_decision(_make_decision([_alloc(f"SYM{i}USDT")]), sector_exposure={}, drawdown=0.0)
            time.sleep(0.005)
        rows = portfolio_history.query_decisions(limit=1, offset=0)
        assert len(rows) == 1

    def test_query_offset_skips_newest(self):
        portfolio_history.save_decision(_make_decision([_alloc("OFFSETUSDT-A")]), sector_exposure={}, drawdown=0.0)
        time.sleep(0.01)
        portfolio_history.save_decision(_make_decision([_alloc("OFFSETUSDT-B")]), sector_exposure={}, drawdown=0.0)
        newest = portfolio_history.query_decisions(limit=1, offset=0)
        older = portfolio_history.query_decisions(limit=1, offset=1)
        assert newest[0]["data"]["selected"][0]["symbol"] == "OFFSETUSDT-B"
        assert older[0]["data"]["selected"][0]["symbol"] == "OFFSETUSDT-A"

    def test_query_symbol_filter_matches_selected(self):
        marker = "FILTERSELUSDT"
        portfolio_history.save_decision(_make_decision([_alloc(marker)]), sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.query_decisions(limit=50, offset=0, symbol=marker)
        assert any(marker in {a["symbol"] for a in r["data"]["selected"]} for r in rows)

    def test_query_symbol_filter_matches_rejected(self):
        # rejected candidates live in decision.rejected, not .selected —
        # build one directly since _make_decision only takes `selected`.
        from portfolio.portfolio_models import RejectedCandidate
        marker = "FILTERREJUSDT"
        decision = OrchestratedDecision(
            generated_at=time.time(), blocked=False, block_reason=None,
            selected=[], rejected=[RejectedCandidate(symbol=marker, rank=1, reason="test")],
            replacements=[], sector_exposure={}, diversification_score=100.0,
            total_capital_allocated=0.0, total_risk_allocated=0.0,
            portfolio_score=0.0, explanation="test",
        )
        portfolio_history.save_decision(decision, sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.query_decisions(limit=50, offset=0, symbol=marker)
        assert any(marker in {r2["symbol"] for r2 in r["data"]["rejected"]} for r in rows)

    def test_query_symbol_filter_excludes_non_matching(self):
        marker = "EXCLUDEDUSDT"
        portfolio_history.save_decision(_make_decision([_alloc(marker)]), sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.query_decisions(limit=50, offset=0, symbol="TOTALLY-DIFFERENT-SYMBOL")
        symbols_seen = {a["symbol"] for r in rows for a in r["data"]["selected"]}
        assert marker not in symbols_seen

    def test_query_sector_filter_matches(self):
        portfolio_history.save_decision(
            _make_decision([_alloc("SECTORUSDT")], sector_exposure={"UniqueSectorXYZ": 100.0}),
            sector_exposure={"UniqueSectorXYZ": 100.0}, drawdown=0.0,
        )
        rows = portfolio_history.query_decisions(limit=50, offset=0, sector="UniqueSectorXYZ")
        assert any("UniqueSectorXYZ" in r["data"]["sector_exposure"] for r in rows)

    def test_query_sector_filter_excludes_non_matching(self):
        rows = portfolio_history.query_decisions(limit=50, offset=0, sector="SectorThatWasNeverPersisted")
        assert rows == []

    def test_query_no_filters_returns_unfiltered_page(self):
        portfolio_history.save_decision(_make_decision([_alloc("NOFILTERUSDT")]), sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.query_decisions(limit=1, offset=0)
        assert len(rows) == 1

    def test_query_failure_returns_empty_list(self, monkeypatch):
        monkeypatch.setattr(
            "portfolio.portfolio_history.ReadConn",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        )
        assert portfolio_history.query_decisions(limit=10, offset=0) == []

    def test_query_limit_zero_returns_empty(self):
        portfolio_history.save_decision(_make_decision([_alloc("ZEROUSDT")]), sector_exposure={}, drawdown=0.0)
        rows = portfolio_history.query_decisions(limit=0, offset=0)
        assert rows == []


class TestCountDecisions:
    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def test_count_increases_after_save(self):
        before = portfolio_history.count_decisions()
        portfolio_history.save_decision(_make_decision([_alloc("COUNTUSDT")]), sector_exposure={}, drawdown=0.0)
        after = portfolio_history.count_decisions()
        assert after == before + 1

    def test_count_is_int(self):
        assert isinstance(portfolio_history.count_decisions(), int)

    def test_count_failure_returns_zero(self, monkeypatch):
        monkeypatch.setattr(
            "portfolio.portfolio_history.ReadConn",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db unavailable")),
        )
        assert portfolio_history.count_decisions() == 0
