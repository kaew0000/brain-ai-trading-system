"""tests/test_v16_s96_failed_trade_phantom_loss.py — V16 §96.

BUG-S96-01/02: a failed execution was journaled as result="OPEN" with
quantity 0; monitor_open_trades() then saw "OPEN row, no exchange position"
and settled it as a phantom LOSS, which get_consecutive_losses() counted —
so failed ORDERS (not losing trades) could trip the consecutive-loss gate.
BUG-S96-03: a failed emergency close was reported as "closed for safety".
BUG-S96-04: futures duplicate-clientOrderId (-4116) was not recognised.

Real production functions, real TradeJournalV2 on a temp SQLite file; only
the exchange is faked (same approach as test_natural_close_portfolio_release).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from binance.error import ClientError

import main as main_module
from analytics.trade_journal import TradeRecord as V1Record
from config.settings import settings
from tests.test_natural_close_portfolio_release import _DataProvider, _Rig
from tests.test_v16_execution_idempotency import _client_error, _make_manager

pytestmark = pytest.mark.unit


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
    return _Rig(tmp_path)


def _row(jrn, tid):
    with jrn._conn() as c:
        return dict(c.execute("SELECT result, pnl, quantity FROM trades WHERE id=?", (tid,)).fetchone())


class TestFailedExecutionIsNotJournaledOpen:

    def test_helper_cancels_failed_execution(self):
        rec = V1Record()
        assert rec.result == "OPEN"
        main_module._apply_execution_outcome_to_record(rec, {"success": False, "error": "x"})
        assert rec.result == "CANCELLED"

    def test_helper_leaves_successful_execution_open(self):
        rec = V1Record()
        main_module._apply_execution_outcome_to_record(rec, {"success": True})
        assert rec.result == "OPEN"

    def test_cancelled_row_is_never_settled_or_counted(self, rig):
        rec = V1Record()
        rec.timestamp, rec.symbol, rec.direction = "2026-11-01T00:00:00", "ETHUSDT", "LONG"
        rec.entry_price, rec.stop_loss, rec.take_profit = 100.0, 90.0, 120.0
        main_module._apply_execution_outcome_to_record(rec, {"success": False})
        tid = rig.jrn.save_trade(rec, execution_lane="LIVE")
        assert rig.jrn.get_open_trades() == []
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 80.0})))
        assert _row(rig.jrn, tid)["result"] == "CANCELLED"
        assert rig.jrn.get_consecutive_losses(execution_lane="LIVE") == 0


class TestMonitorHealsNeverFilledOpenRows:

    def test_qty_zero_open_row_becomes_cancelled_not_loss(self, rig):
        tid = rig.open("ETHUSDT", qty=0.0)          # legacy phantom row
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 80.0})))
        row = _row(rig.jrn, tid)
        assert row["result"] == "CANCELLED" and row["pnl"] == 0.0
        assert rig.jrn.get_consecutive_losses(execution_lane="LIVE") == 0

    def test_three_failed_orders_do_not_trip_loss_streak(self, rig):
        for _ in range(3):
            rig.open("ETHUSDT", qty=0.0)
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 80.0})))
        assert rig.jrn.get_consecutive_losses(execution_lane="LIVE") == 0

    def test_real_filled_trade_still_settles_as_loss(self, rig):
        tid = rig.open("ETHUSDT", qty=2.0)          # sl=90, mark below it
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 89.4})))
        assert _row(rig.jrn, tid)["result"] == "LOSS"
        assert rig.jrn.get_consecutive_losses(execution_lane="LIVE") == 1


class TestEmergencyCloseResultIsChecked:

    def _run(self, close_side_effect):
        m, client = _make_manager()
        tier_fail = _client_error(400, -4120, "Order's type is not supported.")
        client.new_order.side_effect = [
            {"orderId": 20, "status": "FILLED"},        # entry
            tier_fail, tier_fail, tier_fail,            # SL: every tier fails
            close_side_effect,                          # emergency close
        ]
        with patch("execution.trade_manager.time.sleep"):
            return m.execute_trade(
                direction="LONG", entry_price=50_000.0, stop_loss=49_000.0,
                take_profit=52_000.0, balance=1_000.0, risk_pct=0.01,
            )

    def test_failed_close_is_reported_as_naked_position(self):
        result = self._run(_client_error(400, -2022, "ReduceOnly Order is rejected."))
        assert result["success"] is False
        assert "NAKED POSITION STILL OPEN" in result["error"]
        assert result["naked_position_open"] is True

    def test_successful_close_message_unchanged(self):
        result = self._run({"orderId": 21, "status": "FILLED"})
        assert "naked position closed for safety" in result["error"]
        assert "naked_position_open" not in result


class TestFuturesDuplicateClientOrderId:

    def test_minus_4116_is_recovered_via_query_order(self):
        m, client = _make_manager()
        client.new_order.side_effect = ClientError(400, -4116, "ClientOrderId is duplicated.", {})
        client.query_order.return_value = {"orderId": 9, "status": "FILLED"}
        with patch("execution.trade_manager.time.sleep"):
            order = m.place_market_order("LONG", 0.01, client_order_id="bbENTRYtest")
        assert order == {"orderId": 9, "status": "FILLED"}
        client.query_order.assert_called_once()
