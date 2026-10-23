"""tests/test_natural_close_portfolio_release.py — V16 §75.

Bug: when a multi-symbol position was closed on the exchange by its own
SL/TP order, main.py::monitor_open_trades() (SCHEDULER_ENABLED branch,
§60) closed the journal row through TradeLifecycle and registered the
symbol's cooldown, but never removed the position from the scheduler's
PortfolioState. Every natural close therefore leaked one max_positions
slot and left the symbol permanently "already_held". Only the
replacement path (execution_orchestrator.py) removed its own position.

Everything below drives the REAL production function (main.monitor_open_
trades) against a real TradeJournalV2 (temp SQLite), TradeLifecycle,
PortfolioManager and PortfolioState — only the exchange data provider is
faked, same approach as tests/test_multi_symbol_position_tracking.py.
"""
from __future__ import annotations

import time

import pytest

import main as main_module
from config.settings import settings
from execution.trade_lifecycle import TradeLifecycle
from journal.journal_v2 import TradeJournalV2, TradeRecord
from portfolio.portfolio_manager import PortfolioManager
from portfolio.portfolio_models import PortfolioPosition, PositionState
from portfolio.portfolio_state import PortfolioState
from tests.test_portfolio_manager import make_opportunity, make_risk_engine

pytestmark = pytest.mark.unit


# ── fakes / builders ────────────────────────────────────────────────────

class _Bus:
    def publish(self, *a, **k):
        pass


class _DataProvider:
    """Exchange view: `open_symbols` still hold a position; everything
    else has been closed by its SL/TP order."""
    def __init__(self, marks: dict[str, float], open_symbols: tuple[str, ...] = ()):
        self.marks = marks
        self.open_symbols = open_symbols

    def get_all_positions(self):
        return [{"symbol": s} for s in self.open_symbols]

    def get_mark_price(self, symbol=None):
        return self.marks[symbol]


class _Rig:
    def __init__(self, tmp_path):
        self.jrn = TradeJournalV2(str(tmp_path / "journal.db"))
        self.pm = PortfolioManager(journal=self.jrn)
        self.lc = TradeLifecycle(journal=self.jrn, portfolio_manager=self.pm)
        self.state = PortfolioState()

    def open(self, symbol, *, direction="LONG", entry=100.0, sl=90.0, tp=120.0, qty=2.0) -> int:
        """Open exactly the way ExecutionOrchestrator does: journal row +
        lifecycle open + PortfolioState.add_position (same fields)."""
        rec = TradeRecord()
        rec.timestamp, rec.symbol, rec.direction = "2026-10-23T00:00:00", symbol, direction
        rec.entry_price, rec.stop_loss, rec.take_profit, rec.quantity = entry, sl, tp, qty
        tid = self.jrn.save_trade(rec, execution_lane="LIVE")
        handle = self.lc.open_pending(symbol)
        self.lc.open_executing(handle)
        self.lc.open_confirmed(handle, tid, source="EXECUTION_ORCHESTRATOR")
        self.state.add_position(PortfolioPosition(
            symbol=symbol, direction=direction, entry_price=entry, quantity=qty,
            leverage=5, notional=entry * qty, margin_used=entry * qty / 5,
            unrealized_pnl=0.0, state=PositionState.OPEN, opened_at=time.time(), trade_id=tid,
        ))
        return tid

    def sys(self, dp, **overrides):
        d = {"data_provider": dp, "journal_v2": self.jrn, "event_bus": _Bus(),
             "trade_lifecycle": self.lc, "portfolio_state": self.state}
        d.update(overrides)
        return d


@pytest.fixture
def rig(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
    return _Rig(tmp_path)


# ── PortfolioState.remove_position_for_trade ───────────────────────────

class TestRemovePositionForTrade:

    def _pos(self, symbol="ETHUSDT", trade_id=7):
        return PortfolioPosition(
            symbol=symbol, direction="LONG", entry_price=100.0, quantity=1.0, leverage=5,
            notional=100.0, margin_used=20.0, unrealized_pnl=0.0,
            state=PositionState.OPEN, opened_at=time.time(), trade_id=trade_id,
        )

    def test_removes_when_trade_id_matches(self):
        st = PortfolioState()
        st.add_position(self._pos(trade_id=7))
        removed = st.remove_position_for_trade("ETHUSDT", 7)
        assert removed is not None and removed.trade_id == 7
        assert not st.has_position("ETHUSDT")

    def test_noop_when_position_belongs_to_a_different_trade(self):
        st = PortfolioState()
        st.add_position(self._pos(trade_id=8))          # newer position, same symbol
        assert st.remove_position_for_trade("ETHUSDT", 7) is None
        assert st.has_position("ETHUSDT")

    def test_noop_when_symbol_absent(self):
        assert PortfolioState().remove_position_for_trade("ETHUSDT", 7) is None

    def test_noop_when_position_has_no_trade_id(self):
        st = PortfolioState()
        st.add_position(self._pos(trade_id=None))
        assert st.remove_position_for_trade("ETHUSDT", 7) is None
        assert st.has_position("ETHUSDT")

    def test_unconditional_remove_position_unchanged(self):
        st = PortfolioState()
        st.add_position(self._pos(trade_id=7))
        assert st.remove_position("ETHUSDT") is not None
        assert st.remove_position("ETHUSDT") is None


# ── natural close releases the PortfolioState slot ─────────────────────

class TestNaturalCloseReleasesPortfolioState:

    def test_sl_hit_releases_position(self, rig):
        tid = rig.open("ETHUSDT")
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 89.4})))
        assert not rig.state.has_position("ETHUSDT")
        assert rig.state.position_count == 0
        assert rig.jrn.get_open_trades() == []

    def test_tp_hit_releases_position_and_attribution_is_still_recorded(self, rig):
        tid = rig.open("ETHUSDT")
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 120.5})))
        assert not rig.state.has_position("ETHUSDT")
        attr = rig.jrn.get_trade_attribution(tid)
        assert attr["result"] == "WIN"
        assert attr["source"] == "TP"                      # unchanged behavior, guarded
        assert rig.lc.get_state("ETHUSDT").value == "CLOSED"

    def test_only_the_closed_symbol_is_released(self, rig):
        rig.open("ETHUSDT")
        rig.open("SOLUSDT")
        dp = _DataProvider({"ETHUSDT": 89.4, "SOLUSDT": 101.0}, open_symbols=("SOLUSDT",))
        main_module.monitor_open_trades(rig.sys(dp))
        assert rig.state.held_symbols == ["SOLUSDT"]       # still open on the exchange

    def test_released_symbol_is_in_cooldown_not_already_held(self, rig):
        rig.open("ETHUSDT")
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 89.4})))
        decision = rig.pm.decide([make_opportunity("ETHUSDT", 1)], make_risk_engine(), rig.state, 1000.0)
        assert [(r.symbol, r.reason) for r in decision.rejected] == [("ETHUSDT", "in_cooldown")]

    def test_naturally_closed_trades_do_not_exhaust_max_positions(self, rig):
        # The capacity-leak consequence: fill every slot, stop them all out
        # on the exchange, then ask for a brand-new symbol.
        n = rig.pm.limits.max_positions
        symbols = [f"S{i}USDT" for i in range(n)]
        for s in symbols:
            rig.open(s)
        dp = _DataProvider({s: 89.4 for s in symbols})
        main_module.monitor_open_trades(rig.sys(dp))
        assert rig.state.position_count == 0
        decision = rig.pm.decide([make_opportunity("NEWUSDT", 1)], make_risk_engine(), rig.state, 1000.0)
        assert [a.symbol for a in decision.selected] == ["NEWUSDT"]
        assert decision.rejected == []

    def test_position_with_a_different_trade_id_is_not_evicted(self, rig):
        # Journal row #1 is found closed, but PortfolioState now holds a
        # DIFFERENT trade's position for that symbol (e.g. replaced then
        # reopened) — it must survive.
        tid = rig.open("ETHUSDT")
        rig.state.add_position(PortfolioPosition(
            symbol="ETHUSDT", direction="LONG", entry_price=100.0, quantity=1.0, leverage=5,
            notional=100.0, margin_used=20.0, unrealized_pnl=0.0,
            state=PositionState.OPEN, opened_at=time.time(), trade_id=tid + 999,
        ))
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 89.4})))
        assert rig.state.get_position("ETHUSDT").trade_id == tid + 999


# ── robustness: the journal close must never depend on the release ─────

class TestReleaseNeverBlocksTheJournalClose:

    def test_duplicate_close_guard_path_still_releases(self, rig):
        # Another path (e.g. reconciliation) already closed the lifecycle
        # handle; the loop's direct-write fallback must still free the slot.
        tid = rig.open("ETHUSDT")
        handle = rig.lc.request_exit("ETHUSDT", main_module.CloseSource.RECONCILIATION, "x", trade_id=tid)
        rig.lc.exit_executing(handle)
        rig.lc.exit_failed(handle, reason="x")             # terminal -> request_exit returns None
        main_module.monitor_open_trades(rig.sys(_DataProvider({"ETHUSDT": 89.4})))
        assert not rig.state.has_position("ETHUSDT")
        assert rig.jrn.get_open_trades() == []

    def test_no_lifecycle_in_sys_still_releases_and_closes(self, rig):
        rig.open("ETHUSDT")
        sysd = rig.sys(_DataProvider({"ETHUSDT": 89.4}))
        del sysd["trade_lifecycle"]
        main_module.monitor_open_trades(sysd)
        assert not rig.state.has_position("ETHUSDT")
        assert rig.jrn.get_open_trades() == []

    def test_release_failure_does_not_stop_the_journal_close(self, rig):
        rig.open("ETHUSDT")

        class _Exploding(PortfolioState):
            def remove_position_for_trade(self, symbol, trade_id):
                raise RuntimeError("boom")

        sysd = rig.sys(_DataProvider({"ETHUSDT": 89.4}), portfolio_state=_Exploding())
        main_module.monitor_open_trades(sysd)
        assert rig.jrn.get_open_trades() == []

    def test_sys_without_portfolio_state_is_fine(self, rig):
        rig.open("ETHUSDT")
        sysd = rig.sys(_DataProvider({"ETHUSDT": 89.4}))
        del sysd["portfolio_state"]
        main_module.monitor_open_trades(sysd)
        assert rig.jrn.get_open_trades() == []


# ── single-symbol path: behavior unchanged ─────────────────────────────

class TestSingleSymbolPathUnchanged:

    def test_portfolio_state_untouched_when_scheduler_disabled(self, rig, monkeypatch):
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
        rig.open("ETHUSDT")

        class _SingleDP:
            def get_position_info(self, symbol=None):
                return None                                 # flat -> journal rows get closed

            def get_mark_price(self, symbol=None):
                return 89.4

        main_module.monitor_open_trades(rig.sys(_SingleDP()))
        assert rig.jrn.get_open_trades() == []              # journal still closed as before
        assert rig.state.has_position("ETHUSDT")            # single-symbol path never touches it
