"""tests/test_execution_state.py — V16 Phase 2E: Execution Wiring & Live Orchestrator"""
from __future__ import annotations

import pytest

from execution.execution_state import (
    ExecutionState,
    ExecutionStatus,
    get_execution_state,
    reset_execution_state,
)

pytestmark = pytest.mark.unit


class TestIdempotencyLedger:

    def test_not_executed_by_default(self):
        s = ExecutionState()
        assert s.already_executed("batch-1", "BTCUSDT") is False

    def test_mark_executed_then_already_executed_true(self):
        s = ExecutionState()
        s.mark_executed("batch-1", "BTCUSDT")
        assert s.already_executed("batch-1", "BTCUSDT") is True

    def test_idempotency_is_scoped_per_batch(self):
        """Same symbol, different batch (decision cycle) — not a duplicate."""
        s = ExecutionState()
        s.mark_executed("batch-1", "BTCUSDT")
        assert s.already_executed("batch-2", "BTCUSDT") is False

    def test_idempotency_is_scoped_per_symbol(self):
        s = ExecutionState()
        s.mark_executed("batch-1", "BTCUSDT")
        assert s.already_executed("batch-1", "ETHUSDT") is False


class TestLifecycle:

    def test_enqueue_creates_pending_record(self):
        s = ExecutionState()
        record = s.enqueue("exec-1", "batch-1", "BTCUSDT")
        assert record.status == ExecutionStatus.PENDING
        assert s.pending_count == 1

    def test_start_transitions_pending_to_running(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        record = s.start("exec-1")
        assert record is not None
        assert record.status == ExecutionStatus.RUNNING
        assert record.started_at is not None
        assert s.running_count == 1
        assert s.pending_count == 0

    def test_start_on_unknown_id_returns_none(self):
        s = ExecutionState()
        assert s.start("does-not-exist") is None

    def test_start_twice_second_call_returns_none(self):
        """A record already RUNNING is not PENDING anymore — calling
        start() again must not silently re-arm it."""
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        assert s.start("exec-1") is None

    def test_complete_sets_completed_status_and_result(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        s.complete("exec-1", {"quantity": 1.5})
        record = s.get("exec-1")
        assert record.status == ExecutionStatus.COMPLETED
        assert record.finished_at is not None
        assert record.result == {"quantity": 1.5}
        assert s.completed_count == 1

    def test_fail_sets_failed_status_and_error(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        s.fail("exec-1", "exchange rejected order")
        record = s.get("exec-1")
        assert record.status == ExecutionStatus.FAILED
        assert record.error == "exchange rejected order"
        assert s.failed_count == 1

    def test_cancel_sets_cancelled_status_from_any_state(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        s.cancel("exec-1", "no_signal")
        record = s.get("exec-1")
        assert record.status == ExecutionStatus.CANCELLED
        assert record.error == "no_signal"
        assert s.cancelled_count == 1

    def test_operations_on_unknown_id_are_safe_noops(self):
        s = ExecutionState()
        s.complete("nope", {})
        s.fail("nope", "err")
        s.cancel("nope", "reason")
        assert s.record_retry("nope") == 0
        assert s.get("nope") is None


class TestRequestCancel:

    def test_cancel_pending_execution_succeeds(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        assert s.request_cancel("exec-1", "manual_cancel") is True
        assert s.get("exec-1").status == ExecutionStatus.CANCELLED
        assert s.get("exec-1").error == "manual_cancel"

    def test_cancel_already_running_execution_fails(self):
        """Never retry/cancel manual — but also can't cancel something
        already in flight; matches real-world semantics."""
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        assert s.request_cancel("exec-1") is False
        assert s.get("exec-1").status == ExecutionStatus.RUNNING

    def test_cancel_already_completed_execution_fails(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        s.complete("exec-1", {})
        assert s.request_cancel("exec-1") is False

    def test_cancel_unknown_id_fails(self):
        s = ExecutionState()
        assert s.request_cancel("does-not-exist") is False


class TestRetryCounting:

    def test_record_retry_increments_and_returns_new_count(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        assert s.record_retry("exec-1") == 1
        assert s.record_retry("exec-1") == 2
        assert s.get("exec-1").retry_count == 2


class TestLatency:

    def test_latency_seconds_none_when_not_finished(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        s.start("exec-1")
        assert s.get("exec-1").latency_seconds is None

    def test_latency_seconds_computed_after_finish(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "BTCUSDT")
        record = s.start("exec-1")
        record.finished_at = record.started_at + 0.25
        assert s.get("exec-1").latency_seconds == pytest.approx(0.25)


class TestQueryAndAggregates:

    def test_by_status_filters_correctly(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "AAA")
        s.enqueue("exec-2", "batch-1", "BBB")
        s.start("exec-2")
        assert [r.execution_id for r in s.by_status(ExecutionStatus.PENDING)] == ["exec-1"]
        assert [r.execution_id for r in s.by_status(ExecutionStatus.RUNNING)] == ["exec-2"]

    def test_to_dict_summary_counts(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "AAA")
        s.enqueue("exec-2", "batch-1", "BBB")
        s.start("exec-2")
        s.complete("exec-2", {})
        d = s.to_dict()
        assert d["pending"] == 1
        assert d["completed"] == 1
        assert d["total_tracked"] == 2

    def test_clear_resets_everything(self):
        s = ExecutionState()
        s.enqueue("exec-1", "batch-1", "AAA")
        s.mark_executed("batch-1", "AAA")
        s.clear()
        assert s.all_records() == []
        assert s.already_executed("batch-1", "AAA") is False

    def test_history_ring_buffer_evicts_oldest(self):
        """Mirrors events/event_bus.py's bounded-ring-buffer behavior —
        long-running processes must not grow this dict unboundedly."""
        s = ExecutionState()
        from execution.execution_state import _HISTORY_SIZE
        for i in range(_HISTORY_SIZE + 5):
            s.enqueue(f"exec-{i}", "batch-1", "AAA")
        assert len(s.all_records()) == _HISTORY_SIZE
        # the oldest 5 must have been evicted
        assert s.get("exec-0") is None
        assert s.get(f"exec-{_HISTORY_SIZE + 4}") is not None


class TestSingleton:

    def test_get_execution_state_returns_same_instance(self):
        reset_execution_state()
        a = get_execution_state()
        b = get_execution_state()
        assert a is b

    def test_reset_execution_state_returns_fresh_instance(self):
        a = get_execution_state()
        a.enqueue("exec-1", "batch-1", "AAA")
        b = reset_execution_state()
        assert a is not b
        assert b.all_records() == []
