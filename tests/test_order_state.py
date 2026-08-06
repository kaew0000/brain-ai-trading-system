"""
tests/test_order_state.py

V16 Phase ORDER-01: system_health/order_state.py — the canonical
eight-state layer composed on top of ExchangeStateManager,
ReconciliationEngine, RecoveryEngine, and TradeLifecycle (see that
module's docstring for the full composition rationale).

This file exercises OrderStateManager against a REAL ReconciliationEngine
instance (not a mock) so the classification tests are honest about what
reconciliation.py actually returns, while trade_lifecycle/event_bus/
data_provider stay mocked. Every test uses a fresh OrderStateManager AND
a fresh ReconciliationEngine so no state leaks between tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from system_health.reconciliation import ReconciliationEngine
from system_health.recovery_engine import RecoveryEngine
from system_health.order_state import OrderState, OrderStateManager

pytestmark = pytest.mark.unit


@dataclass
class _FakePortfolioPosition:
    direction: str
    quantity: float


def _dp(has_position: bool, side="LONG", qty=0.1062):
    dp = MagicMock()
    dp.get_position_info.return_value = (
        {"side": side, "positionAmt": qty} if has_position else None
    )
    return dp


def _journal(open_trades=None, total_trades=0):
    jrn = MagicMock()
    jrn.get_open_trades.return_value = open_trades or []
    jrn.get_trades.return_value = [None] * total_trades
    return jrn


def _sys(**overrides) -> dict:
    base = {
        "data_provider":        None,
        "paper_engine":          None,
        "journal_v2":            None,
        "portfolio_state":       None,
        "trade_lifecycle":       None,
        "event_bus":             MagicMock(),
        "reconciliation_engine": ReconciliationEngine(),
        "recovery_engine":       RecoveryEngine(),
    }
    base.update(overrides)
    return base


class TestSettledStates:
    def test_all_flat_is_no_position(self):
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.NO_POSITION
        assert snap.ghost_detected is False

    def test_all_agree_open_is_open(self):
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, "LONG", 0.1), journal_v2=jrn)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.OPEN

    def test_unavailable_exchange_is_unknown(self):
        s = _sys()  # no data_provider at all
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.UNKNOWN


class TestLifecycleGranularity:
    def test_executing_lifecycle_is_opening(self):
        from execution.trade_lifecycle import TradeLifecycleState as LC
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        lifecycle = MagicMock()
        lifecycle.get_state.return_value = LC.EXECUTING
        s = _sys(data_provider=_dp(True, "LONG", 0.1), journal_v2=jrn, trade_lifecycle=lifecycle)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.OPENING

    def test_exit_executing_lifecycle_is_closing(self):
        from execution.trade_lifecycle import TradeLifecycleState as LC
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        lifecycle = MagicMock()
        lifecycle.get_state.return_value = LC.EXIT_EXECUTING
        s = _sys(data_provider=_dp(True, "LONG", 0.1), journal_v2=jrn, trade_lifecycle=lifecycle)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.CLOSING

    def test_closed_lifecycle_when_flat_is_closed_not_no_position(self):
        from execution.trade_lifecycle import TradeLifecycleState as LC
        lifecycle = MagicMock()
        lifecycle.get_state.return_value = LC.CLOSED
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3), trade_lifecycle=lifecycle)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.CLOSED

    def test_lifecycle_lookup_failure_does_not_crash(self):
        lifecycle = MagicMock()
        lifecycle.get_state.side_effect = RuntimeError("boom")
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3), trade_lifecycle=lifecycle)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.NO_POSITION


class TestGhostDetection:
    """V16 Phase ORDER-01 (BUG-LIVE-ORDER-01): the reported production
    bug — Binance flat, journal empty, runtime PortfolioState cache still
    reports LONG qty=0.1062."""

    def test_stale_portfolio_state_is_ghost(self):
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.GHOST
        assert snap.ghost_detected is True
        assert snap.mismatch_type == "PRESENCE_MISMATCH"
        assert snap.runtime_position["source"] == "portfolio_state"

    def test_orphan_exchange_position_is_desync_not_ghost(self):
        """Opposite direction of the mismatch: exchange holds a real
        position nothing else knows about. Distinct from GHOST per the
        phase brief's own state list."""
        s = _sys(data_provider=_dp(True), journal_v2=_journal([], total_trades=0))
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.DESYNC
        assert snap.ghost_detected is False

    def test_side_mismatch_is_desync(self):
        jrn = _journal([{"id": 1, "direction": "SHORT", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=0.1), journal_v2=jrn)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.DESYNC


class TestEventPublishingOnTransitionOnly:
    def test_first_ghost_detection_publishes_order_state_changed_and_ghost_detected(self):
        bus = MagicMock()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5),
                  portfolio_state=ps, event_bus=bus)
        OrderStateManager().get_order_state(s, symbol="BTCUSDT")

        published = [c.args[1] for c in bus.publish.call_args_list]
        assert "ORDER_STATE_CHANGED" in published
        assert "GHOST_POSITION_DETECTED" in published

    def test_unchanged_state_does_not_republish(self):
        bus = MagicMock()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5),
                  portfolio_state=ps, event_bus=bus)
        mgr = OrderStateManager()
        mgr.get_order_state(s, symbol="BTCUSDT")
        bus.publish.reset_mock()

        mgr.get_order_state(s, symbol="BTCUSDT")

        bus.publish.assert_not_called()

    def test_recovery_transition_publishes_position_recovered(self):
        """GHOST -> NO_POSITION (recovery clears the cache between the
        two polls) publishes POSITION_RECOVERED, not POSITION_SYNCED."""
        bus = MagicMock()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5),
                  portfolio_state=ps, event_bus=bus)
        mgr = OrderStateManager()
        first = mgr.get_order_state(s, symbol="BTCUSDT")
        assert first.canonical_state == OrderState.GHOST
        bus.publish.reset_mock()

        ps.get_position.return_value = None  # recovery cleared it
        second = mgr.get_order_state(s, symbol="BTCUSDT")

        assert second.canonical_state == OrderState.NO_POSITION
        published = [c.args[1] for c in bus.publish.call_args_list]
        assert "POSITION_RECOVERED" in published
        assert "POSITION_SYNCED" not in published

    def test_settled_to_settled_transition_publishes_position_synced(self):
        """OPEN -> NO_POSITION (a clean, expected close) publishes
        POSITION_SYNCED, not POSITION_RECOVERED — recovery language is
        reserved for transitions out of GHOST/DESYNC."""
        bus = MagicMock()
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, "LONG", 0.1), journal_v2=jrn, event_bus=bus)
        mgr = OrderStateManager()
        first = mgr.get_order_state(s, symbol="BTCUSDT")
        assert first.canonical_state == OrderState.OPEN
        bus.publish.reset_mock()

        s["data_provider"] = _dp(False)
        s["journal_v2"] = _journal([], total_trades=1)
        second = mgr.get_order_state(s, symbol="BTCUSDT")

        assert second.canonical_state == OrderState.NO_POSITION
        published = [c.args[1] for c in bus.publish.call_args_list]
        assert "POSITION_SYNCED" in published
        assert "POSITION_RECOVERED" not in published

    def test_no_event_bus_does_not_crash(self):
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5),
                  portfolio_state=ps, event_bus=None)
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.GHOST


class TestMetrics:
    def test_status_counts_accumulate(self):
        mgr = OrderStateManager()
        s_flat = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))
        mgr.get_order_state(s_flat, symbol="BTCUSDT")

        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s_ghost = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)
        mgr.get_order_state(s_ghost, symbol="BTCUSDT")

        status = mgr.status()
        assert status["sync_count"] >= 1
        assert status["ghost_count"] >= 1
        assert status["last_canonical_state"] == "GHOST"


class TestSingletonFallback:
    def test_falls_back_to_process_wide_reconciliation_singleton(self):
        """When `sys` doesn't carry a reconciliation_engine (e.g. a
        thinner caller), OrderStateManager still works via
        get_reconciliation_engine()'s own singleton — same pattern
        api/app.py's existing /api/system/reconciliation endpoint uses."""
        from system_health.reconciliation import reset_reconciliation_engine
        reset_reconciliation_engine()
        s = {
            "data_provider": _dp(False),
            "journal_v2": _journal([], total_trades=5),
            "event_bus": MagicMock(),
        }
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT")
        assert snap.canonical_state == OrderState.NO_POSITION


class TestSnapshotSerialization:
    def test_to_dict_has_all_brief_required_fields(self):
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))
        snap = OrderStateManager().get_order_state(s, symbol="BTCUSDT").to_dict()
        for field in (
            "exchange_position", "runtime_position", "canonical_state",
            "last_sync", "last_exchange_update", "sync_latency_ms",
            "ghost_detected", "desync_reason",
        ):
            assert field in snap
