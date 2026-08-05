import dataclasses
import pytest

from exchange_state.models import (
    AccountSnapshot, PositionSnapshot, OrderSnapshot, ExchangeSnapshot,
)

pytestmark = pytest.mark.unit


def test_position_snapshot_is_frozen():
    p = PositionSnapshot(
        symbol="BTCUSDT", side="LONG", quantity=0.1, entry_price=65000.0,
        mark_price=65500.0, unrealized_pnl=50.0, leverage=5,
        margin_type="ISOLATED", liquidation_price=40000.0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.quantity = 0.2


def test_order_snapshot_is_sl_is_tp():
    sl = OrderSnapshot(
        symbol="BTCUSDT", order_id=1, client_order_id="sl-1", side="SELL",
        type="STOP_MARKET", status="NEW", stop_price=49000.0, orig_qty=0.1,
        executed_qty=0.0, reduce_only=True,
    )
    tp = OrderSnapshot(
        symbol="BTCUSDT", order_id=2, client_order_id="tp-1", side="SELL",
        type="TAKE_PROFIT_MARKET", status="NEW", stop_price=70000.0,
        orig_qty=0.1, executed_qty=0.0, reduce_only=True,
    )
    plain = OrderSnapshot(
        symbol="BTCUSDT", order_id=3, client_order_id="x", side="BUY",
        type="LIMIT", status="NEW", stop_price=0.0, orig_qty=0.1,
        executed_qty=0.0, reduce_only=False,
    )
    assert sl.is_sl and not sl.is_tp
    assert tp.is_tp and not tp.is_sl
    assert not plain.is_sl and not plain.is_tp


def test_order_snapshot_not_reduce_only_is_neither():
    fake_sl = OrderSnapshot(
        symbol="BTCUSDT", order_id=4, client_order_id="x", side="SELL",
        type="STOP_MARKET", status="NEW", stop_price=49000.0, orig_qty=0.1,
        executed_qty=0.0, reduce_only=False,
    )
    assert not fake_sl.is_sl


def test_exchange_snapshot_open_position_count_and_lookup():
    account = AccountSnapshot(
        wallet_balance=1000.0, available_balance=500.0, unrealized_pnl=0.0,
        total_margin_balance=1000.0, maintenance_margin=0.0, initial_margin=0.0,
    )
    pos = PositionSnapshot(
        symbol="BTCUSDT", side="LONG", quantity=0.1, entry_price=65000.0,
        mark_price=65500.0, unrealized_pnl=50.0, leverage=5,
        margin_type="ISOLATED", liquidation_price=40000.0,
    )
    snap = ExchangeSnapshot(
        mode="paper", exchange="binance", account_id="default",
        account=account, positions={"BTCUSDT": pos},
    )
    assert snap.open_position_count == 1
    assert snap.get_position("BTCUSDT") is pos
    assert snap.get_position("ETHUSDT") is None


def test_exchange_snapshot_defaults():
    account = AccountSnapshot(0, 0, 0, 0, 0, 0)
    snap = ExchangeSnapshot(mode="live", exchange="binance", account_id="default", account=account)
    assert snap.positions == {}
    assert snap.orders == ()
    assert snap.degraded is False
    assert snap.health_score == 100
