"""
tests/test_v16_execution_idempotency.py — V16 Execution Regression Suite

Covers BUG-V16-EXEC-01: place_market_order / place_stop_loss /
place_take_profit / close_position sent no newClientOrderId and swallowed
every ClientError internally (returning None) before @retry_api_call ever
saw it. That meant:
  (a) a retry after an ambiguous network failure (order actually placed,
      response lost) could create a second live order with no error, and
  (b) retries=N was dead code for every Binance-side error (rate limit,
      5xx), because the inner try/except already returned None on any
      ClientError, so the decorator's wrapper saw a normal return value —
      never an exception — and had nothing to retry.

All tests use a MagicMock exchange client — no real network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from binance.error import ClientError

pytestmark = pytest.mark.unit


def _client_error(status_code, error_code, message):
    return ClientError(status_code, error_code, message, {})


def _make_manager():
    """Build a TradeManager with a fully mocked client (mirrors test_execution.py)."""
    from execution.trade_manager import TradeManager

    mock_client = MagicMock()
    mock_client.exchange_info.return_value = {
        "symbols": [{
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "LOT_SIZE",    "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
            ],
        }]
    }
    mock_provider       = MagicMock()
    mock_provider.client = mock_client

    with patch("execution.trade_manager.settings") as ms:
        ms.SYMBOL             = "BTCUSDT"
        ms.LEVERAGE           = 5
        ms.RISK_PER_TRADE_MAX = 0.01
        ms.RISK_PER_TRADE_MIN = 0.005
        manager = TradeManager(mock_provider)

    manager.client = mock_client
    manager.symbol = "BTCUSDT"
    return manager, mock_client


class TestOrderIdempotencyKeys:
    """Every order placement call must carry a newClientOrderId."""

    def test_market_order_generates_client_id_when_not_supplied(self):
        m, client = _make_manager()
        client.new_order.return_value = {"orderId": 1, "status": "FILLED"}
        m.place_market_order("LONG", 0.05)
        kwargs = client.new_order.call_args[1]
        assert "newClientOrderId" in kwargs
        assert kwargs["newClientOrderId"]  # non-empty

    def test_market_order_reuses_caller_supplied_id(self):
        """This is what execute_trade relies on: the SAME id must be sent
        every time, so a retry of the whole call is idempotent."""
        m, client = _make_manager()
        client.new_order.return_value = {"orderId": 1, "status": "FILLED"}
        m.place_market_order("LONG", 0.05, client_order_id="bbENTRYFIXED123")
        m.place_market_order("LONG", 0.05, client_order_id="bbENTRYFIXED123")
        first  = client.new_order.call_args_list[0][1]["newClientOrderId"]
        second = client.new_order.call_args_list[1][1]["newClientOrderId"]
        assert first == second == "bbENTRYFIXED123"

    def test_two_default_generated_ids_are_different(self):
        """Sanity check the generator doesn't collide across unrelated intents."""
        from execution.trade_manager import new_client_order_id
        assert new_client_order_id("ENTRY") != new_client_order_id("ENTRY")

    def test_close_position_carries_client_id(self):
        m, client = _make_manager()
        client.new_order.return_value = {"orderId": 2, "status": "FILLED"}
        m.close_position("LONG", 0.05, client_order_id="bbCLOSEFIXED")
        kwargs = client.new_order.call_args[1]
        assert kwargs["newClientOrderId"] == "bbCLOSEFIXED"
        assert kwargs["reduceOnly"] == "true"


class TestRetryActuallyRetriesNow:
    """BUG-V16-EXEC-01(b): retryable ClientErrors must propagate to the
    @retry_api_call decorator instead of being swallowed as a plain
    `return None`, or retries= is dead code."""

    def test_rate_limit_error_is_retried_and_recovers(self):
        m, client = _make_manager()
        rate_limited = _client_error(429, -1015, "Too many requests.")
        client.new_order.side_effect = [rate_limited, {"orderId": 3, "status": "FILLED"}]

        with patch("execution.trade_manager.time.sleep"):  # don't actually wait in tests
            result = m.place_market_order("LONG", 0.05, client_order_id="bbRETRY1")

        assert client.new_order.call_count == 2
        assert result == {"orderId": 3, "status": "FILLED"}

    def test_non_retryable_business_error_returns_none_without_retry(self):
        """e.g. insufficient margin — retrying can't fix this, so it should
        fail fast with a single call, not burn through retries=5."""
        m, client = _make_manager()
        margin_error = _client_error(400, -2019, "Margin is insufficient.")
        client.new_order.side_effect = margin_error

        with patch("execution.trade_manager.time.sleep"):
            result = m.place_market_order("LONG", 0.05, client_order_id="bbNORETRY1")

        assert result is None
        assert client.new_order.call_count == 1


class TestDuplicateOrderRecovery:
    """BUG-V16-EXEC-01(a): if the exchange rejects a retry because the
    clientOrderId was already used, that means the original attempt likely
    succeeded — recover it via query_order instead of reporting failure or,
    worse, silently returning None and letting the caller think there is no
    position when one actually exists."""

    def test_duplicate_market_order_recovered_via_query_order(self):
        m, client = _make_manager()
        dup_error = _client_error(400, -2010, "Duplicate order sent.")
        client.new_order.side_effect = dup_error
        client.query_order.return_value = {
            "orderId": 999, "status": "FILLED", "origClientOrderId": "bbDUP1"
        }

        result = m.place_market_order("LONG", 0.05, client_order_id="bbDUP1")

        client.query_order.assert_called_once_with(symbol="BTCUSDT", origClientOrderId="bbDUP1")
        assert result["orderId"] == 999

    def test_duplicate_stop_loss_tier1_recovered(self):
        m, client = _make_manager()
        dup_error = _client_error(400, -2010, "Duplicate order sent.")
        client.new_order.side_effect = dup_error
        client.query_order.return_value = {"orderId": 555, "status": "NEW"}

        result = m.place_stop_loss("LONG", 0.05, 49_000.0, client_order_id="bbSLDUP")

        assert result["orderId"] == 555
        # must NOT have fallen through to tier 2/3 — duplicate means tier 1 already exists
        assert client.new_order.call_count == 1


class TestExecuteTradeIdempotentEndToEnd:
    """execute_trade must generate the id ONCE per order and thread it
    through, so a retry triggered deep inside place_market_order's own
    @retry_api_call decorator is still idempotent."""

    def test_entry_order_id_stable_across_internal_retry(self):
        m, client = _make_manager()
        conn_reset = ConnectionResetError("peer reset connection")
        client.new_order.side_effect = [
            conn_reset,                                    # entry attempt 1: ambiguous network failure
            {"orderId": 10, "status": "FILLED"},           # entry attempt 2 (retry)
            {"orderId": 11, "status": "NEW"},               # SL tier 1
            {"orderId": 12, "status": "NEW"},               # TP tier 1
        ]

        with patch("execution.trade_manager.time.sleep"):
            result = m.execute_trade(
                direction="LONG", entry_price=50_000.0,
                stop_loss=49_000.0, take_profit=52_000.0,
                balance=1_000.0, risk_pct=0.01,
            )

        assert result["success"] is True
        entry_calls = [c for c in client.new_order.call_args_list
                       if c[1].get("type") == "MARKET" and not c[1].get("reduceOnly")]
        assert len(entry_calls) == 2
        assert entry_calls[0][1]["newClientOrderId"] == entry_calls[1][1]["newClientOrderId"]

    def test_sl_failure_closes_naked_position_with_its_own_id(self):
        """Existing safety behaviour (force-close on SL failure) must still
        work, and the emergency close must carry its own idempotency id."""
        m, client = _make_manager()
        dup_error = _client_error(400, -4120, "Order's type is not supported.")
        client.new_order.side_effect = [
            {"orderId": 20, "status": "FILLED"},   # entry
            dup_error, dup_error, dup_error,        # SL: all 3 tiers fail
            {"orderId": 21, "status": "FILLED"},   # emergency close
        ]

        with patch("execution.trade_manager.time.sleep"):
            result = m.execute_trade(
                direction="LONG", entry_price=50_000.0,
                stop_loss=49_000.0, take_profit=52_000.0,
                balance=1_000.0, risk_pct=0.01,
            )

        assert result["success"] is False
        assert "naked position closed" in result["error"]
        close_calls = [c for c in client.new_order.call_args_list
                       if c[1].get("type") == "MARKET" and c[1].get("reduceOnly") == "true"]
        assert len(close_calls) == 1
        assert close_calls[0][1]["newClientOrderId"].startswith("bbEMERGCLOSE")
