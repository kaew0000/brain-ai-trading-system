"""Regression tests for fix/live-balance-zero-diagnostics.

Root cause: get_account_balance() silently returned 0.0 with no log
line at any level when trade_client.balance()'s response contained no
"USDT" entry -- indistinguishable in logs/brain_bot.log from a
genuinely empty account, and the cause of every live order this bot
ever attempted being skipped by trade_manager.py's minQty guard (see
PATCH_NOTES.md for the production log evidence).

These tests pin the fixed behavior: the empty-match branch must log a
WARNING (assert the call happens -- not its exact wording, since
that's an implementation detail this test shouldn't be brittle
against), and the success path must log at INFO instead of DEBUG so a
healthy read is visible in a normal INFO-level production log too.

Mirrors tests/test_binance_provider_trade_client.py's fixture style
(mock_time avoids a real network call in __init__'s
_sync_time_offset(); _patch_settings monkeypatches config.settings.settings).
"""
from unittest.mock import MagicMock

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


@pytest.fixture
def dp(monkeypatch, mock_time):
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
    return BinanceDataProvider()


def test_no_usdt_entry_logs_warning_and_returns_zero(monkeypatch, dp):
    """The exact production failure mode: balance() succeeds but its
    response has no 'USDT' entry. Must warn loudly instead of silently
    returning 0.0."""
    import data.binance_provider as bp_module

    monkeypatch.setattr(dp.trade_client, "balance", MagicMock(return_value=[
        {"asset": "BUSD", "availableBalance": "0.00000000"},
    ]))
    warning_mock = MagicMock()
    monkeypatch.setattr(bp_module.logger, "warning", warning_mock)

    result = dp.get_account_balance()

    assert result == 0.0
    assert warning_mock.called, (
        "get_account_balance() must log a WARNING when no 'USDT' entry "
        "is found, instead of silently returning 0.0."
    )


def test_empty_list_response_logs_warning_and_returns_zero(monkeypatch, dp):
    """Same failure mode, degenerate case: balance() returns an empty
    list entirely (e.g. Multi-Assets Mode changing the response shape,
    candidate cause #4 in PATCH_NOTES.md)."""
    import data.binance_provider as bp_module

    monkeypatch.setattr(dp.trade_client, "balance", MagicMock(return_value=[]))
    warning_mock = MagicMock()
    monkeypatch.setattr(bp_module.logger, "warning", warning_mock)

    result = dp.get_account_balance()

    assert result == 0.0
    assert warning_mock.called


def test_usdt_entry_found_logs_info_not_only_debug(monkeypatch, dp):
    """Healthy path: a non-zero USDT balance must now be visible at
    INFO level (previously DEBUG-only, so it never appeared in the
    INFO-level production log even when the read was succeeding)."""
    import data.binance_provider as bp_module

    monkeypatch.setattr(dp.trade_client, "balance", MagicMock(return_value=[
        {"asset": "USDT", "availableBalance": "1234.56"},
    ]))
    info_mock = MagicMock()
    warning_mock = MagicMock()
    monkeypatch.setattr(bp_module.logger, "info", info_mock)
    monkeypatch.setattr(bp_module.logger, "warning", warning_mock)

    result = dp.get_account_balance()

    assert result == 1234.56
    assert info_mock.called, (
        "A successful non-zero balance read must log at INFO level."
    )
    assert not warning_mock.called
