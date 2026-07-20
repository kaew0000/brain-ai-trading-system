"""
tests/test_execution_orchestrator.py — V16 Phase 2E: Execution Wiring &
Live Orchestrator

Uses plain fake test-doubles for execution_engine/portfolio_manager
(matching the duck-typed interfaces ExecutionOrchestrator actually
depends on — execution.execution_factory.build_execution_engine()'s
.execute_trade()/.close_position() contract, and
PortfolioManager.notify_position_closed()) rather than MagicMock, so
each fake's behavior is explicit and readable per test. No Binance, no
network, no REST mocking beyond the API layer already covered by
tests/test_execution_coordinator.py.
"""
from __future__ import annotations

import time

import pytest

from events.event_bus import EventBus, reset_event_bus
from execution.execution_events import EXECUTION_AGENT
from execution.execution_orchestrator import (
    ExecutionOrchestrator,
    ExecutionSignal,
)
from execution.execution_state import ExecutionState, ExecutionStatus
from portfolio.portfolio_models import (
    CorrelationTier,
    OrchestratedDecision,
    PortfolioAllocation,
    PortfolioPosition,
    PositionState,
    ReplacementProposal,
)
from portfolio.portfolio_state import PortfolioState

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_event_bus():
    """Most orchestrator tests don't inject a custom EventBus, so they
    publish through the process-wide get_event_bus() singleton by
    default. Reset it before/after every test here so this file's own
    tests don't interfere with each other, and so it doesn't leak
    execution_* events into other test files (e.g.
    tests/test_portfolio_ws.py's relay tests) when run in the same
    pytest session."""
    reset_event_bus()
    yield
    reset_event_bus()


# ── Shared builders ───────────────────────────────────────────────────────

def make_allocation(symbol="BTCUSDT", capital=200.0, risk_pct=0.01, leverage=5, priority=1) -> PortfolioAllocation:
    return PortfolioAllocation(
        symbol=symbol, priority=priority, allocation_pct=0.2, capital_amount=capital,
        risk_pct=risk_pct, risk_amount=capital * risk_pct, leverage=leverage,
        correlation_tier=CorrelationTier.LOW, correlation_penalty=1.0,
        coverage=1.0, final_score=80.0, reason="test allocation",
    )


def make_decision(selected=None, replacements=None, blocked=False, block_reason=None, generated_at=1_000.0) -> OrchestratedDecision:
    return OrchestratedDecision(
        generated_at=generated_at, blocked=blocked, block_reason=block_reason,
        selected=selected or [], replacements=replacements or [],
    )


def make_position(symbol="BTCUSDT", direction="LONG", qty=1.0) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol, direction=direction, entry_price=100.0, quantity=qty,
        leverage=5, notional=500.0, margin_used=100.0, unrealized_pnl=0.0,
        state=PositionState.OPEN, opened_at=time.time(),
    )


def always_long_signal(symbol) -> ExecutionSignal:
    return ExecutionSignal(direction=1, entry_price=50_000.0, stop_loss=49_000.0, take_profit=52_000.0)


class FakePortfolioManager:
    def __init__(self):
        self.closed_symbols = []

    def notify_position_closed(self, symbol):
        self.closed_symbols.append(symbol)


class FakeEngine:
    """Succeeds on every execute_trade() call. Records every call made
    so tests can assert on exactly what was sent to the execution
    layer."""

    def __init__(self):
        self.execute_calls = []
        self.close_calls = []

    def execute_trade(self, **kwargs):
        self.execute_calls.append(kwargs)
        return {
            "success": True, "direction": kwargs["direction"],
            "entry_price": kwargs["entry_price"], "quantity": 1.23,
            "stop_loss": kwargs["stop_loss"], "take_profit": kwargs["take_profit"],
            "error": None,
        }

    def close_position(self, direction, quantity, symbol=None, client_order_id=None):
        self.close_calls.append({"direction": direction, "quantity": quantity, "symbol": symbol})
        return {"closed": True, "symbol": symbol}


class FailingEngine:
    """Always fails execute_trade() with a configurable error message."""

    def __init__(self, error="Invalid qty=0"):
        self.error = error
        self.execute_calls = 0

    def execute_trade(self, **kwargs):
        self.execute_calls += 1
        return {"success": False, "error": self.error}


class FlakyEngine:
    """Fails with a recoverable-shaped error `fail_times` times, then succeeds."""

    def __init__(self, fail_times=1, error="connection timeout"):
        self.fail_times = fail_times
        self.error = error
        self.attempts = 0

    def execute_trade(self, **kwargs):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            return {"success": False, "error": self.error}
        return {"success": True, "entry_price": kwargs["entry_price"], "quantity": 2.0, "error": None}


class NoCloseEngine:
    """execute_trade only — no close_position (mirrors paper mode's
    _PaperAdapter, which does not support targeted per-symbol close)."""

    def execute_trade(self, **kwargs):
        return {"success": True, "entry_price": kwargs["entry_price"], "quantity": 1.0, "error": None}


def make_orchestrator(engine=None, pm=None, signal_provider=always_long_signal, state=None, **kwargs):
    return ExecutionOrchestrator(
        execution_engine=engine or FakeEngine(),
        portfolio_manager=pm or FakePortfolioManager(),
        signal_provider=signal_provider,
        state=state or ExecutionState(),
        **kwargs,
    )


# ── Successful execution ─────────────────────────────────────────────────

class TestSuccessfulExecution:

    def test_single_allocation_executes_and_completes(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        decision = make_decision(selected=[make_allocation("BTCUSDT")])
        batch = orch.execute(decision, PortfolioState(), balance=10_000.0)

        assert len(batch.results) == 1
        assert batch.results[0].status == ExecutionStatus.COMPLETED
        assert batch.results[0].success is True
        assert len(engine.execute_calls) == 1

    def test_execute_trade_called_with_allocation_sizing(self):
        """leverage/risk_pct must be passed through from the
        PortfolioAllocation unmodified — orchestrator does not
        recompute sizing (CapitalManager/RiskEngine already did)."""
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        alloc = make_allocation("ETHUSDT", risk_pct=0.02, leverage=8)
        orch.execute(make_decision(selected=[alloc]), PortfolioState(), balance=5_000.0)

        call = engine.execute_calls[0]
        assert call["symbol"] == "ETHUSDT"
        assert call["risk_pct"] == 0.02
        assert call["leverage"] == 8
        assert call["balance"] == 5_000.0

    def test_successful_execution_adds_position_to_portfolio_state(self):
        orch = make_orchestrator()
        pstate = PortfolioState()
        orch.execute(make_decision(selected=[make_allocation("BTCUSDT")]), pstate, balance=10_000.0)
        assert pstate.has_position("BTCUSDT")
        assert pstate.get_position("BTCUSDT").direction == "LONG"

    def test_multiple_allocations_all_execute(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        decision = make_decision(selected=[make_allocation("BTCUSDT"), make_allocation("ETHUSDT")])
        batch = orch.execute(decision, PortfolioState(), balance=10_000.0)
        assert len(batch.results) == 2
        assert all(r.success for r in batch.results)
        assert {c["symbol"] for c in engine.execute_calls} == {"BTCUSDT", "ETHUSDT"}


# ── Execution failure ────────────────────────────────────────────────────

class TestExecutionFailure:

    def test_non_recoverable_failure_marks_failed_no_retry(self):
        engine = FailingEngine(error="Invalid qty=0 (insufficient capital)")
        orch = make_orchestrator(engine=engine, max_retries=3)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)

        assert batch.results[0].status == ExecutionStatus.FAILED
        assert batch.results[0].success is False
        assert batch.results[0].retries == 0
        assert engine.execute_calls == 1  # never retried

    def test_failed_execution_does_not_add_position(self):
        engine = FailingEngine()
        orch = make_orchestrator(engine=engine)
        pstate = PortfolioState()
        orch.execute(make_decision(selected=[make_allocation("BTCUSDT")]), pstate, 1_000.0)
        assert not pstate.has_position("BTCUSDT")

    def test_exchange_rejection_is_non_recoverable(self):
        engine = FailingEngine(error="Entry order rejected by exchange")
        orch = make_orchestrator(engine=engine, max_retries=5)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        assert batch.results[0].retries == 0
        assert engine.execute_calls == 1


# ── Retry policy ──────────────────────────────────────────────────────────

class TestRetryPolicy:

    def test_recoverable_failure_retries_then_succeeds(self):
        engine = FlakyEngine(fail_times=1, error="connection timeout")
        orch = make_orchestrator(engine=engine, max_retries=2)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)

        assert batch.results[0].success is True
        assert batch.results[0].retries == 1
        assert engine.attempts == 2

    def test_retries_are_capped_at_max_retries(self):
        engine = FlakyEngine(fail_times=100, error="timeout")  # never actually succeeds
        orch = make_orchestrator(engine=engine, max_retries=2)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)

        assert batch.results[0].success is False
        assert batch.results[0].status == ExecutionStatus.FAILED
        assert batch.results[0].retries == 2
        assert engine.attempts == 3  # 1 initial + 2 retries

    def test_zero_max_retries_means_single_attempt(self):
        engine = FlakyEngine(fail_times=1, error="timeout")
        orch = make_orchestrator(engine=engine, max_retries=0)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        assert batch.results[0].success is False
        assert engine.attempts == 1

    def test_retry_count_recorded_in_execution_state(self):
        state = ExecutionState()
        engine = FlakyEngine(fail_times=1, error="timeout")
        orch = make_orchestrator(engine=engine, state=state, max_retries=2)
        orch.execute(make_decision(selected=[make_allocation("BTCUSDT")], generated_at=42.0), PortfolioState(), 1_000.0)
        record = state.get("decision-42.0:BTCUSDT")
        assert record.retry_count == 1


# ── Risk rejection (portfolio-level block) ──────────────────────────────

class TestRiskRejection:

    def test_blocked_decision_executes_nothing(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        decision = make_decision(selected=[make_allocation()], blocked=True, block_reason="daily_loss_limit")
        batch = orch.execute(decision, PortfolioState(), 1_000.0)

        assert batch.results == []
        assert engine.execute_calls == []

    def test_blocked_decision_still_publishes_metrics_event(self):
        bus = EventBus(persist=False)
        received = []
        bus.subscribe(EXECUTION_AGENT, received.append)
        import execution.execution_events as ee
        orig_get_bus = ee.get_event_bus
        ee.get_event_bus = lambda: bus
        try:
            orch = make_orchestrator()
            decision = make_decision(selected=[make_allocation()], blocked=True, block_reason="x")
            orch.execute(decision, PortfolioState(), 1_000.0)
        finally:
            ee.get_event_bus = orig_get_bus
        assert any(e.event == "execution_metrics_updated" for e in received)


# ── Idempotency / duplicate execution ────────────────────────────────────

class TestIdempotency:

    def test_same_decision_executed_twice_only_places_orders_once(self):
        engine = FakeEngine()
        state = ExecutionState()
        orch = make_orchestrator(engine=engine, state=state)
        decision = make_decision(selected=[make_allocation("BTCUSDT")], generated_at=99.0)

        orch.execute(decision, PortfolioState(), 1_000.0)
        batch2 = orch.execute(decision, PortfolioState(), 1_000.0)

        assert len(engine.execute_calls) == 1  # NOT called a second time
        assert batch2.results[0].status == ExecutionStatus.CANCELLED
        assert batch2.results[0].error == "already_executed"

    def test_different_decisions_are_independent(self):
        """Different generated_at => different default batch_id => the
        same symbol legitimately executes again."""
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        d1 = make_decision(selected=[make_allocation("BTCUSDT")], generated_at=1.0)
        d2 = make_decision(selected=[make_allocation("BTCUSDT")], generated_at=2.0)

        orch.execute(d1, PortfolioState(), 1_000.0)
        orch.execute(d2, PortfolioState(), 1_000.0)

        assert len(engine.execute_calls) == 2

    def test_explicit_batch_id_controls_idempotency_scope(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        decision = make_decision(selected=[make_allocation("BTCUSDT")])

        orch.execute(decision, PortfolioState(), 1_000.0, batch_id="manual-batch")
        orch.execute(decision, PortfolioState(), 1_000.0, batch_id="manual-batch")

        assert len(engine.execute_calls) == 1


# ── Duplicate symbols within one batch ───────────────────────────────────

class TestDuplicateSymbolsInBatch:

    def test_second_allocation_for_same_symbol_is_skipped(self):
        """Defensive guard — CapitalManager/PortfolioManager should never
        actually produce two allocations for the same symbol in one
        decision, but the orchestrator must not silently double-execute
        if it somehow happens."""
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        decision = make_decision(selected=[
            make_allocation("BTCUSDT", priority=1),
            make_allocation("BTCUSDT", priority=2),
        ])
        batch = orch.execute(decision, PortfolioState(), 1_000.0)

        assert len(engine.execute_calls) == 1
        statuses = [r.status for r in batch.results]
        assert statuses.count(ExecutionStatus.COMPLETED) == 1
        assert statuses.count(ExecutionStatus.CANCELLED) == 1
        cancelled = [r for r in batch.results if r.status == ExecutionStatus.CANCELLED][0]
        assert cancelled.error == "duplicate_symbol_in_batch"


# ── Partial execution (mixed outcomes in one batch) ──────────────────────

class TestPartialExecution:

    def test_one_succeeds_one_fails_in_same_batch(self):
        class MixedEngine:
            def execute_trade(self, **kwargs):
                if kwargs["symbol"] == "BTCUSDT":
                    return {"success": True, "entry_price": 50_000.0, "quantity": 1.0, "error": None}
                return {"success": False, "error": "Invalid qty=0"}

        orch = make_orchestrator(engine=MixedEngine())
        decision = make_decision(selected=[make_allocation("BTCUSDT"), make_allocation("ETHUSDT")])
        batch = orch.execute(decision, PortfolioState(), 1_000.0)

        by_symbol = {r.symbol: r for r in batch.results}
        assert by_symbol["BTCUSDT"].success is True
        assert by_symbol["ETHUSDT"].success is False
        summary = batch.summary()
        assert summary.completed == 1
        assert summary.failed == 1
        assert summary.total == 2


# ── Cancellation ──────────────────────────────────────────────────────────

class TestCancellation:

    def test_no_signal_cancels_without_calling_engine(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine, signal_provider=lambda s: None)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)

        assert batch.results[0].status == ExecutionStatus.CANCELLED
        assert batch.results[0].error == "no_signal"
        assert engine.execute_calls == []

    def test_flat_signal_direction_zero_cancels(self):
        engine = FakeEngine()
        flat = ExecutionSignal(direction=0, entry_price=0.0, stop_loss=0.0, take_profit=0.0)
        orch = make_orchestrator(engine=engine, signal_provider=lambda s: flat)
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        assert batch.results[0].status == ExecutionStatus.CANCELLED
        assert engine.execute_calls == []

    def test_preemptive_cancel_of_predicted_execution_id_is_respected(self):
        """A caller who knows the deterministic execution_id
        (f"{batch_id}:{symbol}", derivable from decision.generated_at
        before execute() ever runs) can cancel it in advance — e.g. a
        concurrent request handler cancelling allocation N+1 while
        execute()'s loop is still processing allocation N. Without the
        _already_cancelled guard, _execute_allocation's own enqueue()
        would silently stomp this pre-existing CANCELLED record back to
        PENDING."""
        state = ExecutionState()
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine, state=state)
        decision = make_decision(selected=[make_allocation("BTCUSDT")], generated_at=7.0)

        execution_id = "decision-7.0:BTCUSDT"
        state.enqueue(execution_id, "decision-7.0", "BTCUSDT")
        assert state.request_cancel(execution_id) is True

        batch = orch.execute(decision, PortfolioState(), 1_000.0)
        assert batch.results[0].status == ExecutionStatus.CANCELLED
        assert engine.execute_calls == []

    def test_cancel_reaches_not_yet_processed_allocation_in_same_batch(self):
        """The realistic single-threaded-loop scenario: within one
        execute() call processing [BTCUSDT, ETHUSDT] in order, a cancel
        issued for ETHUSDT's execution_id before the loop reaches it
        (simulated here via a signal_provider side effect that cancels
        the NEXT symbol the first time it's called) must be honored."""
        engine = FakeEngine()
        state = ExecutionState()
        batch_id_holder = {}

        def cancelling_signal_provider(symbol):
            if symbol == "BTCUSDT":
                # Simulate a concurrent cancel of ETHUSDT arriving while
                # BTCUSDT is still being processed.
                eth_execution_id = f"{batch_id_holder['id']}:ETHUSDT"
                state.enqueue(eth_execution_id, batch_id_holder["id"], "ETHUSDT")
                state.request_cancel(eth_execution_id)
            return always_long_signal(symbol)

        orch = make_orchestrator(engine=engine, state=state, signal_provider=cancelling_signal_provider)
        decision = make_decision(
            selected=[make_allocation("BTCUSDT"), make_allocation("ETHUSDT")], generated_at=8.0,
        )
        batch_id_holder["id"] = f"decision-{decision.generated_at}"

        batch = orch.execute(decision, PortfolioState(), 1_000.0)
        by_symbol = {r.symbol: r for r in batch.results}
        assert by_symbol["BTCUSDT"].success is True
        assert by_symbol["ETHUSDT"].status == ExecutionStatus.CANCELLED
        assert [c["symbol"] for c in engine.execute_calls] == ["BTCUSDT"]


# ── Replacement handling ─────────────────────────────────────────────────

class TestReplacementClose:

    def test_replacement_closes_outgoing_position(self):
        engine = FakeEngine()
        pm = FakePortfolioManager()
        pstate = PortfolioState()
        pstate.add_position(make_position("SOLUSDT", "LONG", qty=3.0))
        orch = make_orchestrator(engine=engine, pm=pm)
        proposal = ReplacementProposal(
            incoming_symbol="NEWUSDT", outgoing_symbol="SOLUSDT",
            incoming_score=90.0, outgoing_score=40.0, reason="better opportunity",
        )
        decision = make_decision(replacements=[proposal])
        batch = orch.execute(decision, pstate, 1_000.0)

        assert batch.results[0].status == ExecutionStatus.COMPLETED
        assert batch.results[0].is_replacement is True
        assert not pstate.has_position("SOLUSDT")
        assert pm.closed_symbols == ["SOLUSDT"]
        assert engine.close_calls[0]["symbol"] == "SOLUSDT"
        assert engine.close_calls[0]["direction"] == "LONG"
        assert engine.close_calls[0]["quantity"] == 3.0

    def test_replacement_does_not_open_incoming_symbol(self):
        """By design (see module docstring) — no sizing data exists for
        the incoming side at this decision layer."""
        engine = FakeEngine()
        pstate = PortfolioState()
        pstate.add_position(make_position("SOLUSDT"))
        orch = make_orchestrator(engine=engine)
        proposal = ReplacementProposal(
            incoming_symbol="NEWUSDT", outgoing_symbol="SOLUSDT",
            incoming_score=90.0, outgoing_score=40.0, reason="x",
        )
        orch.execute(make_decision(replacements=[proposal]), pstate, 1_000.0)
        assert not pstate.has_position("NEWUSDT")
        assert engine.execute_calls == []  # no open attempt for NEWUSDT

    def test_replacement_with_no_tracked_outgoing_position_is_cancelled(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine)
        proposal = ReplacementProposal(
            incoming_symbol="NEWUSDT", outgoing_symbol="GHOSTUSDT",
            incoming_score=90.0, outgoing_score=40.0, reason="x",
        )
        batch = orch.execute(make_decision(replacements=[proposal]), PortfolioState(), 1_000.0)
        assert batch.results[0].status == ExecutionStatus.CANCELLED
        assert batch.results[0].error == "outgoing_position_not_found"
        assert engine.close_calls == []

    def test_replacement_gracefully_skips_when_engine_lacks_close_position(self):
        """Mirrors paper mode's documented limitation — must not crash."""
        engine = NoCloseEngine()
        pstate = PortfolioState()
        pstate.add_position(make_position("SOLUSDT"))
        orch = make_orchestrator(engine=engine)
        proposal = ReplacementProposal(
            incoming_symbol="NEWUSDT", outgoing_symbol="SOLUSDT",
            incoming_score=90.0, outgoing_score=40.0, reason="x",
        )
        batch = orch.execute(make_decision(replacements=[proposal]), pstate, 1_000.0)
        assert batch.results[0].status == ExecutionStatus.CANCELLED
        assert batch.results[0].error == "execution_engine_does_not_support_close"
        assert pstate.has_position("SOLUSDT")  # untouched, not force-removed

    def test_replacement_close_failure_is_recorded_failed(self):
        class AlwaysFailsCloseEngine:
            def execute_trade(self, **kwargs):
                return {"success": True, "entry_price": 1.0, "quantity": 1.0, "error": None}
            def close_position(self, direction, quantity, symbol=None, client_order_id=None):
                return None  # exchange never confirms the close

        pm = FakePortfolioManager()
        pstate = PortfolioState()
        pstate.add_position(make_position("SOLUSDT"))
        orch = make_orchestrator(engine=AlwaysFailsCloseEngine(), pm=pm, max_retries=1)
        proposal = ReplacementProposal(
            incoming_symbol="NEWUSDT", outgoing_symbol="SOLUSDT",
            incoming_score=90.0, outgoing_score=40.0, reason="x",
        )
        batch = orch.execute(make_decision(replacements=[proposal]), pstate, 1_000.0)

        assert batch.results[0].status == ExecutionStatus.FAILED
        assert pstate.has_position("SOLUSDT")  # not removed — close never confirmed
        assert pm.closed_symbols == []  # notify_position_closed NOT called on failure

    def test_replacement_idempotent_across_repeated_execute_calls(self):
        engine = FakeEngine()
        pstate = PortfolioState()
        pstate.add_position(make_position("SOLUSDT"))
        orch = make_orchestrator(engine=engine)
        proposal = ReplacementProposal(
            incoming_symbol="NEWUSDT", outgoing_symbol="SOLUSDT",
            incoming_score=90.0, outgoing_score=40.0, reason="x",
        )
        decision = make_decision(replacements=[proposal], generated_at=55.0)
        orch.execute(decision, pstate, 1_000.0)
        # SOLUSDT no longer in pstate, so a second call also finds
        # "no tracked position" independently — but the idempotency
        # ledger should still short-circuit before even checking.
        batch2 = orch.execute(decision, pstate, 1_000.0)
        assert len(engine.close_calls) == 1
        assert batch2.results[0].error == "already_executed"


# ── Latency ────────────────────────────────────────────────────────────────

class TestLatencyTracking:

    def test_completed_execution_has_nonneg_latency_in_state(self):
        state = ExecutionState()
        orch = make_orchestrator(state=state)
        orch.execute(make_decision(selected=[make_allocation("BTCUSDT")], generated_at=3.0), PortfolioState(), 1_000.0)
        record = state.get("decision-3.0:BTCUSDT")
        assert record.latency_seconds is not None
        assert record.latency_seconds >= 0.0

    def test_batch_duration_seconds_nonnegative(self):
        orch = make_orchestrator()
        batch = orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        assert batch.duration_seconds >= 0.0


# ── Metrics integration ──────────────────────────────────────────────────

class TestMetricsIntegration:

    def test_metrics_reflect_executed_batch(self):
        engine = FakeEngine()
        state = ExecutionState()
        orch = make_orchestrator(engine=engine, state=state)
        decision = make_decision(selected=[make_allocation("BTCUSDT"), make_allocation("ETHUSDT")])
        orch.execute(decision, PortfolioState(), 1_000.0)

        snap = orch.metrics()
        assert snap.total == 2
        assert snap.completed == 2
        assert snap.success_rate == 1.0

    def test_metrics_updated_event_published_after_batch(self):
        bus = EventBus(persist=False)
        received = []
        bus.subscribe(EXECUTION_AGENT, received.append)
        import execution.execution_events as ee
        orig_get_bus = ee.get_event_bus
        ee.get_event_bus = lambda: bus
        try:
            orch = make_orchestrator()
            orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        finally:
            ee.get_event_bus = orig_get_bus

        event_types = [e.event for e in received]
        assert "execution_started" in event_types
        assert "execution_completed" in event_types
        assert "execution_metrics_updated" in event_types
        # metrics_updated must be the LAST event published for the batch
        assert event_types[-1] == "execution_metrics_updated"


# ── ExecutionSignal / direction mapping ──────────────────────────────────

class TestSignalDirectionMapping:

    def test_direction_1_maps_to_long(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine, signal_provider=lambda s: ExecutionSignal(1, 100.0, 90.0, 110.0))
        orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        assert engine.execute_calls[0]["direction"] == "LONG"

    def test_direction_minus_1_maps_to_short(self):
        engine = FakeEngine()
        orch = make_orchestrator(engine=engine, signal_provider=lambda s: ExecutionSignal(-1, 100.0, 110.0, 90.0))
        orch.execute(make_decision(selected=[make_allocation()]), PortfolioState(), 1_000.0)
        assert engine.execute_calls[0]["direction"] == "SHORT"
