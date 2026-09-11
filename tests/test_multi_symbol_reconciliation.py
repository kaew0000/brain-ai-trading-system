"""tests/test_multi_symbol_reconciliation.py — V16 §62.

system_health/reconciliation.py's ReconciliationEngine.run() (and
system_health/recovery_engine.py's RecoveryEngine, which acts on its
output) were single-symbol-hardcoded — both only ever checked
settings.SYMBOL, flagged as a known follow-up when §60 made that
dangerous rather than merely incomplete (recovery_engine.py's
auto-clear-on-exchange-flat logic could delete the journal record of a
real, open, non-default-symbol position). This file covers the fix:

  - ReconciliationEngine.run_all_symbols() — one comparison per symbol
    discovered across exchange positions / open journal trades /
    portfolio_state, each with independent suppression state.
  - RecoveryEngine's ghost-clearing and orphan-protection actions now
    act on the real mismatching symbol, not a hardcoded settings.SYMBOL.
  - RecoveryEngine tracks multiple simultaneous orphan holds (one per
    symbol) instead of a single global one.
  - main.py::run_position_reconciliation()'s SCHEDULER_ENABLED dispatch.

run()'s own pre-existing single-symbol behavior is NOT re-tested here
in depth — tests/test_reconciliation.py already covers _classify()
exhaustively, and that logic is untouched (still symbol-agnostic by
itself, same as before §62).
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


@dataclass
class _FakePortfolioPosition:
    direction: str
    quantity: float


def _sys(**overrides) -> dict:
    base = {
        "data_provider":  None,
        "paper_engine":   None,
        "journal_v2":     None,
        "portfolio_state": None,
        "event_bus":      MagicMock(),
    }
    base.update(overrides)
    return base


def _multi_dp(positions: dict[str, dict]):
    """positions: {symbol: {"side":..., "positionAmt":...}} for symbols
    WITH a position; a symbol absent from this dict means flat."""
    dp = MagicMock()

    def _get_position_info(symbol=None):
        return positions.get(symbol)

    def _get_all_positions():
        return [dict(p, symbol=s) for s, p in positions.items()]

    dp.get_position_info.side_effect = _get_position_info
    dp.get_all_positions.side_effect = _get_all_positions
    return dp


def _multi_journal(open_trades: list[dict], total_trades: int | None = None):
    jrn = MagicMock()
    jrn.get_open_trades.return_value = open_trades
    jrn.get_trades.return_value = [None] * (total_trades if total_trades is not None else len(open_trades))
    return jrn


# ─────────────────────────────────────────────────────────────────────────────
# ReconciliationEngine.run_all_symbols()
# ─────────────────────────────────────────────────────────────────────────────
class TestDiscoverSymbols:

    def test_discovers_from_exchange_positions(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        found = eng._discover_symbols(_sys(data_provider=dp))
        assert found == {"XRPUSDT"}

    def test_discovers_from_open_journal_trades(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _multi_journal([{"id": 1, "symbol": "DOGEUSDT", "direction": "LONG", "quantity": 500}])
        found = eng._discover_symbols(_sys(journal_v2=jrn))
        assert found == {"DOGEUSDT"}

    def test_discovers_from_portfolio_state(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        ps = MagicMock()
        ps.held_symbols.return_value = ["ADAUSDT"]
        found = eng._discover_symbols(_sys(portfolio_state=ps))
        assert found == {"ADAUSDT"}

    def test_union_across_all_three_sources_deduplicated(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({"BTCUSDT": {"side": "LONG", "positionAmt": 0.01}})
        jrn = _multi_journal([{"id": 1, "symbol": "BTCUSDT", "direction": "LONG", "quantity": 0.01},
                               {"id": 2, "symbol": "XRPUSDT", "direction": "SHORT", "quantity": 200}])
        ps = MagicMock()
        ps.held_symbols.return_value = ["DOGEUSDT"]
        found = eng._discover_symbols(_sys(data_provider=dp, journal_v2=jrn, portfolio_state=ps))
        assert found == {"BTCUSDT", "XRPUSDT", "DOGEUSDT"}

    def test_source_failure_does_not_block_the_others(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = MagicMock()
        dp.get_all_positions.side_effect = RuntimeError("exchange down")
        jrn = _multi_journal([{"id": 1, "symbol": "XRPUSDT", "direction": "LONG", "quantity": 100}])
        found = eng._discover_symbols(_sys(data_provider=dp, journal_v2=jrn))
        assert found == {"XRPUSDT"}


class TestRunAllSymbolsIndependence:
    """The core §62 fix: two symbols mismatching at once are each
    tracked/suppressed on their own."""

    def test_mismatch_in_one_symbol_does_not_affect_a_clean_symbol(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        # XRPUSDT: exchange open, journal flat-with-history -> CRITICAL presence mismatch.
        # DOGEUSDT: both flat -> no mismatch.
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _multi_journal([], total_trades=5)
        events = eng.run_all_symbols(_sys(data_provider=dp, journal_v2=jrn))
        assert len(events) == 1
        assert events[0].symbol == "XRPUSDT"
        assert events[0].mismatch_type == "PRESENCE_MISMATCH"

    def test_two_simultaneously_mismatching_symbols_both_reported(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({
            "XRPUSDT":  {"side": "LONG",  "positionAmt": 100},
            "DOGEUSDT": {"side": "SHORT", "positionAmt": 500},
        })
        jrn = _multi_journal([], total_trades=5)
        events = eng.run_all_symbols(_sys(data_provider=dp, journal_v2=jrn))
        symbols = {e.symbol for e in events}
        assert symbols == {"XRPUSDT", "DOGEUSDT"}

    def test_suppression_is_per_symbol_not_shared(self):
        """Second identical run: XRPUSDT's mismatch is suppressed (same
        as before §62's per-symbol split), but a FRESH DOGEUSDT mismatch
        that appears on this run must still fire -- proving the two
        symbols' suppression signatures don't collide."""
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _multi_journal([], total_trades=5)
        s = _sys(data_provider=dp, journal_v2=jrn)

        first = eng.run_all_symbols(s)
        assert len(first) == 1 and first[0].symbol == "XRPUSDT"

        second = eng.run_all_symbols(s)
        assert second == []   # identical XRPUSDT mismatch suppressed

        # Now DOGEUSDT also develops a mismatch.
        dp2 = _multi_dp({
            "XRPUSDT":  {"side": "LONG", "positionAmt": 100},
            "DOGEUSDT": {"side": "SHORT", "positionAmt": 300},
        })
        third = eng.run_all_symbols(_sys(data_provider=dp2, journal_v2=jrn))
        assert len(third) == 1
        assert third[0].symbol == "DOGEUSDT"   # fresh, not suppressed

    def test_duplicate_journal_trades_scoped_per_symbol(self):
        """Two open trades total, but for DIFFERENT symbols -- must NOT
        trigger DUPLICATE_JOURNAL_TRADES (that's a per-symbol invariant
        once more than one symbol can legitimately be open at once)."""
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({
            "XRPUSDT":  {"side": "LONG", "positionAmt": 100},
            "DOGEUSDT": {"side": "SHORT", "positionAmt": 300},
        })
        jrn = _multi_journal([
            {"id": 1, "symbol": "XRPUSDT", "direction": "LONG", "quantity": 100},
            {"id": 2, "symbol": "DOGEUSDT", "direction": "SHORT", "quantity": 300},
        ])
        events = eng.run_all_symbols(_sys(data_provider=dp, journal_v2=jrn))
        assert events == []   # both symbols agree, no mismatch at all

    def test_genuine_duplicate_within_one_symbol_still_detected(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _multi_journal([
            {"id": 1, "symbol": "XRPUSDT", "direction": "LONG", "quantity": 100},
            {"id": 2, "symbol": "XRPUSDT", "direction": "LONG", "quantity": 100},
        ])
        events = eng.run_all_symbols(_sys(data_provider=dp, journal_v2=jrn))
        assert len(events) == 1
        assert events[0].mismatch_type == "DUPLICATE_JOURNAL_TRADES"
        assert events[0].symbol == "XRPUSDT"


class TestMultiSymbolAccessors:

    def test_get_recent_for_symbol_isolated_from_default(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _multi_journal([], total_trades=5)
        eng.run_all_symbols(_sys(data_provider=dp, journal_v2=jrn))
        assert len(eng.get_recent_for_symbol("XRPUSDT")) == 1
        assert eng.get_recent_for_symbol("DOGEUSDT") == []
        assert eng.get_recent() == []   # run()'s own buffer, untouched

    def test_run_still_populates_only_the_default_key(self):
        """run() (classic single-symbol path) must not show up in the
        multi-symbol accessors -- they're separate state (see module
        docstring)."""
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = {"side": "LONG", "positionAmt": 0.01}
        jrn = _multi_journal([], total_trades=5)
        eng.run(_sys(data_provider=dp, journal_v2=jrn))
        assert len(eng.get_recent()) == 1
        assert eng.status_all_symbols() == {}


class TestReconciliationEventCarriesSymbol:

    def test_run_all_symbols_event_has_real_symbol(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = _multi_dp({"XRPUSDT": {"side": "LONG", "positionAmt": 100}})
        jrn = _multi_journal([], total_trades=5)
        events = eng.run_all_symbols(_sys(data_provider=dp, journal_v2=jrn))
        assert events[0].symbol == "XRPUSDT"
        assert events[0].to_dict()["symbol"] == "XRPUSDT"

    def test_classic_run_event_symbol_is_settings_symbol(self):
        from config.settings import settings
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = {"side": "LONG", "positionAmt": 0.01}
        jrn = _multi_journal([], total_trades=5)
        evt = eng.run(_sys(data_provider=dp, journal_v2=jrn))
        assert evt.symbol == settings.SYMBOL


# ─────────────────────────────────────────────────────────────────────────────
# RecoveryEngine — symbol-aware ghost clearing / orphan protection
# ─────────────────────────────────────────────────────────────────────────────
def _evt(symbol, mismatch_type="PRESENCE_MISMATCH", **views):
    from system_health.reconciliation import ReconciliationEvent
    defaults = {"exchange_view": {}, "journal_view": {}, "bot_view": {}}
    defaults.update(views)
    return ReconciliationEvent(
        id="x", timestamp="t", mismatch_type=mismatch_type,
        severity="critical", detail="d", symbol=symbol, **defaults,
    )


class TestGhostClearingUsesRealSymbol:

    def test_clear_ghost_journal_row_uses_event_symbol_not_settings_symbol(self):
        from config.settings import settings
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        jrn = MagicMock()
        lifecycle = MagicMock()
        handle = MagicMock()
        lifecycle.request_exit.return_value = handle
        s = _sys(journal_v2=jrn, trade_lifecycle=lifecycle)

        evt = _evt("XRPUSDT", exchange_view={"has_position": False},
                    journal_view={"has_position": True, "trade_id": 7},
                    bot_view={"has_position": False})
        assert "XRPUSDT" != settings.SYMBOL   # sanity: proves this isn't a no-op default
        eng.attempt_reconciliation_recovery(evt, s)

        lifecycle.request_exit.assert_called_once()
        args, kwargs = lifecycle.request_exit.call_args
        assert args[0] == "XRPUSDT"

    def test_clear_runtime_ghost_uses_event_symbol(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        ps = MagicMock()
        ps.remove_position.return_value = _FakePortfolioPosition("LONG", 100)
        s = _sys(portfolio_state=ps)

        evt = _evt("DOGEUSDT", exchange_view={"has_position": False},
                    journal_view={"has_position": False},
                    bot_view={"has_position": True, "source": "portfolio_state"})
        eng.attempt_reconciliation_recovery(evt, s)

        ps.remove_position.assert_called_once_with("DOGEUSDT")


class TestOrphanProtectRoutesToCorrectSymbolManager:

    def test_uses_get_manager_when_trade_manager_is_symbol_aware(self):
        """Simulates execution/execution_coordinator.py's ExecutionCoordinator
        shape: has get_manager(symbol) -> TradeManager. Must route SL
        placement through the SYMBOL-SPECIFIC manager, not fall through
        to whatever the coordinator's own default happens to be."""
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = {
            "symbol": "XRPUSDT", "side": "LONG", "positionAmt": 100.0,
            "entryPrice": 1.0, "markPrice": 1.01, "leverage": 5,
        }
        dp.get_account_balance.return_value = 10_000.0

        xrp_manager = MagicMock(spec=["place_stop_loss"])
        xrp_manager.place_stop_loss.return_value = {"orderId": 1}
        btc_manager = MagicMock(spec=["place_stop_loss"])  # the WRONG one

        coordinator = MagicMock(spec=["get_manager"])
        coordinator.get_manager.side_effect = (
            lambda symbol=None: xrp_manager if symbol == "XRPUSDT" else btc_manager
        )

        s = _sys(data_provider=dp, trade_manager=coordinator, risk_engine=MagicMock())
        evt = _evt("XRPUSDT", exchange_view={"has_position": True},
                    journal_view={"has_position": False}, bot_view={"has_position": True})

        result = eng.attempt_reconciliation_recovery(evt, s)

        assert result == "orphan_sl_placed_and_holding"
        coordinator.get_manager.assert_called_once_with("XRPUSDT")
        xrp_manager.place_stop_loss.assert_called_once()
        btc_manager.place_stop_loss.assert_not_called()

    def test_falls_back_to_trade_manager_itself_when_not_symbol_aware(self):
        """A plain TradeManager (no get_manager) -- e.g. the classic
        single-symbol path -- must still work exactly as before §62."""
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        dp = MagicMock()
        dp.get_position_info.return_value = {
            "symbol": "BTCUSDT", "side": "LONG", "positionAmt": 0.05,
            "entryPrice": 67000.0, "markPrice": 67100.0, "leverage": 5,
        }
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock(spec=["place_stop_loss"])
        tm.place_stop_loss.return_value = {"orderId": 1}
        s = _sys(data_provider=dp, trade_manager=tm, risk_engine=MagicMock())
        evt = _evt("BTCUSDT", exchange_view={"has_position": True},
                    journal_view={"has_position": False}, bot_view={"has_position": True})

        result = eng.attempt_reconciliation_recovery(evt, s)

        assert result == "orphan_sl_placed_and_holding"
        tm.place_stop_loss.assert_called_once()


class TestMultipleSimultaneousOrphanHolds:

    def _orphan_evt(self, symbol):
        return _evt(symbol, exchange_view={"has_position": True},
                    journal_view={"has_position": False}, bot_view={"has_position": True})

    def _mk_sys(self, symbol, entry=1.0):
        dp = MagicMock()
        dp.get_position_info.return_value = {
            "symbol": symbol, "side": "LONG", "positionAmt": 100.0,
            "entryPrice": entry, "markPrice": entry * 1.01, "leverage": 5,
        }
        dp.get_account_balance.return_value = 10_000.0
        tm = MagicMock(spec=["place_stop_loss"])
        tm.place_stop_loss.return_value = {"orderId": 1}
        return _sys(data_provider=dp, trade_manager=tm, risk_engine=MagicMock())

    def test_two_symbols_both_tracked_independently(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        eng.attempt_reconciliation_recovery(self._orphan_evt("XRPUSDT"), self._mk_sys("XRPUSDT"))
        eng.attempt_reconciliation_recovery(self._orphan_evt("DOGEUSDT"), self._mk_sys("DOGEUSDT"))

        holds = eng.get_orphan_holds()
        assert {h["symbol"] for h in holds} == {"XRPUSDT", "DOGEUSDT"}

    def test_acknowledging_one_symbol_leaves_the_other_and_leaves_risk_held(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        risk = MagicMock()
        s1 = self._mk_sys("XRPUSDT"); s1["risk_engine"] = risk
        s2 = self._mk_sys("DOGEUSDT"); s2["risk_engine"] = risk
        eng.attempt_reconciliation_recovery(self._orphan_evt("XRPUSDT"), s1)
        eng.attempt_reconciliation_recovery(self._orphan_evt("DOGEUSDT"), s2)

        result = eng.acknowledge_orphaned_position(sys=s1, operator="nanthachai", symbol="XRPUSDT")

        assert result == "cleared"
        remaining = {h["symbol"] for h in eng.get_orphan_holds()}
        assert remaining == {"DOGEUSDT"}
        # A DIFFERENT symbol is still unprotected -- must NOT resume trading.
        risk.clear_manual_hold.assert_not_called()

    def test_acknowledging_the_last_one_resumes_trading(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        risk = MagicMock()
        s = self._mk_sys("XRPUSDT"); s["risk_engine"] = risk
        eng.attempt_reconciliation_recovery(self._orphan_evt("XRPUSDT"), s)

        result = eng.acknowledge_orphaned_position(sys=s, operator="nanthachai", symbol="XRPUSDT")

        assert result == "cleared"
        assert eng.get_orphan_holds() == []
        risk.clear_manual_hold.assert_called_once()

    def test_no_symbol_arg_clears_all_matching_pre_62_zero_arg_behavior(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        risk = MagicMock()
        s1 = self._mk_sys("XRPUSDT"); s1["risk_engine"] = risk
        eng.attempt_reconciliation_recovery(self._orphan_evt("XRPUSDT"), s1)

        result = eng.acknowledge_orphaned_position(sys=s1, operator="nanthachai")  # no symbol=

        assert result == "cleared"
        assert eng.get_orphan_holds() == []
        risk.clear_manual_hold.assert_called_once()

    def test_get_orphan_hold_singular_returns_one_of_the_holds_for_back_compat(self):
        from system_health.recovery_engine import RecoveryEngine
        eng = RecoveryEngine()
        eng.attempt_reconciliation_recovery(self._orphan_evt("XRPUSDT"), self._mk_sys("XRPUSDT"))
        assert eng.get_orphan_hold()["symbol"] == "XRPUSDT"


# ─────────────────────────────────────────────────────────────────────────────
# main.py::run_position_reconciliation() dispatch
# ─────────────────────────────────────────────────────────────────────────────
class TestMainPyDispatch:

    def test_scheduler_enabled_calls_run_all_symbols(self, monkeypatch):
        from config.settings import settings
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
        engine = MagicMock()
        main_module.run_position_reconciliation({"reconciliation_engine": engine})
        engine.run_all_symbols.assert_called_once()
        engine.run.assert_not_called()

    def test_scheduler_disabled_calls_run(self, monkeypatch):
        from config.settings import settings
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)
        engine = MagicMock()
        main_module.run_position_reconciliation({"reconciliation_engine": engine})
        engine.run.assert_called_once()
        engine.run_all_symbols.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# api/app.py — /api/system/reconciliation* multi-symbol surfacing
# ─────────────────────────────────────────────────────────────────────────────
class TestReconciliationAPIMultiSymbol:

    def _client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        return TestClient(app, raise_server_exceptions=False)

    def test_get_reconciliation_includes_plural_fields(self, monkeypatch):
        from system_health.recovery_engine import reset_recovery_engine
        from system_health.reconciliation import reset_reconciliation_engine
        reset_reconciliation_engine()
        reset_recovery_engine()
        with self._client() as c:
            r = c.get("/api/system/reconciliation")
        assert r.status_code == 200
        data = r.json()["data"]
        assert "orphan_holds" in data
        assert "status_by_symbol" in data
        assert data["orphan_holds"] == []
        assert data["status_by_symbol"] == {}

    def test_acknowledge_accepts_symbol_in_body(self, monkeypatch):
        from system_health.recovery_engine import get_recovery_engine, reset_recovery_engine
        reset_recovery_engine()
        recovery = get_recovery_engine()
        recovery._orphan_holds["XRPUSDT"] = {"symbol": "XRPUSDT", "reason": "test"}
        recovery._orphan_holds["DOGEUSDT"] = {"symbol": "DOGEUSDT", "reason": "test"}

        with self._client() as c:
            r = c.post("/api/system/reconciliation/acknowledge", json={"symbol": "XRPUSDT"})
        assert r.status_code == 200
        remaining = {h["symbol"] for h in r.json()["data"]["orphan_holds"]}
        assert remaining == {"DOGEUSDT"}

    def test_acknowledge_with_no_body_clears_all(self, monkeypatch):
        from system_health.recovery_engine import get_recovery_engine, reset_recovery_engine
        reset_recovery_engine()
        recovery = get_recovery_engine()
        recovery._orphan_holds["XRPUSDT"] = {"symbol": "XRPUSDT", "reason": "test"}

        with self._client() as c:
            r = c.post("/api/system/reconciliation/acknowledge")
        assert r.status_code == 200
        assert r.json()["data"]["orphan_holds"] == []
