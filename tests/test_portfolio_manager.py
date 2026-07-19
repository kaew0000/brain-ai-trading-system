"""tests/test_portfolio_manager.py — V16 Phase 2B

Same conventions as tests/test_capital_manager.py: real RiskEngine
against a mocked journal (not a mocked RiskEngine), real CorrelationEngine
(so correlation-sensitive scenarios use the actual, tested table rather
than a fake one). `_enforce_sector_limits` / `_evaluate_replacements` are
tested directly in addition to through `decide()` — both are non-trivial
enough that isolated, deterministic coverage of exact threshold math is
worth the extra tests alongside the end-to-end ones.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from portfolio.capital_manager import CapitalManager
from portfolio.portfolio_manager import PortfolioManager
from portfolio.portfolio_models import (
    CorrelationTier, PortfolioAllocation, PortfolioLimits, PortfolioPosition, PositionState,
)
from portfolio.portfolio_state import PortfolioState
from portfolio.sector_engine import SectorEngine
from ranking.ranking_models import FactorScore, RankedOpportunity, ScoreBreakdown, ScoreStatus
from risk.risk_engine import RiskEngine

pytestmark = pytest.mark.unit


# ── Shared builders (mirrors tests/test_capital_manager.py's own) ───────────

def make_opportunity(symbol, rank, composite=80.0, coverage=1.0,
                      liquidity=80.0, spread=80.0, atr_pct=0.01) -> RankedOpportunity:
    breakdown = ScoreBreakdown(symbol=symbol, factors={
        "liquidity": FactorScore(name="liquidity", score=liquidity, status=ScoreStatus.COMPUTED, explanation=""),
        "spread":    FactorScore(name="spread", score=spread, status=ScoreStatus.COMPUTED, explanation=""),
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


def make_position(symbol, notional=2_000, margin=400) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol, direction="LONG", entry_price=100, quantity=notional / 100,
        leverage=5, notional=notional, margin_used=margin, unrealized_pnl=0.0,
        state=PositionState.OPEN, opened_at=time.time(),
    )


def make_allocation(symbol, priority=1, capital=1000.0, leverage=5,
                     final_score=80.0, allocation_pct=0.3) -> PortfolioAllocation:
    return PortfolioAllocation(
        symbol=symbol, priority=priority, allocation_pct=allocation_pct,
        capital_amount=capital, risk_pct=0.01, risk_amount=capital * 0.01,
        leverage=leverage, correlation_tier=CorrelationTier.LOW, correlation_penalty=1.0,
        coverage=1.0, final_score=final_score, reason="test",
    )


def no_correlation_limits(**kwargs) -> PortfolioLimits:
    """Most sector/replacement/cooldown tests don't care about correlation
    penalties at all — disabling hard-reject keeps them from being
    incidentally sensitive to config/correlation_table.py's specific tiers."""
    kwargs.setdefault("correlation_hard_reject_enabled", False)
    return PortfolioLimits(**kwargs)


# ── Sector exposure enforcement ──────────────────────────────────────────

class TestSectorLimitsEnforcement:

    def test_rejects_allocation_that_would_exceed_sector_cap(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT", notional=4990, margin=4990))   # Layer1, cap = 5000 @ balance 10k
        allocs = [make_allocation("ETHUSDT", priority=1, capital=1000)]            # 4990 + 1000 > 5000
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=[])
        assert kept == []
        assert len(rejected) == 1
        assert rejected[0].reason == "sector_exposure_exceeded"
        assert rejected[0].details["sector"] == "Layer1"

    def test_allows_allocation_within_sector_cap(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        allocs = [make_allocation("BTCUSDT", priority=1, capital=100)]             # well under 5000
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=[])
        assert len(kept) == 1
        assert rejected == []

    def test_priority_order_first_kept_second_rejected_same_sector(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        allocs = [
            make_allocation("BTCUSDT", priority=1, capital=4000),   # fits under 5000
            make_allocation("ETHUSDT", priority=2, capital=2000),   # cumulative 6000 > 5000
        ]
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=[])
        assert [a.symbol for a in kept] == ["BTCUSDT"]
        assert [r.symbol for r in rejected] == ["ETHUSDT"]

    def test_different_sectors_do_not_share_a_cap(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        allocs = [
            make_allocation("BTCUSDT", priority=1, capital=4000),   # Layer1
            make_allocation("UNIUSDT", priority=2, capital=4000),   # DeFi, own cap
        ]
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=[])
        assert {a.symbol for a in kept} == {"BTCUSDT", "UNIUSDT"}
        assert rejected == []

    def test_zero_balance_skips_enforcement(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        allocs = [make_allocation("BTCUSDT", priority=1, capital=100_000)]
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=0.0, candidates=[])
        assert kept == allocs
        assert rejected == []

    def test_rejected_candidate_carries_original_rank_when_available(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT", notional=4990, margin=4990))
        allocs = [make_allocation("ETHUSDT", priority=1, capital=1000)]
        candidates = [make_opportunity("ETHUSDT", rank=7)]
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=candidates)
        assert rejected[0].rank == 7

    def test_existing_holdings_counted_before_new_picks(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT", notional=6000, margin=6000))   # already over the 5000 cap alone
        allocs = [make_allocation("ETHUSDT", priority=1, capital=10)]              # tiny addition, still Layer1
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=[])
        assert kept == []
        assert rejected[0].reason == "sector_exposure_exceeded"

    def test_uses_capital_not_leveraged_notional(self):
        """The bug this guards against: comparing leveraged notional
        against an unleveraged balance-based cap would make even one
        ordinary position at normal leverage look like it blew the cap.
        Capital (margin), not notional*leverage, is what's bounded by
        `balance` in the first place — see SectorEngine.capital_by_sector's
        docstring."""
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits(max_sector_pct=0.5)))
        state = PortfolioState()
        # capital=1000 but leverage=10 -> notional would be 10,000 (> the
        # 5000 cap) if this were (wrongly) leverage-scaled; capital alone
        # (1000) is comfortably under the cap and must be kept.
        allocs = [make_allocation("BTCUSDT", priority=1, capital=1000, leverage=10)]
        kept, rejected = pm._enforce_sector_limits(allocs, state, balance=10_000, candidates=[])
        assert len(kept) == 1
        assert rejected == []


# ── Replacement logic ─────────────────────────────────────────────────────

class TestReplacementLogic:

    def test_no_replacement_when_portfolio_not_full(self):
        limits = no_correlation_limits(max_positions=5)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm)
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))   # 1 of 5 slots used
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=50), make_opportunity("UNIUSDT", 2, composite=99)]
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert replacements == []

    def test_no_replacement_when_no_held_positions(self):
        limits = no_correlation_limits(max_positions=0)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm)
        state = PortfolioState()
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert replacements == []

    def test_replacement_proposed_when_challenger_clears_threshold(self):
        limits = no_correlation_limits(max_positions=1)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm, replacement_threshold_pct=0.15)
        state = PortfolioState()
        state.add_position(make_position("XMRUSDT"))   # weak held position (Privacy sector)
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("XMRUSDT", 1, composite=20),   # weak, still in ranked universe
            make_opportunity("UNIUSDT", 2, composite=95),   # strong challenger (LOW corr vs XMR)
        ]
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        assert "UNIUSDT" not in [a.symbol for a in base_decision.selected]   # portfolio was full

        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert len(replacements) == 1
        assert replacements[0].incoming_symbol == "UNIUSDT"
        assert replacements[0].outgoing_symbol == "XMRUSDT"
        assert replacements[0].outgoing_score == pytest.approx(20.0)
        assert replacements[0].reason

    def test_no_replacement_when_challenger_below_threshold(self):
        limits = no_correlation_limits(max_positions=1)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm, replacement_threshold_pct=0.15)
        state = PortfolioState()
        state.add_position(make_position("XMRUSDT"))
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("XMRUSDT", 1, composite=80),
            make_opportunity("UNIUSDT", 2, composite=82),   # only marginally better
        ]
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert replacements == []

    def test_held_symbol_missing_from_ranked_universe_scores_zero(self):
        limits = no_correlation_limits(max_positions=1)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm)
        state = PortfolioState()
        state.add_position(make_position("XMRUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("UNIUSDT", 1, composite=50)]   # XMRUSDT absent entirely this cycle
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert len(replacements) == 1
        assert replacements[0].outgoing_symbol == "XMRUSDT"
        assert replacements[0].outgoing_score == 0.0

    def test_min_hold_protection_blocks_replacement(self):
        limits = no_correlation_limits(max_positions=1)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm)
        state = PortfolioState()
        state.add_position(make_position("XMRUSDT"))
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("XMRUSDT", 1, composite=5),
            make_opportunity("UNIUSDT", 2, composite=99),
        ]
        now = time.time()
        pm._protected_until["XMRUSDT"] = now + 1000   # still protected
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, now)
        assert replacements == []

    def test_no_replacement_when_challenger_also_correlation_hard_rejected(self):
        limits = PortfolioLimits(max_positions=1)   # correlation_hard_reject_enabled=True (default)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm)
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("ETHUSDT", 1, composite=99)]   # HIGH correlation vs BTC
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert replacements == []

    def test_at_most_one_replacement_proposed_per_cycle(self):
        limits = no_correlation_limits(max_positions=1)
        cm = CapitalManager(limits=limits)
        pm = PortfolioManager(capital_manager=cm)
        state = PortfolioState()
        state.add_position(make_position("XMRUSDT"))
        rsk = make_risk_engine()
        candidates = [
            make_opportunity("XMRUSDT", 1, composite=5),
            make_opportunity("UNIUSDT", 2, composite=99),
            make_opportunity("ONDOUSDT", 3, composite=98),
        ]
        base_decision = cm.decide(candidates, rsk, state, balance=10_000)
        replacements = pm._evaluate_replacements(candidates, base_decision, state, rsk, 10_000, time.time())
        assert len(replacements) <= 1


# ── decide() end-to-end ───────────────────────────────────────────────────

class TestDecideIntegration:

    def test_blocked_by_risk_engine_returns_blocked_orchestrated_decision(self):
        pm = PortfolioManager()
        rsk = make_risk_engine(blocked=True, block_reason="daily loss limit exceeded")
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.blocked is True
        assert decision.block_reason == "daily loss limit exceeded"
        assert decision.selected == []
        assert decision.replacements == []

    def test_normal_decision_includes_sector_and_diversification(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits()))
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=90)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.blocked is False
        assert len(decision.selected) == 1
        assert "Layer1" in decision.sector_exposure
        assert 0.0 <= decision.diversification_score <= 100.0
        assert decision.portfolio_score > 0

    def test_cooldown_symbol_excluded_from_selection(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits()))
        pm.notify_position_closed("BTCUSDT")   # registered "now" -> still cooling down
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=99)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert any(r.reason == "in_cooldown" for r in decision.rejected)

    def test_expired_cooldown_allows_selection(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits()))
        pm.notify_position_closed("BTCUSDT", now=0.0)   # ancient timestamp -> expired
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=99)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert "BTCUSDT" in [a.symbol for a in decision.selected]

    def test_held_symbol_never_filtered_by_cooldown(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits()))
        state = PortfolioState()
        state.add_position(make_position("BTCUSDT"))
        pm._cooldowns["BTCUSDT"] = time.time() + 9999   # contrived stale entry for an already-held symbol
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = pm.decide(candidates, rsk, state, balance=10_000)
        reasons = {r.symbol: r.reason for r in decision.rejected}
        assert reasons.get("BTCUSDT") == "already_held"   # not "in_cooldown"

    def test_replacement_registers_cooldown_and_protection(self):
        limits = no_correlation_limits(max_positions=1)
        pm = PortfolioManager(capital_manager=CapitalManager(limits=limits))
        state = PortfolioState()
        state.add_position(make_position("XMRUSDT"))
        rsk = make_risk_engine()
        candidates = [make_opportunity("XMRUSDT", 1, composite=5), make_opportunity("UNIUSDT", 2, composite=99)]
        decision = pm.decide(candidates, rsk, state, balance=10_000)
        assert len(decision.replacements) == 1
        assert pm.is_in_cooldown("XMRUSDT")
        assert "UNIUSDT" in pm._protected_until

    def test_sector_rejection_surfaces_in_decision_rejected_list(self):
        limits = no_correlation_limits(max_sector_pct=0.001)   # near-zero cap forces rejection
        pm = PortfolioManager(capital_manager=CapitalManager(limits=limits))
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=90)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert any(r.reason == "sector_exposure_exceeded" for r in decision.rejected)

    def test_explanation_non_empty(self):
        pm = PortfolioManager()
        rsk = make_risk_engine()
        decision = pm.decide([], rsk, PortfolioState(), balance=10_000)
        assert decision.explanation

    def test_to_dict_shape(self):
        pm = PortfolioManager(capital_manager=CapitalManager(limits=no_correlation_limits()))
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1, composite=90)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=10_000)
        d = decision.to_dict()
        for key in ("generated_at", "blocked", "block_reason", "selected", "rejected",
                    "replacements", "sector_exposure", "diversification_score",
                    "total_capital_allocated", "total_risk_allocated", "portfolio_score", "explanation"):
            assert key in d

    def test_from_settings_constructor(self):
        pm = PortfolioManager.from_settings()
        assert pm.limits.max_positions >= 1
        assert isinstance(pm.sector_engine, SectorEngine)
        assert isinstance(pm.capital_manager, CapitalManager)

    def test_status_reports_active_cooldowns(self):
        pm = PortfolioManager()
        pm.notify_position_closed("BTCUSDT")
        status = pm.status()
        assert "BTCUSDT" in status["active_cooldowns"]

    def test_status_does_not_report_expired_cooldowns(self):
        pm = PortfolioManager()
        pm.notify_position_closed("BTCUSDT", now=0.0)   # already expired
        status = pm.status()
        assert "BTCUSDT" not in status["active_cooldowns"]

    def test_empty_candidates_does_not_crash(self):
        pm = PortfolioManager()
        rsk = make_risk_engine()
        decision = pm.decide([], rsk, PortfolioState(), balance=10_000)
        assert decision.selected == []
        assert decision.blocked is False

    def test_zero_balance_does_not_crash(self):
        pm = PortfolioManager()
        rsk = make_risk_engine()
        candidates = [make_opportunity("BTCUSDT", 1)]
        decision = pm.decide(candidates, rsk, PortfolioState(), balance=0.0)
        assert decision.total_capital_allocated == 0.0

    def test_portfolio_manager_never_imports_execution_modules(self):
        """PortfolioManager MUST NOT execute trades — a light structural
        guard against accidental scope creep, not a substitute for the
        module docstring's own explanation of the boundary. Uses ast to
        check actual import statements, not a raw substring search (the
        module docstring itself discusses the execution/ boundary in
        prose, which would false-positive a naive text search)."""
        import ast
        import portfolio.portfolio_manager as mod
        tree = ast.parse(open(mod.__file__).read())
        imported_roots = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(n.name.split(".")[0] for n in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".")[0])
        assert "execution" not in imported_roots
        assert "data" not in imported_roots


# ── Cooldown helper methods ───────────────────────────────────────────────

class TestCooldownHelpers:

    def test_is_in_cooldown_false_initially(self):
        pm = PortfolioManager()
        assert pm.is_in_cooldown("BTCUSDT") is False

    def test_notify_position_closed_registers_cooldown(self):
        pm = PortfolioManager()
        pm.notify_position_closed("BTCUSDT")
        assert pm.is_in_cooldown("BTCUSDT") is True

    def test_cooldown_respects_custom_duration(self):
        pm = PortfolioManager(cooldown_seconds=100)
        now = 1_000_000.0
        pm.notify_position_closed("BTCUSDT", now=now)
        assert pm.is_in_cooldown("BTCUSDT", now=now + 50) is True
        assert pm.is_in_cooldown("BTCUSDT", now=now + 150) is False


# ── Persistence ────────────────────────────────────────────────────────────

class TestPersistence:

    def test_persist_failure_does_not_propagate(self, monkeypatch):
        monkeypatch.setattr(
            "portfolio.portfolio_manager.portfolio_history.save_decision",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        pm = PortfolioManager()
        rsk = make_risk_engine()
        decision = pm.decide([], rsk, PortfolioState(), balance=10_000)
        assert decision.blocked is False   # decide() must still return successfully

    def test_persist_called_once_per_decide(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "portfolio.portfolio_manager.portfolio_history.save_decision",
            lambda decision, sector_exposure, drawdown: calls.append((decision, sector_exposure, drawdown)),
        )
        pm = PortfolioManager()
        rsk = make_risk_engine()
        pm.decide([], rsk, PortfolioState(), balance=10_000)
        assert len(calls) == 1
