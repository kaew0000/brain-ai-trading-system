"""tests/test_ghost_reconciliation_multi_symbol.py — V16 §66.

Closes the last item flagged in §62's "Known follow-up":
system_health/order_state.py's OrderStateManager.get_order_state(sys,
symbol=...) already accepted a symbol parameter (as did
GhostReconciliationMonitor.check()) — but internally it always called
ReconciliationEngine.run() / get_last_views(), which only ever
read/wrote run()'s own settings.SYMBOL-keyed state (see
reconciliation.py's own docstring) regardless of what `symbol` was
passed in. A caller asking about XRPUSDT would silently get BTCUSDT's
exchange/journal/bot views back, mislabeled with symbol="XRPUSDT" in
the returned snapshot.

Covers:
  - ReconciliationEngine.run_for_symbol() (new, §66)
  - OrderStateManager.get_order_state()'s SCHEDULER_ENABLED-aware branch
  - main.py::run_ghost_reconciliation_check()'s multi-symbol dispatch
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from config.settings import settings
from system_health.order_state import OrderState, OrderStateManager
from system_health.reconciliation import ReconciliationEngine
from system_health.recovery_engine import RecoveryEngine

pytestmark = pytest.mark.unit


@dataclass
class _FakePortfolioPosition:
    direction: str
    quantity: float


def _multi_dp(positions: dict[str, dict]):
    dp = MagicMock()
    dp.get_position_info.side_effect = lambda symbol=None: positions.get(symbol)
    dp.get_all_positions.side_effect = lambda: [dict(p, symbol=s) for s, p in positions.items()]
    return dp


def _journal_for(open_trades_by_symbol: dict[str, list[dict]], total_trades=5):
    jrn = MagicMock()
    all_open = [t for trades in open_trades_by_symbol.values() for t in trades]
    jrn.get_open_trades.return_value = all_open
    jrn.get_trades.return_value = [None] * total_trades
    return jrn


def _sys(**overrides) -> dict:
    base = {
        "data_provider":        None,
        "paper_engine":          None,
        "journal_v2":            None,
        "portfolio_state":       None,
        "trade_lifecycle":       None,
        "event_bus":             MagicMock(),
        "reconciliation_engine": ReconciliationEngine(),
        "recovery_engine":       RecoveryEngine(),
    }
    base.update(overrides)
    return base


class TestRunForSymbol:

    def test_reconciles_only_the_given_symbol(self):
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _journal_for({}, total_trades=5)
        evt = eng.run_for_symbol(_sys(data_provider=dp, journal_v2=jrn), "XRPUSDT")
        assert evt is not None
        assert evt.symbol == "XRPUSDT"
        assert evt.mismatch_type == "PRESENCE_MISMATCH"

    def test_shares_suppression_state_with_run_all_symbols(self):
        """A symbol first seen via run_all_symbols(), then queried again
        via run_for_symbol(), must be recognized as the SAME suppression
        track (one mismatch signature, not two independent ones)."""
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _journal_for({}, total_trades=5)
        s = _sys(data_provider=dp, journal_v2=jrn)

        first = eng.run_all_symbols(s)
        assert len(first) == 1

        second = eng.run_for_symbol(s, "XRPUSDT")
        assert second is None   # same signature, suppressed

    def test_does_not_discover_or_touch_other_symbols(self):
        eng = ReconciliationEngine()
        dp = _multi_dp({
            "XRPUSDT":  {"side": "LONG", "positionAmt": 100},
            "DOGEUSDT": {"side": "SHORT", "positionAmt": 300},
        })
        jrn = _journal_for({}, total_trades=5)
        s = _sys(data_provider=dp, journal_v2=jrn)

        eng.run_for_symbol(s, "XRPUSDT")

        assert eng.get_last_views_for_symbol("XRPUSDT") is not None
        assert eng.get_last_views_for_symbol("DOGEUSDT") is None


class TestOrderStateManagerUsesTheGivenSymbol:

    def test_scheduler_mode_reflects_the_requested_symbol_not_settings_symbol(self, monkeypatch):
        """The core §66 bug: querying a non-default symbol under
        SCHEDULER_ENABLED must return THAT symbol's real state, not
        settings.SYMBOL's state mislabeled with the requested symbol."""
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
        assert settings.SYMBOL != "XRPUSDT"   # sanity: proves this isn't a coincidental match

        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _journal_for({}, total_trades=5)
        s = _sys(data_provider=dp, journal_v2=jrn)

        snap = OrderStateManager().get_order_state(s, symbol="XRPUSDT")

        assert snap.symbol == "XRPUSDT"
        assert snap.exchange_position.get("side") == "LONG"
        # Exchange holds a real position, journal has no record of it --
        # DESYNC (the "orphaned exchange position" case), not GHOST
        # (which is the opposite: exchange flat, journal/bot still
        # claim open — see OrderStateManager._classify()).
        assert snap.canonical_state == OrderState.DESYNC
        assert snap.mismatch_type == "PRESENCE_MISMATCH"

    def test_scheduler_mode_two_symbols_queried_independently(self, monkeypatch):
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})   # DOGEUSDT: flat
        jrn = _journal_for({}, total_trades=5)
        s = _sys(data_provider=dp, journal_v2=jrn)

        xrp = OrderStateManager().get_order_state(s, symbol="XRPUSDT")
        doge = OrderStateManager().get_order_state(s, symbol="DOGEUSDT")

        assert xrp.canonical_state == OrderState.DESYNC     # real orphaned position
        assert doge.canonical_state == OrderState.NO_POSITION   # nothing anywhere

    def test_non_scheduler_mode_unchanged(self, monkeypatch):
        """SCHEDULER_ENABLED=false must keep using run()/get_last_views()
        exactly as before §66 — regression guard."""
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
        jrn = _journal_for({}, total_trades=5)
        dp = MagicMock()
        dp.get_position_info.return_value = None
        s = _sys(data_provider=dp, journal_v2=jrn)

        snap = OrderStateManager().get_order_state(s, symbol=settings.SYMBOL)
        assert snap.canonical_state == OrderState.NO_POSITION
        dp.get_position_info.assert_called()
        dp.get_all_positions.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# main.py::run_ghost_reconciliation_check() dispatch
# ─────────────────────────────────────────────────────────────────────────────
class TestMainPyGhostCheckDispatch:

    def test_scheduler_enabled_checks_every_discovered_symbol(self, monkeypatch):
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)

        engine = MagicMock()
        engine._discover_symbols.return_value = {"XRPUSDT", "DOGEUSDT"}
        monitor = MagicMock()
        monkeypatch.setattr(
            "system_health.ghost_reconciliation.get_ghost_reconciliation_monitor",
            lambda: monitor,
        )
        monkeypatch.setattr(
            "system_health.reconciliation.get_reconciliation_engine", lambda: engine,
        )

        main_module.run_ghost_reconciliation_check({})

        checked_symbols = {c.kwargs.get("symbol") for c in monitor.check.call_args_list}
        assert checked_symbols == {"XRPUSDT", "DOGEUSDT"}

    def test_scheduler_disabled_checks_once_with_no_symbol(self, monkeypatch):
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)

        monitor = MagicMock()
        monkeypatch.setattr(
            "system_health.ghost_reconciliation.get_ghost_reconciliation_monitor",
            lambda: monitor,
        )

        main_module.run_ghost_reconciliation_check({})

        monitor.check.assert_called_once_with({})

    def test_no_symbols_discovered_checks_nothing(self, monkeypatch):
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)

        engine = MagicMock()
        engine._discover_symbols.return_value = set()
        monitor = MagicMock()
        monkeypatch.setattr(
            "system_health.ghost_reconciliation.get_ghost_reconciliation_monitor",
            lambda: monitor,
        )
        monkeypatch.setattr(
            "system_health.reconciliation.get_reconciliation_engine", lambda: engine,
        )

        main_module.run_ghost_reconciliation_check({})

        monitor.check.assert_not_called()
