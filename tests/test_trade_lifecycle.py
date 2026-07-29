"""
tests/test_trade_lifecycle.py — V16 Phase 4B Step 3D

Core unit tests for execution/trade_lifecycle.py in isolation — no
ExecutionOrchestrator, no PortfolioManager real instance (a minimal
fake standing in for "anything exposing notify_position_closed()"),
no journal I/O (a minimal fake standing in for "anything
record_trade_outcome() accepts"). Real wiring into the actual close
paths is covered separately (tests/test_trade_lifecycle_integration.py).
"""
from __future__ import annotations

import pytest

from execution.trade_lifecycle import (
    TradeLifecycle,
    TradeLifecycleState,
    TradeLifecycleError,
    CloseSource,
)

pytestmark = pytest.mark.unit


class FakeJournal:
    def __init__(self):
        self.update_calls = []
        self.attribution_calls = []

    def update_trade_result(self, trade_id, result, exit_price, pnl):
        self.update_calls.append((trade_id, result, exit_price, pnl))
        return True

    def save_execution_attribution(self, trade_id, **fields):
        self.attribution_calls.append((trade_id, fields))
        return True


class FailingJournal(FakeJournal):
    def update_trade_result(self, *a, **k):
        raise RuntimeError("db unavailable")

    def save_execution_attribution(self, *a, **k):
        raise RuntimeError("db unavailable")


class FakePortfolioManager:
    def __init__(self):
        self.calls = []

    def notify_position_closed(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))


class TestStateMachineBasics:
    def test_open_pending_starts_in_pending(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        assert h.state == TradeLifecycleState.PENDING

    def test_full_open_sequence_ends_in_monitoring(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        assert h.state == TradeLifecycleState.MONITORING

    def test_open_failed_from_executing(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_failed(h, reason="rejected")
        assert h.state == TradeLifecycleState.FAILED

    def test_full_close_sequence_ends_in_closed(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        assert exit_h.state == TradeLifecycleState.CLOSED

    def test_exit_failed_from_exit_executing(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.STOP_LOSS, "sl_hit")
        lc.exit_executing(exit_h)
        lc.exit_failed(exit_h, reason="exchange_reject")
        assert exit_h.state == TradeLifecycleState.FAILED


class TestInvalidTransitions:
    def test_cannot_skip_executing(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        with pytest.raises(TradeLifecycleError):
            lc.open_confirmed(h, trade_id=1)  # PENDING -> OPEN directly, invalid

    def test_cannot_request_exit_twice_directly(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        first = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        assert first is not None
        second = lc.request_exit("BTCUSDT", CloseSource.STOP_LOSS, "sl_hit")
        assert second is None

    def test_cannot_close_after_closed(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        duplicate = lc.request_exit("BTCUSDT", CloseSource.STOP_LOSS, "sl_hit_again")
        assert duplicate is None

    def test_cannot_close_after_failed(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.STOP_LOSS, "sl_hit")
        lc.exit_executing(exit_h)
        lc.exit_failed(exit_h, reason="reject")
        duplicate = lc.request_exit("BTCUSDT", CloseSource.STOP_LOSS, "sl_hit_again")
        assert duplicate is None


class TestSyntheticHandleForUntrackedSymbols:
    def test_close_for_never_seen_symbol_creates_synthetic_monitoring_handle(self):
        lc = TradeLifecycle()
        # No open_pending/open_confirmed call for this symbol at all —
        # simulates the legacy single-symbol path, which doesn't call
        # TradeLifecycle's open side yet.
        exit_h = lc.request_exit("LEGACYUSDT", CloseSource.STOP_LOSS, "sl_hit", trade_id=42)
        assert exit_h is not None
        assert exit_h.trade_id == 42

    def test_synthetic_handle_close_still_writes_to_journal(self):
        jrn = FakeJournal()
        lc = TradeLifecycle(journal=jrn)
        exit_h = lc.request_exit("LEGACYUSDT", CloseSource.STOP_LOSS, "sl_hit", trade_id=42)
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="LOSS", exit_price=90.0, pnl=-3.0)
        assert jrn.update_calls == [(42, "LOSS", 90.0, -3.0)]


class TestJournalWriting:
    def test_open_confirmed_writes_attribution_only_not_result(self):
        jrn = FakeJournal()
        lc = TradeLifecycle(journal=jrn)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1, execution_id="e1", order_id="o1")
        assert jrn.update_calls == []  # no result yet on open
        assert len(jrn.attribution_calls) == 1
        assert jrn.attribution_calls[0][1]["execution_id"] == "e1"

    def test_exit_confirmed_writes_result_and_attribution(self):
        jrn = FakeJournal()
        lc = TradeLifecycle(journal=jrn)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        assert jrn.update_calls == [(1, "WIN", 100.0, 5.0)]

    def test_close_attribution_includes_reason_source_symbol_duration(self):
        jrn = FakeJournal()
        lc = TradeLifecycle(journal=jrn)
        h = lc.open_pending("ETHUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=7)
        exit_h = lc.request_exit("ETHUSDT", CloseSource.REPLACEMENT, "replaced_by_higher_score")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=50.0, pnl=2.0)
        # two attribution calls total: one from open_confirmed, one from exit_confirmed
        close_call = jrn.attribution_calls[-1]
        assert close_call[0] == 7
        fields = close_call[1]
        assert fields["reason"] == "replaced_by_higher_score"
        assert fields["source"] == "REPLACEMENT"
        assert fields["symbol"] == "ETHUSDT"
        assert fields["duration_seconds"] is not None
        assert fields["duration_seconds"] >= 0

    def test_no_journal_no_crash(self):
        lc = TradeLifecycle(journal=None)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)  # should not raise despite no journal
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)  # should not raise
        assert exit_h.state == TradeLifecycleState.CLOSED

    def test_journal_failure_does_not_block_state_transition(self):
        # Matches this codebase's established "diagnostic data must
        # never break a live trade" rule.
        jrn = FailingJournal()
        lc = TradeLifecycle(journal=jrn)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)  # journal raises internally, caught
        assert h.state == TradeLifecycleState.MONITORING
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        assert exit_h.state == TradeLifecycleState.CLOSED  # transition still happened


class TestPortfolioNotification:
    def test_exit_confirmed_notifies_portfolio_manager_with_record_attribution_false(self):
        pm = FakePortfolioManager()
        lc = TradeLifecycle(journal=FakeJournal(), portfolio_manager=pm)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        assert len(pm.calls) == 1
        symbol, kwargs = pm.calls[0]
        assert symbol == "BTCUSDT"
        assert kwargs["record_attribution"] is False

    def test_notify_portfolio_false_skips_notification(self):
        pm = FakePortfolioManager()
        lc = TradeLifecycle(journal=FakeJournal(), portfolio_manager=pm)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0, notify_portfolio=False)
        assert pm.calls == []

    def test_no_portfolio_manager_no_crash(self):
        lc = TradeLifecycle(journal=FakeJournal(), portfolio_manager=None)
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)  # no crash
        assert exit_h.state == TradeLifecycleState.CLOSED


class TestSnapshotAndLen:
    def test_snapshot_empty_initially(self):
        lc = TradeLifecycle()
        assert lc.snapshot() == []
        assert len(lc) == 0

    def test_snapshot_includes_live_handles(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        snap = lc.snapshot()
        assert len(snap) == 1
        assert snap[0]["symbol"] == "BTCUSDT"
        assert snap[0]["state"] == "MONITORING"
        assert len(lc) == 1

    def test_snapshot_excludes_closed_handles(self):
        lc = TradeLifecycle(journal=FakeJournal())
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        assert lc.snapshot() == []
        assert len(lc) == 0

    def test_snapshot_excludes_failed_handles(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_failed(h, reason="rejected")
        assert lc.snapshot() == []
        assert len(lc) == 0

    def test_multiple_symbols_tracked_independently(self):
        lc = TradeLifecycle()
        for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            h = lc.open_pending(sym)
            lc.open_executing(h)
            lc.open_confirmed(h, trade_id=hash(sym) % 1000)
        assert len(lc) == 3
        symbols = {row["symbol"] for row in lc.snapshot()}
        assert symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def test_reopening_a_symbol_after_close_replaces_terminal_handle(self):
        lc = TradeLifecycle(journal=FakeJournal())
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.TAKE_PROFIT, "tp_hit")
        lc.exit_executing(exit_h)
        lc.exit_confirmed(exit_h, result="WIN", exit_price=100.0, pnl=5.0)
        assert len(lc) == 0

        h2 = lc.open_pending("BTCUSDT")
        lc.open_executing(h2)
        lc.open_confirmed(h2, trade_id=2)
        assert len(lc) == 1
        assert lc.get_state("BTCUSDT") == TradeLifecycleState.MONITORING

    def test_get_state_none_for_unknown_symbol(self):
        lc = TradeLifecycle()
        assert lc.get_state("NEVERUSDT") is None


class TestCloseSourceEnum:
    def test_all_brief_sources_have_enum_values(self):
        expected = {
            "SL", "TP", "CEO_BLOCKED", "REPLACEMENT", "PORTFOLIO_ROTATION",
            "RISK_CLOSE", "RECOVERY", "MANUAL_CLOSE", "EXCHANGE_CLOSE",
            "RECONCILIATION", "LIQUIDATION", "EMERGENCY_CLOSE",
        }
        actual = {member.value for member in CloseSource}
        assert actual == expected

    def test_close_source_recorded_on_handle(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        exit_h = lc.request_exit("BTCUSDT", CloseSource.LIQUIDATION, "liquidated")
        assert exit_h.exit_source == CloseSource.LIQUIDATION


class TestEmptyInstanceIsStillTruthy:
    """Regression test for a real bug this phase's own integration
    tests caught: TradeLifecycle defines __len__ for Part I's "no
    orphan positions" checks, which — without an explicit __bool__ —
    would make a freshly-constructed, empty (0 live handles) instance
    evaluate as falsy, silently breaking any `lifecycle or default()`
    fallback pattern a caller might use (exactly what
    execution/execution_orchestrator.py's constructor did before this
    was found and fixed)."""

    def test_fresh_empty_lifecycle_is_truthy(self):
        lc = TradeLifecycle()
        assert len(lc) == 0
        assert bool(lc) is True

    def test_or_fallback_pattern_does_not_discard_empty_instance(self):
        empty_lc = TradeLifecycle()
        result = empty_lc or TradeLifecycle()
        assert result is empty_lc  # must be the SAME object, not a replacement

    def test_lifecycle_with_handles_is_also_truthy(self):
        lc = TradeLifecycle()
        h = lc.open_pending("BTCUSDT")
        lc.open_executing(h)
        lc.open_confirmed(h, trade_id=1)
        assert bool(lc) is True
