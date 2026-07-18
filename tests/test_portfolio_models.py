"""tests/test_portfolio_models.py — V16 Phase 2A"""
from __future__ import annotations

import time

import pytest

from portfolio.portfolio_models import (
    CorrelationTier, PortfolioAllocation, PortfolioDecision, PortfolioLimits,
    PortfolioPosition, PositionState, RejectedCandidate, RiskBudget,
)

pytestmark = pytest.mark.unit


class TestPortfolioLimitsDefaults:

    def test_defaults_are_conservative(self):
        limits = PortfolioLimits()
        assert 0 < limits.max_symbol_pct <= 1.0
        assert 0 < limits.max_capital_deployed_pct <= 1.0
        assert limits.max_positions >= 1
        assert limits.correlation_hard_reject_tier == CorrelationTier.HIGH

    def test_is_frozen(self):
        limits = PortfolioLimits()
        with pytest.raises(Exception):
            limits.max_positions = 99


class TestRiskBudget:

    def test_remaining_daily_risk(self):
        b = RiskBudget(balance=10_000, max_daily_risk_usdt=300, risk_used_today_usdt=100,
                        max_account_risk_usdt=1000, risk_used_open_usdt=0)
        assert b.remaining_daily_risk_usdt == 200

    def test_remaining_never_negative(self):
        b = RiskBudget(balance=10_000, max_daily_risk_usdt=300, risk_used_today_usdt=500,
                        max_account_risk_usdt=1000, risk_used_open_usdt=0)
        assert b.remaining_daily_risk_usdt == 0.0

    def test_remaining_risk_is_the_tighter_of_the_two_budgets(self):
        b = RiskBudget(balance=10_000, max_daily_risk_usdt=300, risk_used_today_usdt=0,
                        max_account_risk_usdt=1000, risk_used_open_usdt=950)
        # daily budget has 300 remaining, account budget has only 50 remaining
        assert b.remaining_risk_usdt == 50
        assert b.remaining_account_risk_usdt == 50

    def test_is_frozen(self):
        b = RiskBudget(balance=1, max_daily_risk_usdt=1, risk_used_today_usdt=0,
                        max_account_risk_usdt=1, risk_used_open_usdt=0)
        with pytest.raises(Exception):
            b.balance = 2


class TestPortfolioPosition:

    def test_to_dict_serializes_enum(self):
        p = PortfolioPosition(
            symbol="BTCUSDT", direction="LONG", entry_price=50_000, quantity=0.1,
            leverage=5, notional=5_000, margin_used=1_000, unrealized_pnl=0.0,
            state=PositionState.OPEN, opened_at=time.time(),
        )
        d = p.to_dict()
        assert d["state"] == "OPEN"
        assert isinstance(d["state"], str)

    def test_sector_defaults_none(self):
        p = PortfolioPosition(
            symbol="BTCUSDT", direction="LONG", entry_price=1, quantity=1,
            leverage=1, notional=1, margin_used=1, unrealized_pnl=0,
            state=PositionState.OPEN, opened_at=0.0,
        )
        assert p.sector is None

    def test_is_frozen(self):
        p = PortfolioPosition(
            symbol="BTCUSDT", direction="LONG", entry_price=1, quantity=1,
            leverage=1, notional=1, margin_used=1, unrealized_pnl=0,
            state=PositionState.OPEN, opened_at=0.0,
        )
        with pytest.raises(Exception):
            p.entry_price = 2


class TestPortfolioDecision:

    def test_to_dict_round_trips_selected_and_rejected(self):
        d = PortfolioDecision(
            generated_at=time.time(), blocked=False, block_reason=None,
            selected=[PortfolioAllocation(
                symbol="BTCUSDT", priority=1, allocation_pct=0.3, capital_amount=300,
                risk_pct=0.01, risk_amount=3, leverage=5,
                correlation_tier=CorrelationTier.LOW, correlation_penalty=1.0,
                coverage=0.9, final_score=80.0, reason="test",
            )],
            rejected=[RejectedCandidate(symbol="ETHUSDT", rank=2, reason="correlation_hard_reject")],
        )
        out = d.to_dict()
        assert out["selected"][0]["symbol"] == "BTCUSDT"
        assert out["selected"][0]["correlation_tier"] == "LOW"          # enum serialized to str
        assert out["rejected"][0]["reason"] == "correlation_hard_reject"

    def test_blocked_decision_has_no_selections(self):
        d = PortfolioDecision(generated_at=time.time(), blocked=True,
                               block_reason="daily loss limit")
        assert d.selected == []
        assert d.blocked is True
