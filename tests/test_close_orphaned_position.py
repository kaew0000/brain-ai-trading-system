"""
tests/test_close_orphaned_position.py

tools/close_orphaned_position.py had no coverage before this file (new
tool). Tests the core close_orphaned_position() function directly with
mocked data_provider/trade_manager — no real Binance calls, no CLI
argument parsing, no input() prompt (auto_confirm=True everywhere).
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _position(**overrides):
    p = {
        "symbol": "BTCUSDT", "side": "LONG", "positionAmt": 0.1062,
        "entryPrice": 65664.78, "markPrice": 65700.0, "leverage": 5,
    }
    p.update(overrides)
    return p


class TestCloseOrphanedPosition:
    def test_no_position_is_a_safe_noop(self):
        from tools.close_orphaned_position import close_orphaned_position
        dp = MagicMock()
        dp.get_position_info.return_value = None
        tm = MagicMock()

        result = close_orphaned_position(dp, tm, auto_confirm=True)

        assert result == 0
        tm.close_position.assert_not_called()

    def test_closes_and_confirms_flat(self):
        from tools.close_orphaned_position import close_orphaned_position
        dp = MagicMock()
        dp.get_position_info.side_effect = [_position(), None]  # before, after
        tm = MagicMock()
        tm.close_position.return_value = {"orderId": 1, "status": "FILLED"}

        result = close_orphaned_position(dp, tm, auto_confirm=True)

        assert result == 0
        tm.close_position.assert_called_once_with("LONG", 0.1062)

    def test_close_position_returning_none_is_reported_as_failure(self):
        from tools.close_orphaned_position import close_orphaned_position
        dp = MagicMock()
        dp.get_position_info.return_value = _position()
        tm = MagicMock()
        tm.close_position.return_value = None

        result = close_orphaned_position(dp, tm, auto_confirm=True)

        assert result == 2

    def test_still_open_after_close_is_reported_as_failure(self):
        """Order came back non-None but a re-query still shows a position —
        must not be treated as success just because close_position()
        didn't return None (mirrors RecoveryEngine's own
        'verify against exchange truth, don't trust the response alone'
        pattern)."""
        from tools.close_orphaned_position import close_orphaned_position
        dp = MagicMock()
        dp.get_position_info.side_effect = [_position(), _position(positionAmt=0.02)]
        tm = MagicMock()
        tm.close_position.return_value = {"orderId": 1, "status": "PARTIALLY_FILLED"}

        result = close_orphaned_position(dp, tm, auto_confirm=True)

        assert result == 2

    def test_prompt_declined_cancels_without_ordering(self, monkeypatch):
        from tools.close_orphaned_position import close_orphaned_position
        dp = MagicMock()
        dp.get_position_info.return_value = _position()
        tm = MagicMock()
        monkeypatch.setattr("builtins.input", lambda _: "no")

        result = close_orphaned_position(dp, tm, auto_confirm=False)

        assert result == 1
        tm.close_position.assert_not_called()

    def test_prompt_confirmed_places_order(self, monkeypatch):
        from tools.close_orphaned_position import close_orphaned_position
        dp = MagicMock()
        dp.get_position_info.side_effect = [_position(), None]
        tm = MagicMock()
        tm.close_position.return_value = {"orderId": 1, "status": "FILLED"}
        monkeypatch.setattr("builtins.input", lambda _: "YES")

        result = close_orphaned_position(dp, tm, auto_confirm=False)

        assert result == 0
        tm.close_position.assert_called_once_with("LONG", 0.1062)


class TestMainnetGuard:
    def test_main_refuses_when_not_testnet(self, monkeypatch):
        import tools.close_orphaned_position as mod
        from config.settings import settings

        monkeypatch.setattr(settings, "BINANCE_TESTNET", False)
        monkeypatch.setattr(sys, "argv", ["close_orphaned_position.py"])

        result = mod.main()

        assert result == 1
