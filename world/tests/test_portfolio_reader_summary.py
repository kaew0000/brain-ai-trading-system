"""world/tests/test_portfolio_reader_summary.py — Phase W11

world/readers/portfolio_reader.py now accepts two raw shapes. This
file is entirely about proving both keep working, side by side, with
the same Reader instance.
"""
from __future__ import annotations

import pytest

from world.readers.base import DataSource
from world.readers.portfolio_reader import PortfolioReader, PortfolioSummary

pytestmark = pytest.mark.unit


class _StaticSource(DataSource):
    def __init__(self, raw):
        self._raw = raw

    def load_raw(self):
        return self._raw


# ── Phase W4 shape: raw is a bare list ──────────────────────────────────────

def test_bare_list_shape_still_works_unchanged():
    raw = [{"symbol": "BTCUSDT", "district": "portfolio-garden", "size_label": "medium"}]
    reader = PortfolioReader(_StaticSource(raw))
    positions = reader.read()
    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert reader.last_summary is None


def test_bare_list_shape_skips_bad_rows_same_as_before():
    raw = [{"symbol": "BTCUSDT"}, {"no_symbol_key": True}, {"symbol": "ETHUSDT"}]
    reader = PortfolioReader(_StaticSource(raw))
    positions = reader.read()
    assert [p.symbol for p in positions] == ["BTCUSDT", "ETHUSDT"]


# ── Phase W11 shape: raw is {"positions": [...], "summary": {...}} ─────────

def test_dict_shape_parses_positions_and_summary():
    raw = {
        "positions": [{"symbol": "BTCUSDT"}],
        "summary": {"dailyPnl": 42.0, "drawdown": 0.1, "winRate": 0.6, "avgRr": 1.5, "floatingPnl": -3.0},
    }
    reader = PortfolioReader(_StaticSource(raw))
    positions = reader.read()

    assert [p.symbol for p in positions] == ["BTCUSDT"]
    assert reader.last_summary == PortfolioSummary(
        daily_pnl=42.0, floating_pnl=-3.0, drawdown=0.1, win_rate=0.6, avg_rr=1.5,
    )


def test_dict_shape_with_no_summary_key_is_fine():
    raw = {"positions": [{"symbol": "BTCUSDT"}]}
    reader = PortfolioReader(_StaticSource(raw))
    reader.read()
    assert reader.last_summary is None


def test_dict_shape_with_no_positions_key_is_fine():
    raw = {"summary": {"drawdown": 0.2}}
    reader = PortfolioReader(_StaticSource(raw))
    positions = reader.read()
    assert positions == []
    assert reader.last_summary.drawdown == 0.2


def test_dict_shape_with_partial_summary_leaves_other_fields_none():
    raw = {"positions": [], "summary": {"drawdown": 0.2}}
    reader = PortfolioReader(_StaticSource(raw))
    reader.read()
    assert reader.last_summary.drawdown == 0.2
    assert reader.last_summary.daily_pnl is None
    assert reader.last_summary.win_rate is None


def test_last_summary_resets_between_reads():
    """A reader reused across ticks (as main.py's cached RuntimeManager
    wiring does) must not carry a stale summary from a previous
    capture that had one, into a capture that doesn't."""
    reader = PortfolioReader(_StaticSource({"positions": [], "summary": {"drawdown": 0.2}}))
    reader.read()
    assert reader.last_summary is not None

    reader.source = _StaticSource([{"symbol": "BTCUSDT"}])  # next tick: Phase W4 shape
    reader.read()
    assert reader.last_summary is None
