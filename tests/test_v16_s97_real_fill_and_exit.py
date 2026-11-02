"""tests/test_v16_s97_real_fill_and_exit.py — V16 §97.

R-02: the journal stored the SIGNAL price/qty, not what the exchange filled
      (USDS-M MARKET orders are acked before they are priced).
R-01: monitor_open_trades() decided WIN/LOSS from the mark price at check
      time (TP hit + pullback before the next check ⇒ recorded LOSS) and
      ignored fees.
Plus the §96 regression: a pass where every OPEN row was healed by
`qty<=0 → continue` left result/pnl unbound for the mission-close block.

Real functions throughout; only the exchange client is faked.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

import main as main_module
from journal.journal_v2 import TradeRecord
from config.settings import settings
from portfolio.portfolio_models import PortfolioPosition, PositionState
from journal.exit_truth import resolve_realized_exit
from tests.test_natural_close_portfolio_release import _DataProvider, _Rig
from tests.test_v16_execution_idempotency import _client_error, _make_manager

pytestmark = pytest.mark.unit


def _fill(i, side, price, qty, t, *, pnl="0", fee="0.05", asset="USDT"):
    return {"id": i, "side": side, "price": str(price), "qty": str(qty), "time": t,
            "realizedPnl": str(pnl), "commission": str(fee), "commissionAsset": asset}


class _Client:
    """Fake USD-M client: orderId-filtered call returns the entry fills,
    startTime call returns everything on or after that time."""
    def __init__(self, entry_fills, all_fills):
        self.entry_fills, self.all_fills = entry_fills, all_fills
        self.calls = []

    def get_account_trades(self, **kw):
        self.calls.append(kw)
        if "orderId" in kw:
            return self.entry_fills
        return [f for f in self.all_fills if f["time"] >= kw["startTime"]]


ENTRY = [_fill(1, "BUY", 100, 2, 1000, fee="0.08")]


class TestResolveRealizedExit:

    def test_long_take_profit_is_a_win_net_of_fees(self):
        c = _Client(ENTRY, ENTRY + [_fill(2, "SELL", 120, 2, 2000, pnl="40", fee="0.096")])
        r = resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0)
        assert r["result"] == "WIN"
        assert r["exit_price"] == 120.0
        assert r["gross_pnl"] == 40.0
        assert r["fees"] == pytest.approx(0.176)
        assert r["pnl"] == pytest.approx(39.824)

    def test_long_stop_loss_is_a_loss(self):
        c = _Client(ENTRY, ENTRY + [_fill(2, "SELL", 90, 2, 2000, pnl="-20", fee="0.072")])
        r = resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0)
        assert r["result"] == "LOSS" and r["pnl"] < -20.0

    def test_short_uses_buy_side_to_close(self):
        entry = [_fill(1, "SELL", 100, 2, 1000)]
        c = _Client(entry, entry + [_fill(2, "BUY", 80, 2, 2000, pnl="40")])
        r = resolve_realized_exit(c, "ETHUSDT", "SHORT", "100", 2.0)
        assert r["result"] == "WIN" and r["exit_price"] == 80.0

    def test_scale_out_closing_is_weighted_average(self):
        c = _Client(ENTRY, ENTRY + [
            _fill(2, "SELL", 110, 1, 2000, pnl="10"),
            _fill(3, "SELL", 130, 1, 3000, pnl="30"),
        ])
        r = resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0)
        assert r["exit_price"] == 120.0 and r["closing_fills"] == 2

    def test_later_trade_on_same_symbol_is_not_attributed(self):
        # Trade closed at 2000; a NEW trade opened (BUY) and closed (SELL @ 50)
        # afterwards. Only the first closing SELL belongs to this trade.
        c = _Client(ENTRY, ENTRY + [
            _fill(2, "SELL", 120, 2, 2000, pnl="40"),
            _fill(3, "BUY", 60, 2, 3000),
            _fill(4, "SELL", 50, 2, 4000, pnl="-20"),
        ])
        r = resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0)
        assert r["exit_price"] == 120.0 and r["result"] == "WIN"

    def test_fills_before_the_entry_are_ignored(self):
        c = _Client(ENTRY, [_fill(0, "SELL", 500, 2, 500, pnl="999")] + ENTRY
                    + [_fill(2, "SELL", 120, 2, 2000, pnl="40")])
        r = resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0)
        assert r["gross_pnl"] == 40.0

    @pytest.mark.parametrize("entry_id", [None, "", "abc"])
    def test_no_usable_entry_order_id_returns_none(self, entry_id):
        assert resolve_realized_exit(_Client(ENTRY, ENTRY), "ETHUSDT", "LONG", entry_id, 2.0) is None

    def test_position_not_fully_closed_returns_none(self):
        c = _Client(ENTRY, ENTRY + [_fill(2, "SELL", 120, 1, 2000, pnl="20")])
        assert resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0) is None

    def test_api_error_returns_none_and_never_raises(self):
        c = MagicMock()
        c.get_account_trades.side_effect = _client_error(500, -1000, "boom")
        assert resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0) is None

    def test_non_quote_commission_asset_keeps_gross_pnl(self):
        c = _Client(ENTRY, ENTRY + [_fill(2, "SELL", 120, 2, 2000, pnl="40", asset="BNB")])
        r = resolve_realized_exit(c, "ETHUSDT", "LONG", "100", 2.0)
        assert r["fees"] is None and r["pnl"] == 40.0


class _FillsDataProvider(_DataProvider):
    def __init__(self, marks, client, open_symbols=()):
        super().__init__(marks, open_symbols)
        self.client = client


def _open_with_order_id(rig, symbol, order_id, *, entry=100.0, sl=90.0, tp=120.0, qty=2.0):
    """Same as _Rig.open() but with the entry order id journaled (as
    TradeRecord.from_decision does in production)."""
    rec = TradeRecord()
    rec.timestamp, rec.symbol, rec.direction = "2026-11-01T00:00:00", symbol, "LONG"
    rec.entry_price, rec.stop_loss, rec.take_profit, rec.quantity = entry, sl, tp, qty
    rec.order_id = str(order_id)
    tid = rig.jrn.save_trade(rec, execution_lane="LIVE")
    handle = rig.lc.open_pending(symbol)
    rig.lc.open_executing(handle)
    rig.lc.open_confirmed(handle, tid, source="EXECUTION_ORCHESTRATOR")
    rig.state.add_position(PortfolioPosition(
        symbol=symbol, direction="LONG", entry_price=entry, quantity=qty, leverage=5,
        notional=entry * qty, margin_used=entry * qty / 5, unrealized_pnl=0.0,
        state=PositionState.OPEN, opened_at=time.time(), trade_id=tid,
    ))
    return tid


def _row(jrn, tid):
    with jrn._conn() as c:
        return dict(c.execute("SELECT result, pnl, exit_price FROM trades WHERE id=?", (tid,)).fetchone())


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
    return _Rig(tmp_path)


class TestMonitorUsesRealOutcome:

    def test_tp_hit_then_pullback_is_still_a_win(self, rig):
        """The R-01 case: TP filled at 120, price then fell back to 80 before
        the monitor's next check. Heuristic ⇒ LOSS; exchange fills ⇒ WIN."""
        tid = _open_with_order_id(rig, "ETHUSDT", 100)
        client = _Client(ENTRY, ENTRY + [_fill(2, "SELL", 120, 2, 2000, pnl="40", fee="0.096")])
        main_module.monitor_open_trades(rig.sys(_FillsDataProvider({"ETHUSDT": 80.0}, client)))
        row = _row(rig.jrn, tid)
        assert row["result"] == "WIN"
        assert row["exit_price"] == 120.0
        assert row["pnl"] == pytest.approx(39.824)
        assert rig.jrn.get_consecutive_losses(execution_lane="LIVE") == 0

    def test_falls_back_to_mark_heuristic_when_fills_unavailable(self, rig):
        tid = _open_with_order_id(rig, "ETHUSDT", 100)
        client = MagicMock()
        client.get_account_trades.side_effect = _client_error(500, -1000, "boom")
        main_module.monitor_open_trades(rig.sys(_FillsDataProvider({"ETHUSDT": 89.4}, client)))
        row = _row(rig.jrn, tid)
        assert row["result"] == "LOSS" and row["exit_price"] == 89.4

    def test_data_provider_without_client_still_uses_fallback(self, rig):
        tid = _open_with_order_id(rig, "ETHUSDT", 100)
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 89.4})))
        assert _row(rig.jrn, tid)["result"] == "LOSS"


class TestAllRowsHealedLeavesMissionAlone:
    """§96 side effect: when EVERY OPEN row was healed by `qty<=0 → continue`,
    result/pnl were unbound, the mission-close block's f-string raised
    UnboundLocalError (swallowed at debug level) and its `finally` still
    cleared current_mission_id — dropping the live mission without ever
    recording a close. Healing a phantom row must not touch the mission."""

    def test_current_mission_is_not_cleared(self, rig):
        rig.open("ETHUSDT", qty=0.0)
        tracker = MagicMock()
        system = rig.sys(_DataProvider({"ETHUSDT": 80.0}),
                         mission_tracker=tracker, current_mission_id="m1")
        main_module.monitor_open_trades(system)
        assert system["current_mission_id"] == "m1"
        tracker.advance.assert_not_called()


class TestEntryFillReadBack:

    def _run(self, client, **kw):
        m, _ = _make_manager()
        m.client = client
        with patch("execution.trade_manager.time.sleep"), \
             patch.object(m, "calculate_position_size", return_value=0.02):
            return m.execute_trade(direction=kw.get("direction", "LONG"),
                                   entry_price=50_000.0, stop_loss=49_000.0,
                                   take_profit=52_000.0, balance=10_000.0, risk_pct=0.01)

    def _client(self, entry_ack, queried=None):
        c = MagicMock()
        c.new_order.side_effect = [entry_ack, {"orderId": 2, "status": "NEW"},
                                   {"orderId": 3, "status": "NEW"}]
        if queried is not None:
            c.query_order.side_effect = queried if isinstance(queried, list) else [queried]
        return c

    def test_ack_only_response_is_resolved_via_query_order(self):
        c = self._client({"orderId": 1, "status": "NEW"},
                         {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50010.0"})
        r = self._run(c)
        assert r["success"] and r["fill_confirmed"]
        assert r["fill_price"] == 50010.0 and r["filled_qty"] == 0.02
        assert r["slippage_pct"] == pytest.approx(0.02)       # LONG paid 10 more on 50 000

    def test_short_slippage_sign(self):
        c = self._client({"orderId": 1, "status": "NEW"},
                         {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "49990.0"})
        r = self._run(c, direction="SHORT")
        assert r["slippage_pct"] == pytest.approx(0.02)       # SHORT received 10 less ⇒ worse

    def test_priced_response_needs_no_query(self):
        c = self._client({"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50000.5"})
        r = self._run(c)
        assert r["fill_confirmed"] and r["fill_price"] == 50000.5
        c.query_order.assert_not_called()

    def test_still_in_flight_is_polled_then_confirmed(self):
        c = self._client({"orderId": 1, "status": "NEW"}, [
            {"orderId": 1, "status": "NEW", "executedQty": "0", "avgPrice": "0"},
            {"orderId": 1, "status": "FILLED", "executedQty": "0.02", "avgPrice": "50001.0"},
        ])
        r = self._run(c)
        assert r["fill_confirmed"] and r["fill_price"] == 50001.0

    def test_unreadable_fill_does_not_block_the_trade(self):
        c = self._client({"orderId": 1, "status": "NEW"})
        c.query_order.side_effect = _client_error(500, -1000, "boom")
        r = self._run(c)
        assert r["success"] and r["fill_confirmed"] is False and r["fill_price"] is None

    def test_terminal_unfilled_entry_aborts_before_sl(self):
        c = self._client({"orderId": 1, "status": "NEW"},
                         {"orderId": 1, "status": "EXPIRED", "executedQty": "0", "avgPrice": "0"})
        r = self._run(c)
        assert r["success"] is False and "not filled" in r["error"]
        assert c.new_order.call_count == 1                    # entry only — no SL/TP attempted


class TestJournalRecordsRealFill:

    def _decision(self):
        d = MagicMock()
        d.direction, d.regime, d.oi_delta, d.funding_rate = "LONG", "TREND", 0.01, 0.0001
        d.confidence, d.score = 0.78, 7
        d.entry_price, d.stop_loss, d.take_profit = 50_000.0, 49_500.0, 51_000.0
        d.mtf_aligned, d.block_reasons = True, []
        return d

    def _rec(self, execution):
        from features.smc_engine import SMCSignals
        from features.volume_engine import VolumeSignals
        with patch("analytics.trade_journal.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            return TradeRecord.from_decision(self._decision(), SMCSignals(), VolumeSignals(),
                                             execution=execution)

    def test_confirmed_fill_overrides_signal_price_and_qty(self):
        rec = self._rec({"success": True, "quantity": 0.02, "entry_order": {"orderId": 7},
                         "fill_confirmed": True, "fill_price": 50_012.5, "filled_qty": 0.019})
        assert rec.entry_price == 50_012.5 and rec.quantity == 0.019 and rec.order_id == "7"

    def test_unconfirmed_fill_keeps_signal_price(self):
        rec = self._rec({"success": True, "quantity": 0.02, "entry_order": {"orderId": 7},
                         "fill_confirmed": False})
        assert rec.entry_price == 50_000.0 and rec.quantity == 0.02
