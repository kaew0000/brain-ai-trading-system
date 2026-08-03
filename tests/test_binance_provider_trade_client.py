"""Regression tests for BUG-V16-BP-05.

Root cause: BinanceDataProvider.trade_client was hardcoded to always use
BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_BASE_URL, no matter what
EXECUTION_MODE / settings.BINANCE_TESTNET said. run_live.bat / run_live.sh
correctly set EXECUTION_MODE=live and BINANCE_TESTNET=false, and
execution_factory.py correctly logged "Binance LIVE", but every real order
(execution/trade_manager.py -> self.client -> data_provider.client ->
trade_client) still went to Binance Testnet — so "live" mode could never
actually reach mainnet.

These tests pin the fixed behavior: trade_client must branch on
settings.BINANCE_TESTNET (the same flag the run_* scripts already set), and
must refuse to start live with empty mainnet credentials rather than
silently sending signed requests with blank keys.
"""
import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def mock_time(monkeypatch):
    """Avoid a real network call in _sync_time_offset() during __init__."""
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": 1_700_000_000_000},
    )


def _patch_settings(monkeypatch, **overrides):
    from config.settings import settings
    for attr, value in overrides.items():
        monkeypatch.setattr(settings, attr, value)
    return settings


def test_testnet_mode_uses_testnet_credentials(monkeypatch, mock_time):
    _patch_settings(
        monkeypatch,
        BINANCE_TESTNET=True,
        BINANCE_TESTNET_API_KEY="testnet-key",
        BINANCE_TESTNET_API_SECRET="testnet-secret",
        BINANCE_TESTNET_BASE_URL="https://demo-fapi.binance.com",
        BINANCE_API_KEY="mainnet-key",
        BINANCE_API_SECRET="mainnet-secret",
        BINANCE_PROD_BASE_URL="https://fapi.binance.com",
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()

    assert dp.trade_client.base_url == "https://demo-fapi.binance.com"
    assert dp.trade_client.key == "testnet-key"
    # market data must always stay on mainnet regardless of trade mode
    assert dp.market_client.base_url == "https://fapi.binance.com"
    assert dp.market_client.key == "mainnet-key"
    assert dp.client is dp.trade_client


def test_live_mode_uses_mainnet_credentials(monkeypatch, mock_time):
    _patch_settings(
        monkeypatch,
        BINANCE_TESTNET=False,
        BINANCE_TESTNET_API_KEY="testnet-key",
        BINANCE_TESTNET_API_SECRET="testnet-secret",
        BINANCE_TESTNET_BASE_URL="https://demo-fapi.binance.com",
        BINANCE_API_KEY="mainnet-key",
        BINANCE_API_SECRET="mainnet-secret",
        BINANCE_PROD_BASE_URL="https://fapi.binance.com",
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()

    # This is the exact regression: live mode must reach mainnet, not testnet.
    assert dp.trade_client.base_url == "https://fapi.binance.com"
    assert dp.trade_client.key == "mainnet-key"
    assert dp.client is dp.trade_client


def test_live_mode_without_mainnet_keys_fails_fast(monkeypatch, mock_time):
    _patch_settings(
        monkeypatch,
        BINANCE_TESTNET=False,
        BINANCE_API_KEY="",
        BINANCE_API_SECRET="",
    )
    from data.binance_provider import BinanceDataProvider
    with pytest.raises(RuntimeError, match="BINANCE_TESTNET=false"):
        BinanceDataProvider()
