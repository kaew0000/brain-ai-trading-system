"""tests/test_capital_manager.py — V16 Phase 2A

All RiskEngine instances here are real (risk.risk_engine.RiskEngine)
constructed against a mocked journal — mirrors tests/test_p1b1_dynamic_risk.py's
own convention, rather than mocking RiskEngine itself, so these tests
exercise the real can_trade()/get_risk_pct()/get_leverage() contract
CapitalManager actually depends on.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from portfolio.capital_manager import CapitalManager
from portfolio.correlation_engine import CorrelationEngine
from portfolio.portfolio_models import (
    CorrelationTier, PortfolioLimits, PortfolioPosition, PositionState,
)
from portfolio.portfolio_state import PortfolioState
from ranking.ranking_models import FactorScore, RankedOpportunity, ScoreBreakdown, ScoreStatus
from risk.risk_engine import RiskEngine

pytestmark = pytest.mark.unit


# ── Shared builders ──────────────────────────────────────────────────────

def make_opportunity(symbol, rank, composite=80.0, coverage=1.0,
                      liquidity=80.0, spread=80.0, atr_pct=0.01,
                      liquidity_status=ScoreStatus.COMPUTED,
                      spread_status=ScoreStatus.COMPUTED) -> RankedOpportunity:
    breakdown = ScoreBreakdown(symbol=symbol, factors={
        "liquidity": FactorScore(name="liquidity", score=liquidity, status=liquidity_status, explanation=""),
        "spread":    FactorScore(name="spread", score=spread, status=spread_status, explanation=""),
        "risk":      FactorScore(name="risk", score=70.0, status=ScoreStatus.COMPUTED,
                                   explanation="", raw_value=atr_pct),
    })
    return RankedOpportunity(
        rank=rank, symbol=symbol, composite_score=composite, breakdown=breakdown,
        explanation="", ranked_at=time.time(), data_age_s=0.0, coverage=coverage,
    )


def make_risk_engine(pnl=0.0, streak=0, blocked=False, block_reason=None) -> RiskEngine:
    journal = MagicMock()
    journal.get_today_pnl.return_value = pnl
    journal.get_consecutive_losses.return_value = streak
    journal.get_daily_stats.return_value = {"total_pnl": pnl, "total_trades": 0, "win_rate": 0.0}
    eng = RiskEngine(journal)
    if blocked:
        eng.can_trade = MagicMock(return_value=(False, block_reason or "blocked for test"))
    return eng


def make_position(symbol, notional=2_000, margin=400):
    return PortfolioPosition(
        symbol=symbol, direction="LONG", entry_price=100, quantity=notional / 100,
        leverage=5, notional=notional, margin_used=margin, unrealized_pnl=0.0,
        state=PositionState.OPEN, opened_at=time.time(),
    )


# ── Risk-gate behavior ───────────────────────────────────────────────────

class TestRiskEngineGate:

    def test_blocked_risk_engine_rejects_everything(self):
        cm = CapitalManager()
        rsk = make_risk_engine(blocked=True, block_reason="daily loss limit exceeded")
        candidates = [make_opportunity("BTCUSDT", 1), make_opportunity("ETHUSDT", 2)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)

        assert decision.blocked is True
        assert decision.block_reason == "daily loss limit exceeded"
        assert decision.selected == []
        assert len(decision.rejected) == 2
        assert all(r.reason.startswith("risk_engine_blocked") for r in decision.rejected)

    def test_not_blocked_proceeds_normally(self):
        cm = CapitalManager()
        rsk = make_risk_engine(blocked=False)
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.blocked is False
        assert len(decision.selected) == 1


# ── Capacity ─────────────────────────────────────────────────────────────

class TestPortfolioCapacity:

    def test_full_portfolio_rejects_all_new_candidates(self):
        limits = PortfolioLimits(max_positions=2)
        cm = CapitalManager(limits=limits)
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))
        state.add_position(make_position("ETHUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("SOLUSDT", 1)]

        decision = cm.decide(candidates, rsk, state, balance=10_000)
        assert decision.selected == []
        assert decision.rejected[0].reason == "portfolio_full"

    def test_partial_capacity_only_fills_open_slots(self):
        limits = PortfolioLimits(max_positions=2, correlation_hard_reject_enabled=False)
        cm = CapitalManager(limits=limits)
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))     # 1 of 2 slots used
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("ETHUSDT", 1, composite=90),
            make_opportunity("SOLUSDT", 2, composite=85),
            make_opportunity("LINKUSDT", 3, composite=80),
        ]
        decision = cm.decide(candidates, rsk, state, balance=10_000)
        assert len(decision.selected) == 1               # only 1 slot was free
        reasons = {r.reason for r in decision.rejected}
        assert "portfolio_full" in reasons

    def test_already_held_symbol_is_rejected_as_duplicate(self):
        cm = CapitalManager()
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1), make_opportunity("ETHUSDT", 2)]

        decision = cm.decide(candidates, rsk, state, balance=10_000)
        btc_rejection = next(r for r in decision.rejected if r.symbol == "BTCUSDT")
        assert btc_rejection.reason == "already_held"
        # ETHUSDT should still be considered (and hard-rejected for correlation
        # with the held BTCUSDT, which is a separate, also-correct outcome)
        assert "BTCUSDT" not in [a.symbol for a in decision.selected]


# ── Correlation ──────────────────────────────────────────────────────────

class TestCorrelation:

    def test_high_correlation_against_held_position_is_hard_rejected(self):
        cm = CapitalManager()   # correlation_hard_reject_enabled=True by default
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("ETHUSDT", 1)]     # HIGH tier vs BTC

        decision = cm.decide(candidates, rsk, state, balance=10_000)
        assert decision.selected == []
        assert decision.rejected[0].reason == "correlation_hard_reject"
        assert decision.rejected[0].details["tier"] == "HIGH"

    def test_hard_reject_can_be_disabled(self):
        limits = PortfolioLimits(correlation_hard_reject_enabled=False)
        cm = CapitalManager(limits=limits)
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("ETHUSDT", 1)]

        decision = cm.decide(candidates, rsk, state, balance=10_000)
        # still selected, but penalized (not rejected) — final_score is reduced
        assert len(decision.selected) == 1
        assert decision.selected[0].correlation_tier == CorrelationTier.HIGH
        assert decision.selected[0].correlation_penalty == 0.5

    def test_lower_correlation_candidate_gets_larger_allocation_despite_lower_composite(self):
        """The scenario from the design smoke test: a lower-composite,
        LOW-correlation candidate should out-allocate a higher-composite,
        MEDIUM-correlation one once BTC is already selected."""
        cm = CapitalManager()
        state = PortfolioState()
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=95, coverage=1.0),
            make_opportunity("SOLUSDT", 2, composite=90, coverage=0.8),   # MEDIUM vs BTC
            make_opportunity("LINKUSDT", 3, composite=85, coverage=0.85),  # LOW vs BTC
        ]
        decision = cm.decide(candidates, rsk, state, balance=10_000)
        by_symbol = {a.symbol: a for a in decision.selected}
        assert by_symbol["LINKUSDT"].final_score > by_symbol["SOLUSDT"].final_score
        assert by_symbol["LINKUSDT"].allocation_pct > by_symbol["SOLUSDT"].allocation_pct

    def test_no_held_or_correlated_selections_gives_low_tier(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected[0].correlation_tier == CorrelationTier.LOW
        assert decision.selected[0].correlation_penalty == 1.0


# ── Eligibility gates ────────────────────────────────────────────────────

class TestEligibilityGates:

    def test_low_liquidity_is_rejected(self):
        limits = PortfolioLimits(min_liquidity_score=30.0)
        cm = CapitalManager(limits=limits)
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, liquidity=10.0)]

        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert decision.rejected[0].reason == "liquidity_below_minimum"

    def test_wide_spread_is_rejected(self):
        limits = PortfolioLimits(min_spread_score=20.0)
        cm = CapitalManager(limits=limits)
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, spread=5.0)]

        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert decision.rejected[0].reason == "spread_below_minimum"

    def test_low_coverage_rejected_when_minimum_configured(self):
        limits = PortfolioLimits(min_coverage=0.5)
        cm = CapitalManager(limits=limits)
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, coverage=0.2)]

        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert decision.rejected[0].reason == "coverage_below_minimum"

    def test_default_min_coverage_is_zero_so_low_coverage_still_passes(self):
        cm = CapitalManager()   # default min_coverage=0.0
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, coverage=0.1)]

        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert len(decision.selected) == 1


# ── Coverage weighting ───────────────────────────────────────────────────

class TestCoverageWeighting:

    def test_higher_coverage_gets_higher_final_score_at_equal_composite(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=80, coverage=1.0),
        ]
        candidates_low_cov = [
            make_opportunity("BTCUSDT", 1, composite=80, coverage=0.3),
        ]
        d_high = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        d_low  = cm.decide(candidates_low_cov, rsk, PortfolioState(), balance=10_000)
        assert d_high.selected[0].final_score > d_low.selected[0].final_score

    def test_coverage_floor_prevents_full_zeroing(self):
        """Even 0 coverage should retain PORTFOLIO_COVERAGE_WEIGHT_FLOOR
        (default 0.5) of the composite score, not collapse to 0."""
        cm = CapitalManager(coverage_weight_floor=0.5)
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=80, coverage=0.0)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected[0].final_score == pytest.approx(80 * 0.5)

    def test_never_use_ai_confidence_or_historical_performance_factors(self):
        """Structural guard: capital_manager.py must not read the
        ai_confidence/historical_performance breakdown factors at all —
        confirms the design decision by construction, not just by not
        testing it. A breakdown missing those keys entirely must still
        produce a normal decision (proves they're never looked up)."""
        cm = CapitalManager()
        rsk = make_risk_engine()
        opp = make_opportunity("BTCUSDT", 1, composite=80, coverage=0.9)
        assert "ai_confidence" not in opp.breakdown.factors
        assert "historical_performance" not in opp.breakdown.factors
        decision = cm.decide([opp], rsk, PortfolioState(), balance=10_000)
        assert len(decision.selected) == 1   # no KeyError, no crash


# ── Volatility / leverage ────────────────────────────────────────────────

class TestVolatilityAndLeverage:

    def test_high_volatility_reduces_leverage_and_risk_pct(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        calm     = [make_opportunity("BTCUSDT", 1, atr_pct=0.005)]   # below threshold
        volatile = [make_opportunity("ETHUSDT", 1, atr_pct=0.05)]    # well above threshold

        d_calm     = cm.decide(calm, rsk, PortfolioState(), balance=10_000)
        d_volatile = cm.decide(volatile, rsk, PortfolioState(), balance=10_000)

        assert d_volatile.selected[0].leverage <= d_calm.selected[0].leverage
        assert d_volatile.selected[0].risk_pct <= d_calm.selected[0].risk_pct

    def test_leverage_capped_by_portfolio_limit_even_when_risk_engine_allows_more(self):
        limits = PortfolioLimits(max_leverage=3)
        cm = CapitalManager(limits=limits)
        rsk = make_risk_engine()   # RiskEngine's own settings.LEVERAGE default is 5
        candidates = [make_opportunity("BTCUSDT", 1, atr_pct=0.005)]  # calm -> no vol scaling
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected[0].leverage <= 3

    def test_missing_atr_data_does_not_crash(self):
        """UNAVAILABLE risk factor (atr_pct=None) must fall back to
        RiskEngine's un-scaled defaults, not raise."""
        cm = CapitalManager()
        rsk = make_risk_engine()
        opp = make_opportunity("BTCUSDT", 1)
        opp.breakdown.factors["risk"] = FactorScore(
            name="risk", score=50.0, status=ScoreStatus.UNAVAILABLE, explanation="", raw_value=None,
        )
        decision = cm.decide([opp], rsk, PortfolioState(), balance=10_000)
        assert len(decision.selected) == 1
        assert decision.selected[0].leverage >= 1


# ── Capital scenarios ────────────────────────────────────────────────────

class TestCapitalScenarios:

    def test_full_capital_single_candidate(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=90)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected[0].capital_amount > 0
        assert decision.total_capital_allocated == decision.selected[0].capital_amount

    def test_never_equal_weighted_unless_scores_are_equal(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=95, coverage=1.0),
            make_opportunity("LINKUSDT", 2, composite=30, coverage=1.0),   # LOW correlation vs BTC
        ]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        pcts = {a.symbol: a.allocation_pct for a in decision.selected}
        # BTC's raw share (95/125=76%) exceeds max_symbol_pct and gets capped
        # to 35%; LINK's raw share (30/125=24%) does not — so this scenario
        # only proves the point if LINK's allocation stays below the cap.
        assert pcts["LINKUSDT"] < cm.limits.max_symbol_pct
        assert pcts["BTCUSDT"] != pytest.approx(pcts["LINKUSDT"])

    def test_equal_scores_get_equal_allocation(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=80, coverage=1.0),
            make_opportunity("XMRUSDT", 2, composite=80, coverage=1.0),   # LOW vs BTC, identical score
        ]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        pcts = {a.symbol: a.allocation_pct for a in decision.selected}
        assert pcts["BTCUSDT"] == pytest.approx(pcts["XMRUSDT"])

    def test_max_symbol_pct_caps_a_dominant_candidate(self):
        limits = PortfolioLimits(max_symbol_pct=0.35, correlation_hard_reject_enabled=False)
        cm = CapitalManager(limits=limits)
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=99, coverage=1.0),
            make_opportunity("ETHUSDT", 2, composite=10, coverage=1.0),
        ]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        btc = next(a for a in decision.selected if a.symbol == "BTCUSDT")
        assert btc.allocation_pct <= 0.35 + 1e-9

    def test_no_capital_when_balance_already_fully_deployed(self):
        limits = PortfolioLimits(max_capital_deployed_pct=0.80)
        cm = CapitalManager(limits=limits)
        state = PortfolioState()
        # already 80% deployed via margin_used
        state.add_position(make_position("ETHUSDT", notional=40_000, margin=8_000))
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]

        decision = cm.decide(candidates, rsk, state, balance=10_000)
        assert decision.selected == [] or decision.selected[0].capital_amount == pytest.approx(0.0, abs=1e-6)

    def test_risk_budget_exhaustion_rejects_or_scales_down_later_candidates(self):
        limits = PortfolioLimits(max_daily_risk_pct=0.001, correlation_hard_reject_enabled=False)  # tiny risk budget
        cm = CapitalManager(limits=limits)
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=90),
            make_opportunity("ETHUSDT", 2, composite=85),
        ]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        # total risk actually allocated must never exceed the configured budget
        assert decision.total_risk_allocated <= 10_000 * 0.001 + 1e-6

    def test_daily_pnl_loss_reduces_remaining_risk_budget(self):
        limits = PortfolioLimits(max_daily_risk_pct=0.03)
        cm = CapitalManager(limits=limits)
        state_fresh = PortfolioState(daily_pnl=0.0)
        state_after_losses = PortfolioState(daily_pnl=-250.0)
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=90)]

        d1 = cm.decide(candidates, rsk, state_fresh, balance=10_000)
        d2 = cm.decide(candidates, rsk, state_after_losses, balance=10_000)
        assert d2.total_risk_allocated <= d1.total_risk_allocated


# ── Allocation ordering / priority ──────────────────────────────────────

class TestAllocationOrdering:

    def test_priority_follows_final_score_descending(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("BTCUSDT", 1, composite=95, coverage=1.0),
            make_opportunity("XMRUSDT", 2, composite=70, coverage=1.0),   # LOW vs BTC
        ]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        priorities = sorted(decision.selected, key=lambda a: a.priority)
        assert priorities[0].symbol == "BTCUSDT"
        assert priorities[0].priority < priorities[1].priority

    def test_decision_includes_explanation_and_reason_per_allocation(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.explanation
        assert decision.selected[0].reason


# ── No candidates / edge cases ───────────────────────────────────────────

class TestEdgeCases:

    def test_empty_candidate_list(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        decision = cm.decide([], rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert decision.blocked is False

    def test_zero_balance_does_not_crash(self):
        cm = CapitalManager()
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = cm.decide(candidates, rsk, PortfolioState(), balance=0.0)
        assert decision.total_capital_allocated == 0.0

    def test_from_settings_constructor_reads_config(self):
        cm = CapitalManager.from_settings()
        assert cm.limits.max_positions >= 1
        assert isinstance(cm.correlation_engine, CorrelationEngine)
