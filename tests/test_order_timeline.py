"""tests/test_order_timeline.py — Track C3 Phase 1: Unified Order/Trade Timeline"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from execution.order_timeline import (
    OrderTimeline,
    TimelineState,
    compose_state,
    get_order_timeline,
    reset_order_timeline,
)
from execution.trade_lifecycle import CloseSource, TradeLifecycle, TradeLifecycleState

pytestmark = pytest.mark.unit


def _fake_exchange_manager(order_status_by_symbol: dict[str, str]):
    """Minimal duck-typed stand-in for ExchangeStateManager — OrderTimeline
    only ever calls .get_orders() on it (see module docstring: it never
    calls refresh(), never touches BinanceDataProvider)."""
    orders = [SimpleNamespace(symbol=sym, status=status) for sym, status in order_status_by_symbol.items()]
    return SimpleNamespace(get_orders=lambda: orders)


# ── compose_state() — pure function ──────────────────────────────────

class TestComposeState:

    def test_no_handle_is_new(self):
        assert compose_state(None, None) == TimelineState.NEW

    def test_pending_is_new(self):
        assert compose_state(TradeLifecycleState.PENDING, None) == TimelineState.NEW

    def test_executing_with_no_order_info_is_submitted(self):
        assert compose_state(TradeLifecycleState.EXECUTING, None) == TimelineState.SUBMITTED

    def test_executing_with_order_status_new_is_acknowledged(self):
        assert compose_state(TradeLifecycleState.EXECUTING, "NEW") == TimelineState.ACKNOWLEDGED

    def test_executing_with_partially_filled_order(self):
        assert compose_state(TradeLifecycleState.EXECUTING, "PARTIALLY_FILLED") == TimelineState.PARTIALLY_FILLED

    def test_executing_with_canceled_order(self):
        assert compose_state(TradeLifecycleState.EXECUTING, "CANCELED") == TimelineState.CANCELLED

    def test_open_is_filled(self):
        assert compose_state(TradeLifecycleState.OPEN, None) == TimelineState.FILLED

    def test_monitoring_is_open(self):
        assert compose_state(TradeLifecycleState.MONITORING, None) == TimelineState.OPEN

    def test_exit_requested_is_closing(self):
        assert compose_state(TradeLifecycleState.EXIT_REQUESTED, None) == TimelineState.CLOSING

    def test_exit_executing_is_closing(self):
        assert compose_state(TradeLifecycleState.EXIT_EXECUTING, None) == TimelineState.CLOSING

    def test_closed_is_closed(self):
        assert compose_state(TradeLifecycleState.CLOSED, None) == TimelineState.CLOSED

    def test_failed_is_failed(self):
        assert compose_state(TradeLifecycleState.FAILED, None) == TimelineState.FAILED

    def test_order_status_refinement_ignored_outside_executing(self):
        """Order-status refinement only applies during EXECUTING — see
        module docstring. A stale/leftover order status must not
        override e.g. an OPEN (already-filled) trade state."""
        assert compose_state(TradeLifecycleState.OPEN, "PARTIALLY_FILLED") == TimelineState.FILLED


# ── run_once() diffing against the two real/stub sources ────────────

class TestRunOnce:

    def test_new_pending_trade_is_recorded_as_new(self, tmp_path):
        lifecycle = TradeLifecycle()
        lifecycle.open_pending("BTCUSDT")
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=str(tmp_path / "t.db"))

        entries = ot.run_once()

        assert len(entries) == 1
        assert entries[0].symbol == "BTCUSDT"
        assert entries[0].state_before is None
        assert entries[0].state_after == TimelineState.NEW

    def test_no_duplicate_entry_when_state_unchanged(self, tmp_path):
        lifecycle = TradeLifecycle()
        lifecycle.open_pending("BTCUSDT")
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=str(tmp_path / "t.db"))

        ot.run_once()
        second = ot.run_once()

        assert second == []
        assert len(ot.recent()) == 1

    def test_full_open_to_close_sequence_produces_expected_transitions(self, tmp_path):
        lifecycle = TradeLifecycle()
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=str(tmp_path / "t.db"))

        handle = lifecycle.open_pending("BTCUSDT")
        ot.run_once()  # NEW

        lifecycle.open_executing(handle)
        ot.run_once()  # SUBMITTED

        lifecycle.open_confirmed(handle, trade_id=1)  # -> OPEN -> MONITORING internally
        ot.run_once()  # composed state settles on OPEN (MONITORING wins as last real state)

        lifecycle.request_exit("BTCUSDT", CloseSource.STOP_LOSS, "sl hit")
        ot.run_once()  # CLOSING

        lifecycle.exit_executing(handle)  # EXIT_REQUESTED -> EXIT_EXECUTING (still composes to CLOSING)
        lifecycle.exit_confirmed(handle, result="WIN", pnl=10.0)
        ot.run_once()  # CLOSED

        states = [e["state_after"] for e in ot.recent(symbol="BTCUSDT")][::-1]
        assert states == [
            TimelineState.NEW,
            TimelineState.SUBMITTED,
            TimelineState.OPEN,
            TimelineState.CLOSING,
            TimelineState.CLOSED,
        ]

    def test_terminal_state_is_recorded_not_reverted_to_new(self, tmp_path):
        """Guards against a real bug caught during design: TradeLifecycle
        .snapshot() deliberately excludes terminal CLOSED/FAILED handles
        (see its own docstring). Diffing off snapshot() alone would make
        a closed symbol look like trade_state=None -> composed NEW the
        very next poll. get_handle_snapshot() (added this phase) fixes
        this by reading the terminal handle directly."""
        lifecycle = TradeLifecycle()
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=str(tmp_path / "t.db"))

        handle = lifecycle.open_pending("ETHUSDT")
        lifecycle.open_executing(handle)
        lifecycle.open_confirmed(handle, trade_id=7)
        lifecycle.request_exit("ETHUSDT", CloseSource.TAKE_PROFIT, "tp hit")
        lifecycle.exit_executing(handle)
        lifecycle.exit_confirmed(handle, result="WIN", pnl=5.0)

        ot.run_once()  # first observation after all of the above: settles on CLOSED
        again = ot.run_once()  # nothing changed — must stay CLOSED, not flip to NEW

        assert again == []
        assert ot.current_state("ETHUSDT")["state"] == TimelineState.CLOSED

    def test_order_status_refinement_from_exchange_manager(self, tmp_path):
        lifecycle = TradeLifecycle()
        handle = lifecycle.open_pending("BNBUSDT")
        lifecycle.open_executing(handle)

        exchange = _fake_exchange_manager({"BNBUSDT": "PARTIALLY_FILLED"})
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", exchange_manager=exchange, db_path=str(tmp_path / "t.db"))

        ot.run_once()  # NEW is skipped (created before first run_once() call in this test)
        assert ot.current_state("BNBUSDT")["state"] == TimelineState.PARTIALLY_FILLED

    def test_missing_exchange_manager_does_not_crash(self, tmp_path):
        lifecycle = TradeLifecycle()
        lifecycle.open_pending("BTCUSDT")
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", exchange_manager=None, db_path=str(tmp_path / "t.db"))

        entries = ot.run_once()

        assert len(entries) == 1  # still gets the TradeLifecycle-only view


# ── persistence / restart survival ───────────────────────────────────

class TestPersistenceAndRestart:

    def test_history_survives_a_fresh_instance_against_the_same_db_file(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")

        lifecycle_a = TradeLifecycle()
        lifecycle_a.open_pending("BTCUSDT")
        ot_a = OrderTimeline(lifecycle_a, execution_lane="LIVE", db_path=db_path)
        ot_a.run_once()

        # Simulate a restart: a brand-new OrderTimeline, brand-new
        # TradeLifecycle (empty), but the SAME db file — history() must
        # still show the row ot_a wrote, even though this new instance's
        # in-memory current_state()/recent() start empty.
        lifecycle_b = TradeLifecycle()
        ot_b = OrderTimeline(lifecycle_b, execution_lane="LIVE", db_path=db_path)

        assert ot_b.recent() == []
        rows = ot_b.history(symbol="BTCUSDT")
        assert len(rows) == 1
        assert rows[0]["state_after"] == TimelineState.NEW

    def test_history_is_ordered_newest_first_and_respects_limit(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        lifecycle = TradeLifecycle()
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=db_path)

        handle = lifecycle.open_pending("BTCUSDT")
        ot.run_once()
        lifecycle.open_executing(handle)
        ot.run_once()
        lifecycle.open_confirmed(handle, trade_id=1)
        ot.run_once()

        rows = ot.history(symbol="BTCUSDT", limit=2)
        assert len(rows) == 2
        assert rows[0]["state_after"] == TimelineState.OPEN
        assert rows[1]["state_after"] == TimelineState.SUBMITTED

    def test_schema_init_is_idempotent_across_instances(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        OrderTimeline(TradeLifecycle(), execution_lane="LIVE", db_path=db_path)
        OrderTimeline(TradeLifecycle(), execution_lane="LIVE", db_path=db_path)  # must not raise

    def test_history_is_trimmed_once_row_cap_is_exceeded(self, tmp_path):
        """ORDER_TIMELINE_HISTORY_MAX_ROWS guard — order_timeline_history
        must not grow unbounded on a long-running process."""
        db_path = str(tmp_path / "timeline.db")
        lifecycle = TradeLifecycle()
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=db_path, max_history_rows=5)
        ot._TRIM_CHECK_INTERVAL = 1  # check every persisted batch for this test

        # Produce more than 5 persisted transitions across distinct symbols.
        for i in range(8):
            symbol = f"SYM{i}USDT"
            lifecycle.open_pending(symbol)
            ot.run_once()

        rows = ot.history(limit=1000)
        assert len(rows) <= 5

    def test_trim_does_not_run_before_the_check_interval(self, tmp_path):
        db_path = str(tmp_path / "timeline.db")
        lifecycle = TradeLifecycle()
        ot = OrderTimeline(lifecycle, execution_lane="LIVE", db_path=db_path, max_history_rows=1)
        # Default _TRIM_CHECK_INTERVAL (200) — a couple of persisted
        # batches must NOT trigger a trim yet, even though max_rows=1.
        lifecycle.open_pending("BTCUSDT")
        ot.run_once()
        lifecycle.open_pending("ETHUSDT")
        ot.run_once()

        assert len(ot.history(limit=1000)) == 2


# ── background thread lifecycle ──────────────────────────────────────

class TestThreadLifecycle:

    def test_start_stop_is_running(self, tmp_path):
        ot = OrderTimeline(TradeLifecycle(), execution_lane="LIVE", db_path=str(tmp_path / "t.db"), poll_interval_seconds=0.05)
        assert ot.is_running() is False

        ot.start()
        try:
            time.sleep(0.2)
            assert ot.is_running() is True
        finally:
            ot.stop()

        assert ot.is_running() is False

    def test_start_is_idempotent(self, tmp_path):
        ot = OrderTimeline(TradeLifecycle(), execution_lane="LIVE", db_path=str(tmp_path / "t.db"), poll_interval_seconds=0.05)
        ot.start()
        first_thread = ot._thread
        ot.start()  # should not spawn a second thread
        try:
            assert ot._thread is first_thread
        finally:
            ot.stop()


# ── singleton accessor ────────────────────────────────────────────────

class TestSingleton:

    def teardown_method(self):
        reset_order_timeline()

    def test_get_order_timeline_returns_same_instance(self):
        a = get_order_timeline(trade_lifecycle=TradeLifecycle(), db_path=":memory:")
        b = get_order_timeline()
        assert a is b

    def test_reset_order_timeline_forces_a_fresh_instance(self):
        a = get_order_timeline(trade_lifecycle=TradeLifecycle(), db_path=":memory:")
        reset_order_timeline()
        b = get_order_timeline(trade_lifecycle=TradeLifecycle(), db_path=":memory:")
        assert a is not b
