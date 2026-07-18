"""
tests/test_execution_coordinator.py — V16 Phase 1 Multi-Symbol Foundation

Covers execution/execution_coordinator.py and the supporting changes:
  - TradeManager(data_provider, symbol=...) accepting an explicit symbol
  - config.settings.symbol_list fallback behavior
  - ExecutionCoordinator: manager creation, caching (singleton-per-symbol,
    O(1) lookup, no duplicates), execution routing, health check,
    graceful shutdown, and backward compatibility with the pre-V16
    single-TradeManager call pattern.

All tests use a MagicMock exchange client — no real network calls.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


def _make_mock_provider():
    """A data_provider whose .client is a MagicMock UMFutures — matches
    what TradeManager actually reads (see TradeManager.__init__)."""
    mock_client = MagicMock()
    mock_client.exchange_info.return_value = {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
                    {"filterType": "PRICE_FILTER",  "tickSize": "0.10"},
                ],
            },
            {
                "symbol": "ETHUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE",     "stepSize": "0.01", "minQty": "0.01", "maxQty": "1000.0"},
                    {"filterType": "PRICE_FILTER",  "tickSize": "0.01"},
                ],
            },
        ]
    }
    mock_client.change_leverage.return_value = {}
    mock_client.change_margin_type.return_value = {}
    provider = MagicMock()
    provider.client = mock_client
    return provider, mock_client


def _settings_patch(ms):
    ms.SYMBOL             = "BTCUSDT"
    ms.LEVERAGE            = 5
    ms.RISK_PER_TRADE_MAX  = 0.01
    ms.RISK_PER_TRADE_MIN  = 0.005
    ms.MAX_MARGIN_USAGE    = 0.20
    ms.symbol_list         = ["BTCUSDT"]


class TestTradeManagerExplicitSymbol:
    """TradeManager(data_provider, symbol=...) must be backward compatible."""

    def test_default_symbol_matches_settings(self):
        from execution.trade_manager import TradeManager
        provider, _ = _make_mock_provider()
        with patch("execution.trade_manager.settings") as ms:
            _settings_patch(ms)
            tm = TradeManager(provider)
        assert tm.symbol == "BTCUSDT"

    def test_explicit_symbol_overrides_settings(self):
        from execution.trade_manager import TradeManager
        provider, _ = _make_mock_provider()
        with patch("execution.trade_manager.settings") as ms:
            _settings_patch(ms)
            tm = TradeManager(provider, symbol="ETHUSDT")
        assert tm.symbol == "ETHUSDT"

    def test_two_instances_have_independent_symbols(self):
        """No shared mutable state between TradeManagers for different symbols."""
        from execution.trade_manager import TradeManager
        provider, _ = _make_mock_provider()
        with patch("execution.trade_manager.settings") as ms:
            _settings_patch(ms)
            tm_btc = TradeManager(provider, symbol="BTCUSDT")
            tm_eth = TradeManager(provider, symbol="ETHUSDT")
        assert tm_btc.symbol == "BTCUSDT"
        assert tm_eth.symbol == "ETHUSDT"
        tm_eth.symbol = "SOLUSDT"          # mutate one instance
        assert tm_btc.symbol == "BTCUSDT"  # ... must not affect the other


class TestSettingsSymbolList:
    """config.settings.symbol_list fallback rule."""

    def test_falls_back_to_symbol_when_symbols_unset(self):
        from config.settings import Settings
        s = Settings(SYMBOL="BTCUSDT")
        assert s.SYMBOLS is None
        assert s.symbol_list == ["BTCUSDT"]

    def test_uses_symbols_when_set(self):
        from config.settings import Settings
        s = Settings(SYMBOL="BTCUSDT", SYMBOLS=["BTCUSDT", "ETHUSDT"])
        assert s.symbol_list == ["BTCUSDT", "ETHUSDT"]

    def test_empty_symbols_list_falls_back_too(self):
        from config.settings import Settings
        s = Settings(SYMBOL="BTCUSDT", SYMBOLS=[])
        assert s.symbol_list == ["BTCUSDT"]


class TestExecutionCoordinatorManagerLifecycle:

    def _make_coordinator(self, symbols=None):
        from execution.execution_coordinator import ExecutionCoordinator
        provider, client = _make_mock_provider()
        with patch("execution.execution_coordinator.settings") as ecs, \
             patch("execution.trade_manager.settings") as tms:
            ecs.symbol_list = symbols or ["BTCUSDT"]
            _settings_patch(tms)
            coordinator = ExecutionCoordinator(provider, symbols=symbols)
        return coordinator, client

    def test_defaults_to_single_settings_symbol(self):
        coordinator, _ = self._make_coordinator(symbols=None)
        assert coordinator.symbols == ["BTCUSDT"]
        assert coordinator.default_symbol == "BTCUSDT"

    def test_get_manager_creates_trade_manager(self):
        from execution.trade_manager import TradeManager
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            mgr = coordinator.get_manager("ETHUSDT")
        assert isinstance(mgr, TradeManager)
        assert mgr.symbol == "ETHUSDT"

    def test_manager_is_cached_singleton_per_symbol(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            mgr1 = coordinator.get_manager("BTCUSDT")
            mgr2 = coordinator.get_manager("BTCUSDT")
        assert mgr1 is mgr2  # same instance, not a new one

    def test_no_duplicate_managers_across_repeated_calls(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            for _ in range(5):
                coordinator.get_manager("BTCUSDT")
                coordinator.get_manager("ETHUSDT")
        assert len(coordinator._managers) == 2

    def test_different_symbols_get_different_managers(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            btc = coordinator.get_manager("BTCUSDT")
            eth = coordinator.get_manager("ETHUSDT")
        assert btc is not eth
        assert btc.symbol == "BTCUSDT"
        assert eth.symbol == "ETHUSDT"

    def test_unconfigured_symbol_raises(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT"])
        with pytest.raises(ValueError):
            coordinator.get_manager("DOGEUSDT")

    def test_no_symbols_raises_at_construction(self):
        from execution.execution_coordinator import ExecutionCoordinator
        provider, _ = _make_mock_provider()
        with patch("execution.execution_coordinator.settings") as ecs:
            ecs.symbol_list = []
            with pytest.raises(ValueError):
                ExecutionCoordinator(provider, symbols=[])


class TestExecutionCoordinatorRouting:

    def _make_coordinator(self, symbols=None):
        from execution.execution_coordinator import ExecutionCoordinator
        provider, client = _make_mock_provider()
        with patch("execution.execution_coordinator.settings") as ecs:
            ecs.symbol_list = symbols or ["BTCUSDT"]
            coordinator = ExecutionCoordinator(provider, symbols=symbols)
        return coordinator, client

    def test_execute_trade_default_symbol_matches_bare_trademanager(self):
        """Backward-compat: with one symbol configured, calling
        coordinator.execute_trade(...) without `symbol=` must produce the
        exact same order calls a bare TradeManager.execute_trade() would."""
        coordinator, client = self._make_coordinator(symbols=["BTCUSDT"])
        client.new_order.side_effect = [
            {"orderId": 1, "status": "FILLED"},  # entry
            {"orderId": 2, "status": "NEW"},      # SL
            {"orderId": 3, "status": "NEW"},      # TP
        ]
        with patch("execution.trade_manager.settings") as tms, \
             patch("execution.trade_manager.time.sleep"):
            _settings_patch(tms)
            result = coordinator.execute_trade(
                direction="LONG", entry_price=50_000.0,
                stop_loss=49_000.0, take_profit=52_000.0,
                balance=1_000.0, risk_pct=0.01,
            )
        assert result["success"] is True
        entry_call = client.new_order.call_args_list[0]
        assert entry_call[1]["symbol"] == "BTCUSDT"
        assert entry_call[1]["type"] == "MARKET"

    def test_execute_trade_routes_to_requested_symbol(self):
        coordinator, client = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        client.new_order.side_effect = [
            {"orderId": 10, "status": "FILLED"},
            {"orderId": 11, "status": "NEW"},
            {"orderId": 12, "status": "NEW"},
        ]
        with patch("execution.trade_manager.settings") as tms, \
             patch("execution.trade_manager.time.sleep"):
            _settings_patch(tms)
            result = coordinator.execute_trade(
                direction="SHORT", entry_price=3_000.0,
                stop_loss=3_100.0, take_profit=2_800.0,
                balance=1_000.0, risk_pct=0.01,
                symbol="ETHUSDT",
            )
        assert result["success"] is True
        entry_call = client.new_order.call_args_list[0]
        assert entry_call[1]["symbol"] == "ETHUSDT"
        # only the ETHUSDT manager should have been created
        assert list(coordinator._managers.keys()) == ["ETHUSDT"]

    def test_getattr_passthrough_to_default_manager(self):
        """Safety-net delegation for attributes the coordinator doesn't
        define itself (e.g. .client, .cancel_all_orders)."""
        coordinator, client = self._make_coordinator(symbols=["BTCUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            assert coordinator.symbol == "BTCUSDT"   # delegated to TradeManager.symbol
            assert coordinator.client is client       # delegated to TradeManager.client

    def test_private_attribute_lookup_does_not_delegate(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT"])
        with pytest.raises(AttributeError):
            coordinator._totally_made_up_private_attr


class TestExecutionCoordinatorHealthAndShutdown:

    def _make_coordinator(self, symbols=None):
        from execution.execution_coordinator import ExecutionCoordinator
        provider, client = _make_mock_provider()
        with patch("execution.execution_coordinator.settings") as ecs:
            ecs.symbol_list = symbols or ["BTCUSDT"]
            coordinator = ExecutionCoordinator(provider, symbols=symbols)
        return coordinator, client

    def test_health_check_reports_all_configured_symbols(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        health = coordinator.health_check()
        assert set(health.keys()) == {"BTCUSDT", "ETHUSDT"}
        assert health["BTCUSDT"]["manager_created"] is False
        assert health["BTCUSDT"]["is_default"] is True
        assert health["ETHUSDT"]["is_default"] is False

    def test_health_check_reflects_created_managers(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            coordinator.get_manager("BTCUSDT")
        health = coordinator.health_check()
        assert health["BTCUSDT"]["manager_created"] is True
        assert health["ETHUSDT"]["manager_created"] is False

    def test_initialize_sets_leverage_and_margin_for_every_symbol(self):
        coordinator, client = self._make_coordinator(symbols=["BTCUSDT", "ETHUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            results = coordinator.initialize()
        assert results == {"BTCUSDT": True, "ETHUSDT": True}
        assert client.change_leverage.call_count == 2
        assert client.change_margin_type.call_count == 2

    def test_shutdown_clears_managers_and_blocks_further_use(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT"])
        with patch("execution.trade_manager.settings") as tms:
            _settings_patch(tms)
            coordinator.get_manager("BTCUSDT")
        assert len(coordinator._managers) == 1
        coordinator.shutdown()
        assert len(coordinator._managers) == 0
        with pytest.raises(RuntimeError):
            coordinator.get_manager("BTCUSDT")

    def test_shutdown_is_idempotent(self):
        coordinator, _ = self._make_coordinator(symbols=["BTCUSDT"])
        coordinator.shutdown()
        coordinator.shutdown()  # must not raise
