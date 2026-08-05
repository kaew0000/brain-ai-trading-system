"""
tests/test_recovery_engine.py

system_health/recovery_engine.py had NO test coverage at all before this
file (confirmed by inspection: no test_recovery_engine.py, no references
to RecoveryEngine in any other test module). This file covers:

  - The pre-existing "ghost journal row" recovery path (was previously
    completely untested — this is net-new coverage, not a regression
    guard for something that was already verified).
  - V16 BUG-LIVE-RISK-02: the opposite case — a real exchange position
    with no journal record. Previously fell through to
    "no_safe_auto_action" silently. Now auto-protects with an SL and
    holds new entries until a human acknowledges.

All tests use a fresh RecoveryEngine() instance (not the process-wide
singleton) so state never leaks between tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


@dataclass
class _FakeEvent:
    mismatch_type: str
    exchange_view: dict
    journal_view: dict
    bot_view: dict


def _sys(**overrides) -> dict:
    base = {
        "data_provider": MagicMock(),
        "trade_manager":  MagicMock(),
        "risk_engine":    MagicMock(),
        "event_bus":      MagicMock(),
        "journal_v2":     MagicMock(),
        "trade_lifecycle": None,
    }
    base.update(overrides)
    return base


class TestNonPresenceMismatch:
    def test_non_presence_mismatch_skips_recovery(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        evt = _FakeEvent("QTY_MISMATCH", {}, {}, {})
        result = eng.attempt_reconciliation_recovery(evt, _sys())
        assert result == "no_auto_recovery_for:QTY_MISMATCH"


class TestGhostJournalRow:
    """Exchange flat, journal thinks it's open — previously-existing path,
    now getting its first-ever test coverage."""

    def test_ghost_row_closed_via_lifecycle(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        lifecycle = MagicMock()
        lifecycle.request_exit.return_value = "handle-123"
        s = _sys(trade_lifecycle=lifecycle)
        evt = _FakeEvent(
            "PRESENCE_MISMATCH",
            exchange_view={"has_position": False},
            journal_view={"has_position": True, "trade_id": 42},
            bot_view={"has_position": False},
        )
        result = eng.attempt_reconciliation_recovery(evt, s)
        assert result == "closed_ghost_journal_row"
        lifecycle.request_exit.assert_called_once()
        lifecycle.exit_executing.assert_called_once_with("handle-123")
        lifecycle.exit_confirmed.assert_called_once()

    def test_ghost_row_missing_trade_id_is_safe_noop(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        evt = _FakeEvent(
            "PRESENCE_MISMATCH",
            exchange_view={"has_position": False},
            journal_view={"has_position": True, "trade_id": None},
            bot_view={"has_position": False},
        )
        result = eng.attempt_reconciliation_recovery(evt, _sys())
        assert result == "missing_journal_or_trade_id"


class TestOrphanedExchangePosition:
    """V16 BUG-LIVE-RISK-02: exchange has a real position, journal has
    nothing on it at all."""

    def _evt(self):
        return _FakeEvent(
            "PRESENCE_MISMATCH",
            exchange_view={"has_position": True, "side": "LONG", "qty": 0.05},
            journal_view={"has_position": False},
            bot_view={"has_position": True, "side": "LONG", "qty": 0.05},
        )

    def _position(self, **overrides):
        p = {
            "symbol": "BTCUSDT", "side": "LONG", "positionAmt": 0.05,
            "entryPrice": 67000.0, "markPrice": 67100.0, "leverage": 5,
        }
        p.update(overrides)
        return p

    def test_auto_protects_and_holds_on_success(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = self._position()
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock()
        tm.place_stop_loss.return_value = {"orderId": 1, "status": "NEW"}
        risk = MagicMock()
        risk.has_manual_hold.return_value = False
        bus = MagicMock()
        s = _sys(data_provider=dp, trade_manager=tm, risk_engine=risk, event_bus=bus)

        result = eng.attempt_reconciliation_recovery(self._evt(), s)

        assert result == "orphan_sl_placed_and_holding"
        tm.place_stop_loss.assert_called_once()
        # LONG position -> protective SL must be placed BELOW entry price.
        args, kwargs = tm.place_stop_loss.call_args
        stop_price = args[2] if len(args) > 2 else kwargs["stop_price"]
        assert stop_price < 67000.0
        risk.set_manual_hold.assert_called_once()
        bus.publish.assert_called_once()
        assert bus.publish.call_args.kwargs.get("severity") == "critical"
        assert eng.get_orphan_hold() is not None
        assert eng.get_orphan_hold()["symbol"] == "BTCUSDT"
        assert eng.get_orphan_hold()["sl_placed"] is True

    def test_short_position_sl_placed_above_entry(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = self._position(side="SHORT")
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock()
        tm.place_stop_loss.return_value = {"orderId": 1, "status": "NEW"}
        s = _sys(data_provider=dp, trade_manager=tm)

        evt = _FakeEvent(
            "PRESENCE_MISMATCH",
            exchange_view={"has_position": True, "side": "SHORT", "qty": 0.05},
            journal_view={"has_position": False},
            bot_view={"has_position": True, "side": "SHORT", "qty": 0.05},
        )
        eng.attempt_reconciliation_recovery(evt, s)

        args, kwargs = tm.place_stop_loss.call_args
        stop_price = args[2] if len(args) > 2 else kwargs["stop_price"]
        assert stop_price > 67000.0

    def test_still_holds_when_sl_placement_fails(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = self._position()
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock()
        tm.place_stop_loss.return_value = None  # exchange rejected it
        risk = MagicMock()
        s = _sys(data_provider=dp, trade_manager=tm, risk_engine=risk)

        result = eng.attempt_reconciliation_recovery(self._evt(), s)

        assert result == "orphan_sl_failed_still_holding"
        risk.set_manual_hold.assert_called_once()   # still held despite failed SL
        assert eng.get_orphan_hold()["sl_placed"] is False

    def test_does_not_reattempt_sl_once_already_held(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = self._position()
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock()
        tm.place_stop_loss.return_value = {"orderId": 1, "status": "NEW"}
        risk = MagicMock()
        risk.has_manual_hold.return_value = True
        s = _sys(data_provider=dp, trade_manager=tm, risk_engine=risk)

        eng.attempt_reconciliation_recovery(self._evt(), s)   # 1st: places SL
        result = eng.attempt_reconciliation_recovery(self._evt(), s)  # 2nd: same position again

        assert result == "orphan_already_held"
        assert tm.place_stop_loss.call_count == 1  # not called a second time

    def test_position_closed_between_read_and_recovery(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = None
        s = _sys(data_provider=dp)

        result = eng.attempt_reconciliation_recovery(self._evt(), s)

        assert result == "position_no_longer_open"
        assert eng.get_orphan_hold() is None

    def test_missing_trade_manager_is_safe_noop(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        s = _sys(trade_manager=None)
        result = eng.attempt_reconciliation_recovery(self._evt(), s)
        assert result == "missing_data_provider_or_trade_manager"


class TestAcknowledgeOrphanedPosition:
    def test_no_hold_active(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        result = eng.acknowledge_orphaned_position(sys=_sys(), operator="nanthachai")
        assert result == "no_hold_active"

    def test_acknowledge_clears_hold_and_risk_engine(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = {
            "symbol": "BTCUSDT", "side": "LONG", "positionAmt": 0.05,
            "entryPrice": 67000.0, "markPrice": 67100.0, "leverage": 5,
        }
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock()
        tm.place_stop_loss.return_value = {"orderId": 1, "status": "NEW"}
        risk = MagicMock()
        s = _sys(data_provider=dp, trade_manager=tm, risk_engine=risk)
        evt = _FakeEvent(
            "PRESENCE_MISMATCH",
            exchange_view={"has_position": True, "side": "LONG", "qty": 0.05},
            journal_view={"has_position": False},
            bot_view={"has_position": True, "side": "LONG", "qty": 0.05},
        )
        eng.attempt_reconciliation_recovery(evt, s)
        assert eng.get_orphan_hold() is not None

        result = eng.acknowledge_orphaned_position(sys=s, operator="nanthachai")

        assert result == "cleared"
        assert eng.get_orphan_hold() is None
        risk.clear_manual_hold.assert_called_once()

    def test_get_orphan_hold_returns_a_copy_not_live_reference(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = {
            "symbol": "BTCUSDT", "side": "LONG", "positionAmt": 0.05,
            "entryPrice": 67000.0, "markPrice": 67100.0, "leverage": 5,
        }
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock()
        tm.place_stop_loss.return_value = {"orderId": 1, "status": "NEW"}
        s = _sys(data_provider=dp, trade_manager=tm)
        evt = _FakeEvent(
            "PRESENCE_MISMATCH",
            exchange_view={"has_position": True, "side": "LONG", "qty": 0.05},
            journal_view={"has_position": False},
            bot_view={"has_position": True, "side": "LONG", "qty": 0.05},
        )
        eng.attempt_reconciliation_recovery(evt, s)

        snapshot = eng.get_orphan_hold()
        snapshot["symbol"] = "MUTATED"
        assert eng.get_orphan_hold()["symbol"] == "BTCUSDT"
