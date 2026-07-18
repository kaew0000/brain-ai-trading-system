"""tests/test_portfolio_state.py — V16 Phase 2A"""
from __future__ import annotations

import time

import pytest

from portfolio.portfolio_models import PortfolioPosition, PositionState
from portfolio.portfolio_state import PortfolioState

pytestmark = pytest.mark.unit


def _pos(symbol, notional=5_000, margin=1_000, sector=None, state=PositionState.OPEN):
    return PortfolioPosition(
        symbol=symbol, direction="LONG", entry_price=100, quantity=notional / 100,
        leverage=5, notional=notional, margin_used=margin, unrealized_pnl=0.0,
        state=state, opened_at=time.time(), sector=sector,
    )


class TestPositionTracking:

    def test_add_and_get_position(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT"))
        assert s.has_position("BTCUSDT")
        assert s.get_position("BTCUSDT").symbol == "BTCUSDT"

    def test_add_position_overwrites_same_symbol(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", notional=5_000))
        s.add_position(_pos("BTCUSDT", notional=9_000))
        assert s.position_count == 1
        assert s.get_position("BTCUSDT").notional == 9_000

    def test_remove_position(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT"))
        removed = s.remove_position("BTCUSDT")
        assert removed.symbol == "BTCUSDT"
        assert not s.has_position("BTCUSDT")

    def test_remove_missing_position_returns_none(self):
        s = PortfolioState()
        assert s.remove_position("BTCUSDT") is None

    def test_held_symbols_and_count(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT"))
        s.add_position(_pos("ETHUSDT"))
        assert s.position_count == 2
        assert set(s.held_symbols) == {"BTCUSDT", "ETHUSDT"}


class TestCapitalAndExposure:

    def test_reserved_capital_sums_margin(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", margin=1_000))
        s.add_position(_pos("ETHUSDT", margin=500))
        assert s.reserved_capital == 1_500

    def test_free_capital(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", margin=1_000))
        assert s.free_capital(10_000) == 9_000

    def test_free_capital_never_negative(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", margin=9_000))
        assert s.free_capital(5_000) == 0.0

    def test_symbol_exposure(self):
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", notional=5_000))
        assert s.symbol_exposure("BTCUSDT") == 5_000
        assert s.symbol_exposure("ETHUSDT") == 0.0

    def test_sector_exposure_zero_until_sector_engine_exists(self):
        """Every PortfolioPosition.sector is None until 2B — sector_exposure
        must return 0.0 for every sector today, not raise."""
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", notional=5_000, sector=None))
        assert s.sector_exposure("Layer1") == 0.0

    def test_sector_exposure_sums_when_sector_is_set(self):
        """Forward-compat check: once something DOES set .sector (tests,
        or 2B later), sector_exposure must aggregate correctly."""
        s = PortfolioState()
        s.add_position(_pos("BTCUSDT", notional=5_000, sector="Layer1"))
        s.add_position(_pos("ETHUSDT", notional=3_000, sector="Layer1"))
        s.add_position(_pos("DOGEUSDT", notional=1_000, sector="Meme"))
        assert s.sector_exposure("Layer1") == 8_000
        assert s.sector_exposure("Meme") == 1_000


class TestDrawdown:

    def test_no_peak_recorded_yet_gives_zero_drawdown(self):
        s = PortfolioState()
        assert s.portfolio_drawdown(10_000) == 0.0
        assert s.peak_balance == 10_000     # first observation becomes the peak

    def test_drawdown_below_peak(self):
        s = PortfolioState(peak_balance=10_000)
        assert s.portfolio_drawdown(9_000) == pytest.approx(0.10)

    def test_new_high_updates_peak_and_zeroes_drawdown(self):
        s = PortfolioState(peak_balance=10_000)
        assert s.portfolio_drawdown(11_000) == 0.0
        assert s.peak_balance == 11_000

    def test_record_balance_updates_peak_without_computing_drawdown(self):
        s = PortfolioState()
        s.record_balance(5_000)
        s.record_balance(7_000)
        s.record_balance(6_000)          # lower than peak — should not lower peak
        assert s.peak_balance == 7_000


class TestPnLFields:

    def test_daily_and_floating_pnl_are_plain_fields(self):
        s = PortfolioState(daily_pnl=-50.0, floating_pnl=120.0)
        assert s.daily_pnl == -50.0
        assert s.floating_pnl == 120.0

    def test_to_dict_includes_all_fields(self):
        s = PortfolioState(daily_pnl=10.0, floating_pnl=-5.0)
        s.add_position(_pos("BTCUSDT"))
        d = s.to_dict(balance=10_000)
        for key in ("positions", "position_count", "reserved_capital",
                    "free_capital", "risk_used", "daily_pnl", "floating_pnl",
                    "peak_balance", "drawdown"):
            assert key in d

    def test_to_dict_without_balance_leaves_balance_dependent_fields_none(self):
        s = PortfolioState()
        d = s.to_dict()
        assert d["free_capital"] is None
        assert d["drawdown"] is None
