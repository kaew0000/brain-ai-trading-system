"""tests/test_execution_scheduler.py — V16 Phase 2F: Execution Scheduler
+ Multi-Symbol Signals
"""
from __future__ import annotations

import time

import pytest

from events.event_bus import reset_event_bus
from execution.execution_orchestrator import ExecutionOrchestrator, ExecutionSignal
from execution.execution_scheduler import ExecutionScheduler
from execution.execution_state import reset_execution_state
from portfolio.portfolio_models import (
    CorrelationTier,
    OrchestratedDecision,
    PortfolioAllocation,
)
from ranking.ranking_models import RankedOpportunity, ScoreBreakdown

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_event_bus():
    reset_event_bus()
    yield
    reset_event_bus()


# ── Shared fakes ─────────────────────────────────────────────────────────

def make_opportunity(symbol="BTCUSDT", rank=1, score=80.0) -> RankedOpportunity:
    return RankedOpportunity(
        rank=rank, symbol=symbol, composite_score=score,
        breakdown=ScoreBreakdown(symbol=symbol), explanation="test",
        ranked_at=1.0, data_age_s=1.0,
    )


def make_allocation(symbol="BTCUSDT") -> PortfolioAllocation:
    return PortfolioAllocation(
        symbol=symbol, priority=1, allocation_pct=0.2, capital_amount=100.0,
        risk_pct=0.01, risk_amount=1.0, leverage=3, correlation_tier=CorrelationTier.LOW,
        correlation_penalty=1.0, coverage=1.0, final_score=80.0, reason="t",
    )


class FakeRanker:
    def __init__(self, opportunities=None):
        self.opportunities = opportunities if opportunities is not None else [make_opportunity()]
        self.call_count = 0

    def rank(self):
        self.call_count += 1
        return list(self.opportunities)


class FakePortfolioManager:
    """Mirrors PortfolioManager.decide()'s real signature exactly."""

    def __init__(self, decision_fn=None):
        self.decision_fn = decision_fn or (
            lambda candidates, risk_engine, state, balance: OrchestratedDecision(
                generated_at=time.time(), blocked=False, block_reason=None,
                selected=[make_allocation(c.symbol) for c in candidates],
            )
        )
        self.calls = []

    def decide(self, candidates, risk_engine, state, balance):
        self.calls.append((candidates, risk_engine, state, balance))
        return self.decision_fn(candidates, risk_engine, state, balance)

    def notify_position_closed(self, symbol):
        pass


class FakeExecutionEngine:
    def execute_trade(self, **kwargs):
        return {"success": True, "entry_price": 100.0, "quantity": 1.0, "error": None}


class FakeDataProvider:
    def __init__(self, balance=10_000.0):
        self.balance = balance
        self.balance_call_count = 0

    def get_account_balance(self):
        self.balance_call_count += 1
        return self.balance


def make_scheduler(ranker=None, pm=None, dp=None, orch=None, **kwargs):
    ranker = ranker or FakeRanker()
    pm = pm or FakePortfolioManager()
    dp = dp or FakeDataProvider()
    if orch is None:
        orch = ExecutionOrchestrator(
            execution_engine=FakeExecutionEngine(), portfolio_manager=pm,
            signal_provider=lambda s: ExecutionSignal(1, 100.0, 90.0, 110.0),
            state=reset_execution_state(),
        )
    kwargs.setdefault("interval_seconds", 1)
    kwargs.setdefault("candidate_limit", 20)
    return ExecutionScheduler(
        opportunity_ranker=ranker, portfolio_manager=pm, risk_engine=object(),
        execution_orchestrator=orch, data_provider=dp,
        **kwargs,
    )


class TestRunOnceHappyPath:

    def test_successful_cycle_returns_batch_with_completed_allocation(self):
        sched = make_scheduler()
        batch = sched.run_once()
        assert batch is not None
        assert batch.summary().completed == 1
        assert sched.last_error is None
        assert sched.cycle_count == 1

    def test_position_recorded_in_owned_portfolio_state(self):
        sched = make_scheduler()
        sched.run_once()
        assert sched.portfolio_state.has_position("BTCUSDT")

    def test_balance_fetched_from_data_provider_each_cycle(self):
        dp = FakeDataProvider(balance=5000.0)
        sched = make_scheduler(dp=dp)
        sched.run_once()
        assert dp.balance_call_count == 1

    def test_candidates_passed_through_to_portfolio_manager(self):
        ranker = FakeRanker([make_opportunity("BTCUSDT"), make_opportunity("ETHUSDT", rank=2)])
        pm = FakePortfolioManager()
        sched = make_scheduler(ranker=ranker, pm=pm)
        sched.run_once()
        candidates_seen = pm.calls[0][0]
        assert [c.symbol for c in candidates_seen] == ["BTCUSDT", "ETHUSDT"]


class TestNoCandidates:

    def test_empty_ranker_output_is_a_clean_noop(self):
        sched = make_scheduler(ranker=FakeRanker([]))
        batch = sched.run_once()
        assert batch is None
        assert sched.last_error is None  # not an error — just nothing to do


class TestCandidateLimit:

    def test_limit_truncates_the_candidate_list(self):
        opps = [make_opportunity(f"SYM{i}USDT", rank=i) for i in range(10)]
        ranker = FakeRanker(opps)
        pm = FakePortfolioManager()
        sched = make_scheduler(ranker=ranker, pm=pm, candidate_limit=3)
        sched.run_once()
        assert len(pm.calls[0][0]) == 3

    def test_zero_or_none_limit_means_no_truncation(self):
        opps = [make_opportunity(f"SYM{i}USDT", rank=i) for i in range(5)]
        ranker = FakeRanker(opps)
        pm = FakePortfolioManager()
        sched = make_scheduler(ranker=ranker, pm=pm, candidate_limit=0)
        sched.run_once()
        assert len(pm.calls[0][0]) == 5


class TestBlockedDecision:

    def test_blocked_decision_executes_nothing(self):
        def blocked_decide(candidates, risk_engine, state, balance):
            return OrchestratedDecision(generated_at=time.time(), blocked=True, block_reason="daily_loss_limit")

        pm = FakePortfolioManager(decision_fn=blocked_decide)
        sched = make_scheduler(pm=pm)
        batch = sched.run_once()
        assert batch is None
        assert sched.last_error is None  # blocked is a normal outcome, not a failure


class TestErrorHandling:

    def test_ranker_exception_is_caught_and_recorded(self):
        class RaisingRanker:
            def rank(self):
                raise ConnectionError("simulated scanner outage")

        sched = make_scheduler(ranker=RaisingRanker())
        batch = sched.run_once()
        assert batch is None
        assert "simulated scanner outage" in sched.last_error

    def test_data_provider_exception_is_caught(self):
        class RaisingDataProvider:
            def get_account_balance(self):
                raise ConnectionError("balance fetch failed")

        sched = make_scheduler(dp=RaisingDataProvider())
        batch = sched.run_once()
        assert batch is None
        assert sched.last_error is not None

    def test_error_does_not_prevent_next_cycle_from_succeeding(self):
        """The scheduler thread must survive one bad cycle and keep
        running — this is what actually matters for a long-lived
        background thread, not just that run_once() doesn't raise."""
        calls = {"n": 0}

        class FlakyRanker:
            def rank(self):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise ConnectionError("transient")
                return [make_opportunity()]

        sched = make_scheduler(ranker=FlakyRanker())
        first = sched.run_once()
        assert first is None
        assert sched.last_error is not None  # must check before the next run_once() resets it

        second = sched.run_once()
        assert second is not None
        assert sched.last_error is None  # cleared on the successful cycle

    def test_last_error_cleared_at_start_of_each_cycle(self):
        sched = make_scheduler(ranker=FakeRanker([]))
        # Force an error on cycle 1
        class OnceRaising:
            def __init__(self):
                self.n = 0
            def rank(self):
                self.n += 1
                if self.n == 1:
                    raise RuntimeError("boom")
                return []
        sched2 = make_scheduler(ranker=OnceRaising())
        sched2.run_once()
        assert sched2.last_error is not None
        sched2.run_once()  # no candidates, but no error this time
        assert sched2.last_error is None


class TestLifecycle:

    def test_not_running_before_start(self):
        sched = make_scheduler()
        assert sched.is_running() is False

    def test_running_after_start_then_stopped_after_stop(self):
        sched = make_scheduler(interval_seconds=1)
        sched.start()
        time.sleep(0.2)
        assert sched.is_running() is True
        sched.stop()
        assert sched.is_running() is False

    def test_start_runs_at_least_one_cycle(self):
        sched = make_scheduler(interval_seconds=1)
        sched.start()
        time.sleep(0.2)
        sched.stop()
        assert sched.cycle_count >= 1

    def test_double_start_is_a_safe_noop(self):
        sched = make_scheduler(interval_seconds=1)
        sched.start()
        time.sleep(0.1)
        sched.start()  # must not raise or spawn a second thread
        assert sched.is_running() is True
        sched.stop()

    def test_stop_before_start_is_safe(self):
        sched = make_scheduler()
        sched.stop()  # must not raise
        assert sched.is_running() is False


class TestObservability:

    def test_to_dict_reflects_state(self):
        sched = make_scheduler()
        sched.run_once()
        d = sched.to_dict()
        assert d["cycle_count"] == 1
        assert d["running"] is False
        assert d["tracked_positions"] == 1
        assert d["interval_seconds"] == 1
        assert d["candidate_limit"] == 20

    def test_cycle_count_increments_across_calls(self):
        sched = make_scheduler()
        sched.run_once()
        sched.run_once()
        sched.run_once()
        assert sched.cycle_count == 3


class TestSettingsDefaults:
    """Matches tests/test_market_scanner.py's own TestSettingsDefaults
    precedent for SCANNER_ENABLED — the bootstrap wiring itself in
    main.py isn't directly unit-tested (same as MarketScanner's own
    startup block isn't), but the safe-by-default posture is."""

    def test_scheduler_disabled_by_default(self):
        from config.settings import Settings
        assert Settings().SCHEDULER_ENABLED is False

    def test_default_interval_is_60s(self):
        from config.settings import Settings
        assert Settings().SCHEDULER_INTERVAL_SECONDS == 60

    def test_default_candidate_limit_is_20(self):
        from config.settings import Settings
        assert Settings().SCHEDULER_CANDIDATE_LIMIT == 20
