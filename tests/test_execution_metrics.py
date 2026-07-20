"""tests/test_execution_metrics.py — V16 Phase 2E: Execution Wiring & Live Orchestrator"""
from __future__ import annotations

import pytest

from execution.execution_metrics import compute_metrics
from execution.execution_state import ExecutionState

pytestmark = pytest.mark.unit


class TestComputeMetricsEmpty:

    def test_empty_state_gives_zeroed_snapshot(self):
        snap = compute_metrics(ExecutionState())
        assert snap.total == 0
        assert snap.success_rate == 0.0
        assert snap.failure_rate == 0.0
        assert snap.retry_rate == 0.0
        assert snap.average_latency_seconds == 0.0
        assert snap.per_symbol_counts == {}


class TestComputeMetricsCounts:

    def _state_with(self):
        s = ExecutionState()
        # one clean success
        s.enqueue("e1", "b1", "BTCUSDT"); s.start("e1"); s.complete("e1", {})
        # one success after a retry
        s.enqueue("e2", "b1", "ETHUSDT"); s.start("e2"); s.record_retry("e2"); s.complete("e2", {})
        # one failure
        s.enqueue("e3", "b1", "SOLUSDT"); s.start("e3"); s.fail("e3", "rejected")
        # one cancelled (never started)
        s.enqueue("e4", "b1", "ADAUSDT"); s.cancel("e4", "no_signal")
        # one still pending
        s.enqueue("e5", "b1", "XRPUSDT")
        return s

    def test_status_counts(self):
        snap = compute_metrics(self._state_with())
        assert snap.total == 5
        assert snap.completed == 2
        assert snap.failed == 1
        assert snap.cancelled == 1
        assert snap.pending == 1
        assert snap.running == 0

    def test_success_and_failure_rate_only_over_finished(self):
        """finished = completed + failed = 3 (2 completed, 1 failed);
        pending/cancelled must not dilute the rate."""
        snap = compute_metrics(self._state_with())
        assert snap.success_rate == pytest.approx(2 / 3)
        assert snap.failure_rate == pytest.approx(1 / 3)

    def test_retry_rate_over_finished_only(self):
        """Of the 3 finished executions, exactly 1 (e2) needed a retry."""
        snap = compute_metrics(self._state_with())
        assert snap.retry_rate == pytest.approx(1 / 3)

    def test_per_symbol_counts_include_every_tracked_record(self):
        snap = compute_metrics(self._state_with())
        assert snap.per_symbol_counts == {
            "BTCUSDT": 1, "ETHUSDT": 1, "SOLUSDT": 1, "ADAUSDT": 1, "XRPUSDT": 1,
        }

    def test_per_symbol_counts_sum_multiple_executions_same_symbol(self):
        s = ExecutionState()
        s.enqueue("e1", "b1", "BTCUSDT"); s.start("e1"); s.complete("e1", {})
        s.enqueue("e2", "b2", "BTCUSDT"); s.start("e2"); s.complete("e2", {})
        snap = compute_metrics(s)
        assert snap.per_symbol_counts["BTCUSDT"] == 2


class TestAverageLatency:

    def test_average_latency_across_finished_records(self):
        s = ExecutionState()
        s.enqueue("e1", "b1", "AAA")
        r1 = s.start("e1")
        s.complete("e1", {})
        r1.finished_at = r1.started_at + 1.0  # override after complete() sets its own timestamp

        s.enqueue("e2", "b1", "BBB")
        r2 = s.start("e2")
        s.complete("e2", {})
        r2.finished_at = r2.started_at + 3.0

        snap = compute_metrics(s)
        assert snap.average_latency_seconds == pytest.approx(2.0)

    def test_pending_records_do_not_contribute_latency(self):
        s = ExecutionState()
        s.enqueue("e1", "b1", "AAA")  # never started/finished
        snap = compute_metrics(s)
        assert snap.average_latency_seconds == 0.0


class TestSnapshotToDict:

    def test_to_dict_rounds_and_serializes(self):
        s = ExecutionState()
        s.enqueue("e1", "b1", "AAA"); s.start("e1"); s.complete("e1", {})
        snap = compute_metrics(s)
        d = snap.to_dict()
        assert d["total"] == 1
        assert d["success_rate"] == 1.0
        assert isinstance(d["per_symbol_counts"], dict)
