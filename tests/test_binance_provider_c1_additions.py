"""Tests for C1's additive BinanceDataProvider accessors:
get_account_snapshot(), get_open_orders(), get_server_time().

These are read-only, additive methods — no existing method's behavior is
touched by adding them.
"""
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_time(monkeypatch):
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": 1_700_000_000_000},
    )


def _make_provider(monkeypatch, mock_time):
    from config.settings import settings
    monkeypatch.setattr(settings, "BINANCE_TESTNET", True)
    from data.binance_provider import BinanceDataProvider
    return BinanceDataProvider()


def test_get_account_snapshot_parses_totals_and_filters_zero_positions(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    dp.trade_client.account = lambda **kw: {
        "totalWalletBalance": "1000.0",
        "availableBalance": "500.0",
        "totalUnrealizedProfit": "50.0",
        "totalMarginBalance": "1050.0",
        "totalMaintMargin": "10.0",
        "totalInitialMargin": "20.0",
        "positions": [
            {
                "symbol": "BTCUSDT", "positionAmt": "0.1062",
                "entryPrice": "65664.78", "markPrice": "65000.0",
                "unrealizedProfit": "-70.0", "leverage": "5",
                "marginType": "isolated", "liquidationPrice": "40000.0",
            },
            {"symbol": "ETHUSDT", "positionAmt": "0.0"},  # must be filtered out
        ],
    }

    snap = dp.get_account_snapshot()
    assert snap["wallet_balance"] == 1000.0
    assert snap["available_balance"] == 500.0
    assert snap["unrealized_pnl"] == 50.0
    assert len(snap["positions"]) == 1
    pos = snap["positions"][0]
    assert pos["symbol"] == "BTCUSDT"
    assert pos["side"] == "LONG"
    assert pos["quantity"] == pytest.approx(0.1062)
    assert pos["entry_price"] == 65664.78


def test_get_account_snapshot_short_side(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    dp.trade_client.account = lambda **kw: {
        "totalWalletBalance": "1000.0", "availableBalance": "500.0",
        "totalUnrealizedProfit": "0.0", "totalMarginBalance": "1000.0",
        "totalMaintMargin": "0.0", "totalInitialMargin": "0.0",
        "positions": [
            {"symbol": "BTCUSDT", "positionAmt": "-0.5", "entryPrice": "60000.0",
             "markPrice": "59000.0", "unrealizedProfit": "500.0", "leverage": "3",
             "marginType": "isolated", "liquidationPrice": "70000.0"},
        ],
    }
    snap = dp.get_account_snapshot()
    assert snap["positions"][0]["side"] == "SHORT"
    assert snap["positions"][0]["quantity"] == 0.5


def test_get_open_orders_no_symbol(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    calls = {}

    def fake_get_orders(**kw):
        calls.update(kw)
        return [{
            "symbol": "BTCUSDT", "orderId": 123, "clientOrderId": "sl-1",
            "side": "SELL", "type": "STOP_MARKET", "status": "NEW",
            "stopPrice": "49000.0", "origQty": "0.1", "executedQty": "0.0",
            "reduceOnly": True,
        }]

    dp.trade_client.get_orders = fake_get_orders
    orders = dp.get_open_orders()
    assert calls == {"recvWindow": 5000}
    assert len(orders) == 1
    assert orders[0]["order_id"] == 123
    assert orders[0]["reduce_only"] is True


def test_get_open_orders_with_symbol_filters_request(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    calls = {}

    def fake_get_orders(**kw):
        calls.update(kw)
        return []

    dp.trade_client.get_orders = fake_get_orders
    dp.get_open_orders(symbol="BTCUSDT")
    assert calls == {"recvWindow": 5000, "symbol": "BTCUSDT"}


def test_get_server_time(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    dp.market_client.time = lambda: {"serverTime": 1690000000000}
    assert dp.get_server_time() == 1690000000000
