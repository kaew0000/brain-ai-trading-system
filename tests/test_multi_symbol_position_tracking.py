"""tests/test_multi_symbol_position_tracking.py — V16 §60.

Covers the corruption bug found while wiring up true multi-symbol
trading: data_provider.get_position_info() only ever checked
settings.SYMBOL, so main.py's monitor_open_trades() (scheduled
unconditionally, every 30s) would read a genuinely-still-open position
in any OTHER symbol as "no position" and mark it CLOSED in the
journal.

Two layers:
1. data/binance_provider.py::BinanceDataProvider.get_position_info(symbol=...)
   and the new get_all_positions() — thin wrappers around the exchange
   client, tested against a fake trade_client.
2. main.py::monitor_open_trades()'s SCHEDULER_ENABLED-aware branch —
   the actual bug fix, tested via the real production function with a
   fake data provider/journal (same pattern as
   tests/test_trade_lifecycle_integration.py).
"""
from __future__ import annotations

import pytest

from config.settings import settings
from data.binance_provider import BinanceDataProvider

pytestmark = pytest.mark.unit


def _raw_position(symbol, amt, entry=100.0, mark=105.0, side_leverage=5):
    return {
        "symbol": symbol, "positionAmt": str(amt), "entryPrice": str(entry),
        "unRealizedProfit": "0.0", "leverage": str(side_leverage), "markPrice": str(mark),
    }


class _FakeTradeClient:
    """Mimics binance.um_futures.UMFutures's get_position_risk: with a
    symbol kwarg, Binance returns only that symbol's row(s); without
    one, every symbol with a row (including flat/zero ones some
    accounts carry) comes back."""
    def __init__(self, all_rows):
        self.all_rows = all_rows
        self.calls = []

    def get_position_risk(self, symbol=None, recvWindow=None):
        self.calls.append(symbol)
        if symbol is None:
            return self.all_rows
        return [r for r in self.all_rows if r["symbol"] == symbol]


def _bare_provider(rows, default_symbol="BTCUSDT"):
    """Construct a BinanceDataProvider without running __init__ (which
    needs real API keys / a live network client) — same
    bypass-the-constructor pattern this project's own convention favors
    for testing a thin wrapper method in isolation."""
    dp = object.__new__(BinanceDataProvider)
    dp.symbol = default_symbol
    dp.trade_client = _FakeTradeClient(rows)
    return dp


class TestGetPositionInfoSymbolParam:

    def test_defaults_to_self_symbol_unchanged(self):
        dp = _bare_provider([_raw_position("BTCUSDT", 0.01)], default_symbol="BTCUSDT")
        pos = dp.get_position_info()
        assert pos["symbol"] == "BTCUSDT"
        assert dp.trade_client.calls == ["BTCUSDT"]

    def test_explicit_symbol_overrides_default(self):
        dp = _bare_provider([_raw_position("XRPUSDT", 100.0)], default_symbol="BTCUSDT")
        pos = dp.get_position_info(symbol="XRPUSDT")
        assert pos["symbol"] == "XRPUSDT"
        assert dp.trade_client.calls == ["XRPUSDT"]

    def test_no_position_for_symbol_returns_none(self):
        dp = _bare_provider([], default_symbol="BTCUSDT")
        assert dp.get_position_info(symbol="XRPUSDT") is None


class TestGetAllPositions:

    def test_returns_every_nonzero_symbol(self):
        dp = _bare_provider([
            _raw_position("BTCUSDT", 0.0),      # flat -- excluded
            _raw_position("XRPUSDT", 500.0),
            _raw_position("DOGEUSDT", -1000.0),  # short
        ])
        positions = dp.get_all_positions()
        symbols = {p["symbol"] for p in positions}
        assert symbols == {"XRPUSDT", "DOGEUSDT"}
        doge = next(p for p in positions if p["symbol"] == "DOGEUSDT")
        assert doge["side"] == "SHORT"
        assert doge["positionAmt"] == 1000.0   # abs()

    def test_no_symbol_filter_sent_to_exchange(self):
        dp = _bare_provider([_raw_position("BTCUSDT", 1.0)])
        dp.get_all_positions()
        assert dp.trade_client.calls == [None]

    def test_empty_account_returns_empty_list(self):
        dp = _bare_provider([])
        assert dp.get_all_positions() == []


# ─────────────────────────────────────────────────────────────────────────────
# main.py::monitor_open_trades() -- the actual corruption-bug fix
# ─────────────────────────────────────────────────────────────────────────────
class FakeJournal:
    def __init__(self, open_trades):
        self._open_trades = open_trades
        self.calls = []

    def get_open_trades(self):
        return self._open_trades

    def update_trade_result(self, trade_id, result, exit_price, pnl):
        self.calls.append((trade_id, result, exit_price, pnl))
        return True


class FakeMultiSymbolDataProvider:
    def __init__(self, open_positions_by_symbol, mark_prices):
        self._open = open_positions_by_symbol   # {symbol: raw dict} still open on exchange
        self._marks = mark_prices                # {symbol: price}
        self.mark_price_calls = []

    def get_all_positions(self):
        return list(self._open.values())

    def get_position_info(self, symbol=None):
        # Only used by the pre-§60 single-symbol branch; multi-symbol
        # tests never expect this to be called.
        raise AssertionError("get_position_info() should not be called in scheduler mode")

    def get_mark_price(self, symbol=None):
        self.mark_price_calls.append(symbol)
        return self._marks[symbol]


def _open_trade(tid, symbol, direction="LONG", entry=100.0, sl=90.0, tp=110.0, qty=1.0):
    return {"id": tid, "symbol": symbol, "entry_price": str(entry), "stop_loss": str(sl),
            "take_profit": str(tp), "direction": direction, "quantity": str(qty)}


class TestMonitorOpenTradesMultiSymbol:

    def _run(self, monkeypatch, dp, jrn):
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)
        sys_dict = {"data_provider": dp, "journal_v2": jrn, "event_bus": None,
                    "trade_lifecycle": None}
        main_module.monitor_open_trades(sys_dict)

    def test_open_position_in_a_different_symbol_is_left_alone(self, monkeypatch):
        """The core corruption bug: an XRPUSDT position is still
        genuinely open on the exchange (BTCUSDT is not, and never was,
        part of this trade) -- must NOT be marked closed."""
        jrn = FakeJournal([_open_trade(1, "XRPUSDT")])
        dp = FakeMultiSymbolDataProvider(
            open_positions_by_symbol={"XRPUSDT": _raw_position("XRPUSDT", 500.0)},
            mark_prices={},
        )
        self._run(monkeypatch, dp, jrn)
        assert jrn.calls == []   # not closed

    def test_only_the_symbol_that_actually_closed_gets_processed(self, monkeypatch):
        jrn = FakeJournal([_open_trade(1, "BTCUSDT", entry=100, tp=110),
                            _open_trade(2, "XRPUSDT", entry=1.0, tp=1.1)])
        dp = FakeMultiSymbolDataProvider(
            # BTCUSDT still open; XRPUSDT no longer in the exchange's
            # position list -- it closed.
            open_positions_by_symbol={"BTCUSDT": _raw_position("BTCUSDT", 0.01)},
            mark_prices={"XRPUSDT": 1.11},
        )
        self._run(monkeypatch, dp, jrn)
        assert len(jrn.calls) == 1
        tid, result, exit_price, pnl = jrn.calls[0]
        assert tid == 2
        assert exit_price == 1.11
        # get_mark_price was asked about XRPUSDT specifically, not BTCUSDT.
        assert dp.mark_price_calls == ["XRPUSDT"]

    def test_per_symbol_mark_price_used_for_pnl_not_a_shared_value(self, monkeypatch):
        """Two different symbols closing in the same cycle must each
        get priced with THEIR OWN mark price."""
        jrn = FakeJournal([_open_trade(1, "XRPUSDT", entry=1.0, tp=1.1, qty=100),
                            _open_trade(2, "DOGEUSDT", entry=0.10, tp=0.11, qty=1000)])
        dp = FakeMultiSymbolDataProvider(
            open_positions_by_symbol={},   # both closed
            mark_prices={"XRPUSDT": 1.11, "DOGEUSDT": 0.111},
        )
        self._run(monkeypatch, dp, jrn)
        assert len(jrn.calls) == 2
        by_id = {c[0]: c for c in jrn.calls}
        assert by_id[1][2] == 1.11     # XRPUSDT's own mark
        assert by_id[2][2] == 0.111    # DOGEUSDT's own mark

    def test_mark_price_fetched_once_per_symbol_not_per_trade(self, monkeypatch):
        """Two open journal rows for the same symbol (e.g. a partial-
        fill artifact) must not double-fetch the mark price."""
        jrn = FakeJournal([_open_trade(1, "XRPUSDT", entry=1.0, tp=1.1),
                            _open_trade(2, "XRPUSDT", entry=1.0, tp=1.1)])
        dp = FakeMultiSymbolDataProvider(
            open_positions_by_symbol={}, mark_prices={"XRPUSDT": 1.11},
        )
        self._run(monkeypatch, dp, jrn)
        assert dp.mark_price_calls == ["XRPUSDT"]   # once, cached for the 2nd row

    def test_nothing_to_process_returns_without_touching_journal(self, monkeypatch):
        jrn = FakeJournal([_open_trade(1, "BTCUSDT"), _open_trade(2, "XRPUSDT")])
        dp = FakeMultiSymbolDataProvider(
            open_positions_by_symbol={
                "BTCUSDT": _raw_position("BTCUSDT", 0.01),
                "XRPUSDT": _raw_position("XRPUSDT", 500.0),
            },
            mark_prices={},
        )
        self._run(monkeypatch, dp, jrn)
        assert jrn.calls == []
        assert dp.mark_price_calls == []   # never even asked -- nothing closed

    def test_no_open_trades_short_circuits_before_any_position_check(self, monkeypatch):
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", True)

        class ExplodingDataProvider:
            def get_all_positions(self):
                raise AssertionError("must not be called when there are no open journal trades")

        sys_dict = {"data_provider": ExplodingDataProvider(), "journal_v2": FakeJournal([]),
                    "event_bus": None, "trade_lifecycle": None}
        main_module.monitor_open_trades(sys_dict)   # must not raise


class TestMonitorOpenTradesSingleSymbolModeUnchanged:
    """Regression guard: SCHEDULER_ENABLED=False (the default) must
    keep using the pre-§60 single get_position_info() check exactly as
    before -- get_all_positions() must never even be called."""

    def test_still_in_position_returns_without_calling_get_all_positions(self, monkeypatch):
        import main as main_module
        monkeypatch.setattr(settings, "SCHEDULER_ENABLED", False)

        class Explodes:
            def get_all_positions(self):
                raise AssertionError("single-symbol mode must not call get_all_positions()")
            def get_position_info(self):
                return {"symbol": "BTCUSDT"}

        jrn = FakeJournal([_open_trade(1, "BTCUSDT")])
        sys_dict = {"data_provider": Explodes(), "journal_v2": jrn,
                    "event_bus": None, "trade_lifecycle": None}
        main_module.monitor_open_trades(sys_dict)
        assert jrn.calls == []
