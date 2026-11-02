"""tests/test_v16_s98_entry_position_guard.py — V16 §98.

R-03: execute_trade() called cancel_all_orders() before entering, which also
      cancels the closePosition SL/TP of a position ALREADY open on the symbol.
Plus: the emergency close after a failed SL used the SIGNAL qty; on a partial
      fill a larger reduceOnly order is rejected and the position stays naked.
Real TradeManager; only the exchange client is faked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from config.settings import settings
from tests.test_v16_execution_idempotency import _client_error, _make_manager

pytestmark = pytest.mark.unit


def _run(client, **kw):
    m, _ = _make_manager()
    m.client = client
    with patch("execution.trade_manager.time.sleep"), \
         patch.object(m, "calculate_position_size", return_value=0.02):
        return m, m.execute_trade(direction="LONG", entry_price=50_000.0,
                                  stop_loss=49_000.0, take_profit=52_000.0,
                                  balance=10_000.0, risk_pct=0.01)


def _pos(amt, symbol="BTCUSDT"):
    return [{"symbol": symbol, "positionAmt": str(amt), "leverage": "5"}]


class TestExistingPositionGuard:

    def test_open_position_refuses_entry_and_touches_nothing(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("0.05")
        _, r = _run(c)
        assert r["success"] is False and "already has an open position" in r["error"]
        c.cancel_open_orders.assert_not_called()      # SL/TP of the live position survive
        c.new_order.assert_not_called()
        c.change_leverage.assert_not_called()
        c.change_margin_type.assert_not_called()

    def test_short_position_is_also_refused(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("-0.05")
        _, r = _run(c)
        assert r["success"] is False
        c.cancel_open_orders.assert_not_called()

    def test_flat_position_trades_as_before(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("0.000")
        c.new_order.side_effect = [
            {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50000"},
            {"orderId": 2, "status": "NEW"}, {"orderId": 3, "status": "NEW"}]
        _, r = _run(c)
        assert r["success"] is True
        c.cancel_open_orders.assert_called_once()

    def test_other_symbols_positions_are_ignored(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("3", symbol="ETHUSDT") + _pos("0")
        c.new_order.side_effect = [
            {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50000"},
            {"orderId": 2, "status": "NEW"}, {"orderId": 3, "status": "NEW"}]
        _, r = _run(c)
        assert r["success"] is True

    def test_unverifiable_lookup_keeps_legacy_behaviour(self):
        c = MagicMock()
        c.get_position_risk.side_effect = _client_error(400, -2015, "nope")
        c.new_order.side_effect = [
            {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50000"},
            {"orderId": 2, "status": "NEW"}, {"orderId": 3, "status": "NEW"}]
        _, r = _run(c)
        assert r["success"] is True

    def test_flag_off_restores_pre_s98_behaviour(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("0.05")
        c.new_order.side_effect = [
            {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50000"},
            {"orderId": 2, "status": "NEW"}, {"orderId": 3, "status": "NEW"}]
        with patch.object(settings, "ENTRY_EXISTING_POSITION_GUARD_ENABLED", False):
            _, r = _run(c)
        assert r["success"] is True
        c.cancel_open_orders.assert_called_once()


class TestEmergencyCloseUsesFilledQty:

    def test_partial_fill_then_sl_failure_closes_filled_qty(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("0")
        m, _ = _make_manager()
        m.client = c
        c.new_order.side_effect = [
            {"orderId": 1, "status": "PARTIALLY_FILLED", "executedQty": "0.005", "avgPrice": "50000"},
        ]
        with patch("execution.trade_manager.time.sleep"), \
             patch.object(m, "calculate_position_size", return_value=0.02), \
             patch.object(m, "place_stop_loss", return_value=None), \
             patch.object(m, "close_position", return_value={"orderId": 9}) as close:
            r = m.execute_trade(direction="LONG", entry_price=50_000.0,
                                stop_loss=49_000.0, take_profit=52_000.0,
                                balance=10_000.0, risk_pct=0.01)
        assert r["success"] is False
        assert close.call_args.args[1] == pytest.approx(0.005)   # not the 0.02 signal qty

    def test_unconfirmed_fill_still_closes_signal_qty(self):
        c = MagicMock()
        c.get_position_risk.return_value = _pos("0")
        m, _ = _make_manager()
        m.client = c
        c.new_order.side_effect = [{"orderId": 1, "status": "NEW"}]
        c.query_order.side_effect = _client_error(500, -1000, "boom")
        with patch("execution.trade_manager.time.sleep"), \
             patch.object(m, "calculate_position_size", return_value=0.02), \
             patch.object(m, "place_stop_loss", return_value=None), \
             patch.object(m, "close_position", return_value={"orderId": 9}) as close:
            m.execute_trade(direction="LONG", entry_price=50_000.0,
                            stop_loss=49_000.0, take_profit=52_000.0,
                            balance=10_000.0, risk_pct=0.01)
        assert close.call_args.args[1] == pytest.approx(0.02)
