"""tests/test_binance_provider_hft1_additions.py — V16 Phase 4C Track B, HFT-1.

Tests for the additive BinanceDataProvider.get_order_book_snapshot() REST
wrapper (used by data/local_order_book.py / data/binance_ws_client.py for
initial sync and gap-resync) and the config.settings.Settings.hft_ws_url
property. Both are read-only/additive — no existing method's behavior is
touched by adding them, matching the existing C1-additions test file's own
stated scope.
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


def test_get_order_book_snapshot_returns_raw_binance_shape(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    dp.market_client.depth = lambda **kw: {
        "lastUpdateId": 12345,
        "bids": [["100.00", "1.0"], ["99.50", "2.0"]],
        "asks": [["100.50", "1.0"], ["101.00", "2.0"]],
    }
    result = dp.get_order_book_snapshot(symbol="BTCUSDT")
    assert result["lastUpdateId"] == 12345
    assert result["bids"][0] == ["100.00", "1.0"]


def test_get_order_book_snapshot_passes_symbol_and_limit(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    captured = {}

    def fake_depth(**kw):
        captured.update(kw)
        return {"lastUpdateId": 1, "bids": [], "asks": []}

    dp.market_client.depth = fake_depth
    dp.get_order_book_snapshot(symbol="ETHUSDT", limit=500)
    assert captured == {"symbol": "ETHUSDT", "limit": 500}


def test_get_order_book_snapshot_defaults_to_provider_symbol(monkeypatch, mock_time):
    dp = _make_provider(monkeypatch, mock_time)
    captured = {}

    def fake_depth(**kw):
        captured.update(kw)
        return {"lastUpdateId": 1, "bids": [], "asks": []}

    dp.market_client.depth = fake_depth
    dp.get_order_book_snapshot()
    assert captured["symbol"] == dp.symbol
    assert captured["limit"] == 1000   # default


def test_get_order_book_snapshot_propagates_client_error(monkeypatch, mock_time):
    from binance.error import ClientError

    dp = _make_provider(monkeypatch, mock_time)

    def raise_error(**kw):
        raise ClientError(400, -1121, "Invalid symbol.", {})

    dp.market_client.depth = raise_error
    with pytest.raises(ClientError):
        dp.get_order_book_snapshot(symbol="BADSYMBOL")


def test_hft_ws_url_uses_testnet_host_when_testnet_true(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "BINANCE_TESTNET", True)
    assert settings.hft_ws_url == settings.HFT_WS_TESTNET_BASE_URL


def test_hft_ws_url_uses_mainnet_host_when_testnet_false(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "BINANCE_TESTNET", False)
    assert settings.hft_ws_url == settings.HFT_WS_BASE_URL


def test_hft_ws_enabled_defaults_to_false():
    from config.settings import settings
    assert settings.HFT_WS_ENABLED is False
