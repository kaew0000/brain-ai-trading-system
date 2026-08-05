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


class TestClosePositionRetryBudget:
    """V16 BUG-LIVE-RISK-04: close_position is the emergency fallback used
    when SL placement fails after ALL of place_stop_loss's retries — it
    must not give up more easily than the thing it's a fallback for."""

    def test_close_position_retries_as_many_times_as_place_stop_loss(self):
        m, client = _make_manager()
        rate_limited = _client_error(429, -1015, "Too many requests.")
        # 4 failures then success on the 5th attempt — only possible to
        # observe if retries=5 (old retries=2 would have raised out after
        # attempt 2 and never reached call #5).
        client.new_order.side_effect = [
            rate_limited, rate_limited, rate_limited, rate_limited,
            {"orderId": 9, "status": "FILLED"},
        ]
        with patch("execution.trade_manager.time.sleep"):
            result = m.close_position("LONG", 0.05, client_order_id="bbCLOSERETRY")
        assert client.new_order.call_count == 5
        assert result == {"orderId": 9, "status": "FILLED"}


class TestLeverageReQueryOnSetLeverageFailure:
    """V16 BUG-LIVE-RISK-03: set_leverage()'s return value must actually be
    checked. On failure, re-query the exchange's real current leverage and
    size the trade against THAT — not the intended-but-unconfirmed value."""

    def _stub_happy_order_flow(self, client):
        client.new_order.return_value = {"orderId": 1, "status": "FILLED"}

    def test_sizes_against_actual_leverage_when_set_leverage_fails(self):
        m, client = _make_manager()
        client.change_leverage.side_effect = _client_error(400, -4046, "No need to change margin type.")
        client.get_position_risk.return_value = [
            {"symbol": "BTCUSDT", "leverage": "3"},
        ]
        self._stub_happy_order_flow(client)

        with patch.object(m, "calculate_position_size", return_value=0.02) as mock_calc, \
             patch("execution.trade_manager.time.sleep"):
            result = m.execute_trade(
                direction="LONG", entry_price=67000.0, stop_loss=65800.0,
                take_profit=69400.0, balance=10000.0, risk_pct=0.01, leverage=10,
            )

        # intended leverage was 10x; actual on the exchange was 3x —
        # calculate_position_size must be called with the ACTUAL value.
        mock_calc.assert_called_once_with(10000.0, 67000.0, 65800.0, 0.01, 3)
        assert result["success"] is True

    def test_uses_intended_leverage_when_set_leverage_succeeds(self):
        """Sanity check / non-regression: the normal (no-failure) path is unchanged."""
        m, client = _make_manager()
        client.change_leverage.return_value = {}  # no exception == success
        self._stub_happy_order_flow(client)

        with patch.object(m, "calculate_position_size", return_value=0.02) as mock_calc, \
             patch("execution.trade_manager.time.sleep"):
            m.execute_trade(
                direction="LONG", entry_price=67000.0, stop_loss=65800.0,
                take_profit=69400.0, balance=10000.0, risk_pct=0.01, leverage=10,
            )

        mock_calc.assert_called_once_with(10000.0, 67000.0, 65800.0, 0.01, 10)
        client.get_position_risk.assert_not_called()

    def test_aborts_trade_when_leverage_cannot_be_verified(self):
        """If set_leverage fails AND the re-query also fails, abort rather
        than guess — no order should be placed at all."""
        m, client = _make_manager()
        client.change_leverage.side_effect = _client_error(400, -4046, "No need to change margin type.")
        client.get_position_risk.side_effect = _client_error(400, -1000, "An unknown error occurred.")
        self._stub_happy_order_flow(client)

        with patch("execution.trade_manager.time.sleep"):
            result = m.execute_trade(
                direction="LONG", entry_price=67000.0, stop_loss=65800.0,
                take_profit=69400.0, balance=10000.0, risk_pct=0.01, leverage=10,
            )

        assert result["success"] is False
        assert "leverage" in result["error"].lower()
        client.new_order.assert_not_called()

    def test_retryable_requery_error_is_retried(self):
        """The re-query call itself must honor @retry_api_call, not
        swallow a retryable ClientError internally (that would be
        BUG-V16-EXEC-01(b) again, just relocated to this new method)."""
        m, client = _make_manager()
        client.change_leverage.side_effect = _client_error(400, -4046, "No need to change margin type.")
        rate_limited = _client_error(429, -1015, "Too many requests.")
        client.get_position_risk.side_effect = [
            rate_limited,
            [{"symbol": "BTCUSDT", "leverage": "3"}],
        ]
        self._stub_happy_order_flow(client)

        with patch.object(m, "calculate_position_size", return_value=0.02) as mock_calc, \
             patch("execution.trade_manager.time.sleep"):
            result = m.execute_trade(
                direction="LONG", entry_price=67000.0, stop_loss=65800.0,
                take_profit=69400.0, balance=10000.0, risk_pct=0.01, leverage=10,
            )

        assert client.get_position_risk.call_count == 2
        mock_calc.assert_called_once_with(10000.0, 67000.0, 65800.0, 0.01, 3)
        assert result["success"] is True


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
