import time
import threading
import pytest
from unittest.mock import MagicMock

from exchange_state.manager import ExchangeStateManager, get_manager, reset_registry

pytestmark = pytest.mark.unit


def _mock_dp(
    wallet_balance=1000.0, symbol="BTCUSDT", qty=0.1, entry=65000.0,
    orders=None,
):
    dp = MagicMock()
    dp.get_account_snapshot.return_value = {
        "wallet_balance": wallet_balance, "available_balance": 500.0,
        "unrealized_pnl": 0.0, "total_margin_balance": wallet_balance,
        "maintenance_margin": 0.0, "initial_margin": 0.0,
        "positions": [{
            "symbol": symbol, "side": "LONG", "quantity": qty,
            "entry_price": entry, "mark_price": entry + 100, "unrealized_pnl": 10.0,
            "leverage": 5, "margin_type": "ISOLATED", "liquidation_price": 40000.0,
        }] if qty else [],
    }
    dp.get_open_orders.return_value = orders or []
    return dp


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry()
    yield
    reset_registry()


class TestBasics:
    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            ExchangeStateManager(MagicMock(), mode="invalid")

    def test_first_refresh_builds_snapshot(self):
        m = ExchangeStateManager(_mock_dp(), mode="paper")
        snap = m.get_snapshot()
        assert snap.account.wallet_balance == 1000.0
        assert snap.revision == 1
        assert snap.degraded is False
        assert snap.sync_reason == "startup"

    def test_cache_hit_returns_same_object_without_calling_provider_again(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=60)
        s1 = m.get_snapshot()
        s2 = m.get_snapshot()
        assert s1 is s2
        assert dp.get_account_snapshot.call_count == 1

    def test_ttl_expiry_triggers_refresh(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0.01)
        m.get_snapshot()
        time.sleep(0.02)
        m.get_snapshot()
        assert dp.get_account_snapshot.call_count == 2

    def test_force_refresh_bypasses_cache(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=60)
        m.get_snapshot()
        m.get_snapshot(force=True)
        assert dp.get_account_snapshot.call_count == 2

    def test_single_refresh_is_exactly_two_provider_calls(self):
        """v2 requirement: one refresh = one composed round, not one call
        per field."""
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper")
        m.refresh()
        assert dp.get_account_snapshot.call_count == 1
        assert dp.get_open_orders.call_count == 1


class TestPositionsAndOrders:
    def test_get_positions_and_get_position(self):
        m = ExchangeStateManager(_mock_dp(), mode="paper")
        positions = m.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTCUSDT"
        assert m.get_position("BTCUSDT").side == "LONG"
        assert m.get_position("ETHUSDT") is None

    def test_get_orders(self):
        orders = [{
            "symbol": "BTCUSDT", "order_id": 1, "client_order_id": "sl-1",
            "side": "SELL", "type": "STOP_MARKET", "status": "NEW",
            "stop_price": 49000.0, "orig_qty": 0.1, "executed_qty": 0.0,
            "reduce_only": True,
        }]
        m = ExchangeStateManager(_mock_dp(orders=orders), mode="paper")
        result = m.get_orders()
        assert len(result) == 1
        assert result[0].is_sl is True

    def test_position_version_increments_on_change_only(self):
        dp = _mock_dp(entry=65000.0)
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0)
        v1 = m.get_position("BTCUSDT").version
        # same data → refresh again, version must NOT bump
        m.refresh()
        v2 = m.get_position("BTCUSDT").version
        assert v1 == v2 == 1

        # change entry price → version must bump
        dp.get_account_snapshot.return_value["positions"][0]["entry_price"] = 66000.0
        m.refresh()
        v3 = m.get_position("BTCUSDT").version
        assert v3 == 2

    def test_position_disappearing_and_reappearing_resets_state(self):
        dp = _mock_dp(entry=65000.0)
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0)
        assert m.get_position("BTCUSDT").version == 1

        dp.get_account_snapshot.return_value["positions"] = []
        m.refresh()
        assert m.get_position("BTCUSDT") is None

        dp.get_account_snapshot.return_value["positions"] = [{
            "symbol": "BTCUSDT", "side": "LONG", "quantity": 0.1,
            "entry_price": 67000.0, "mark_price": 67100.0, "unrealized_pnl": 0.0,
            "leverage": 5, "margin_type": "ISOLATED", "liquidation_price": 40000.0,
        }]
        m.refresh()
        assert m.get_position("BTCUSDT").version == 1  # fresh start, not 3


class TestDegradedFallback:
    def test_refresh_failure_with_prior_snapshot_returns_stale(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0)
        first = m.get_snapshot()
        dp.get_account_snapshot.side_effect = TimeoutError("read timed out")
        second = m.refresh()
        assert second.degraded is True
        assert second.stale_reason == "timeout"
        assert second.account.wallet_balance == first.account.wallet_balance
        assert second.health_score < 100

    def test_refresh_failure_with_no_prior_snapshot_returns_empty(self):
        dp = _mock_dp()
        dp.get_account_snapshot.side_effect = ConnectionError("network unreachable")
        m = ExchangeStateManager(dp, mode="paper")
        snap = m.refresh()
        assert snap.degraded is True
        assert snap.account.wallet_balance == 0.0
        assert snap.health_score == 0
        assert snap.positions == {}

    def test_recovery_after_failure_clears_degraded(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0)
        m.get_snapshot()
        dp.get_account_snapshot.side_effect = TimeoutError("timeout")
        m.refresh()
        dp.get_account_snapshot.side_effect = None
        recovered = m.refresh()
        assert recovered.degraded is False
        assert recovered.health_score == 100


class TestModeIsolationAndRegistry:
    def test_mode_isolation_separate_instances(self):
        dp = _mock_dp()
        m1 = ExchangeStateManager(dp, mode="paper")
        m2 = ExchangeStateManager(dp, mode="live")
        m1.refresh()
        m2.refresh()
        assert m1.get_snapshot().mode == "paper"
        assert m2.get_snapshot().mode == "live"

    def test_get_manager_returns_same_instance_for_same_key(self):
        dp = _mock_dp()
        m1 = get_manager(dp, mode="paper", account_id="acct1")
        m2 = get_manager(dp, mode="paper", account_id="acct1")
        assert m1 is m2

    def test_get_manager_different_mode_is_different_instance(self):
        dp = _mock_dp()
        m1 = get_manager(dp, mode="paper")
        m2 = get_manager(dp, mode="live")
        assert m1 is not m2


class TestThreadSafety:
    def test_concurrent_refresh_no_errors(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0)
        errors = []
        results = []

        def worker():
            try:
                results.append(m.refresh())
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 20
        # revision must be monotonically consistent — no torn/duplicate state.
        # status() reads the cached snapshot directly (ttl_seconds=0 would
        # make get_snapshot() trigger yet another refresh here).
        assert m.status()["revision"] == 20

    def test_concurrent_get_and_refresh_no_errors(self):
        dp = _mock_dp()
        m = ExchangeStateManager(dp, mode="paper", ttl_seconds=0.001)
        errors = []

        def getter():
            try:
                for _ in range(50):
                    m.get_snapshot()
                    m.get_positions()
            except Exception as exc:
                errors.append(exc)

        def refresher():
            try:
                for _ in range(20):
                    m.refresh()
            except Exception as exc:
                errors.append(exc)

        threads = (
            [threading.Thread(target=getter) for _ in range(5)]
            + [threading.Thread(target=refresher) for _ in range(3)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


def test_status_reports_expected_fields():
    dp = _mock_dp()
    m = ExchangeStateManager(dp, mode="testnet")
    m.get_snapshot()
    s = m.status()
    assert s["mode"] == "testnet"
    assert s["has_snapshot"] is True
    assert s["health_score"] == 100
