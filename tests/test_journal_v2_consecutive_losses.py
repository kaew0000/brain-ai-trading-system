"""tests/test_journal_v2_consecutive_losses.py

Regression coverage for the 2026-08-31 cross-lane consecutive-loss bug:
journal.journal_v2.TradeJournalV2.get_consecutive_losses() used to query
across every execution_lane combined, so the always-on background
training lane's frequent, expected losses (see training_lane/
training_lane_runner.py -- that lane exists specifically to bust and
reset a small auto-training balance) could trip RiskEngine's LIVE-trading
gate even with zero live trades having happened.

No dedicated test file previously existed for journal/journal_v2.py
directly (tests/test_execution.py's TestRiskEngine-adjacent fixtures use
the older analytics.trade_journal.TradeJournal, a different class).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from journal.journal_v2 import TradeJournalV2, TradeRecord

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    # NOTE: deliberately NOT using db_path=":memory:" here -- see
    # database/db.py's `_memory_connections` module-level cache, which
    # shares one single connection across *every* TradeJournalV2(":memory:")
    # instance for the whole process (by design, for a different use
    # case). Using a real temp-file path per test gives each test its own
    # isolated database, matching the pattern tests/test_execution.py's
    # `tmp_journal` fixture already uses for exactly this reason.
    return TradeJournalV2(db_path=str(tmp_path / "test_journal_v2.db"))


def _record(direction="LONG"):
    rec = TradeRecord()
    rec.timestamp = datetime.now(timezone.utc).isoformat()
    rec.symbol = "BTCUSDT"
    rec.direction = direction
    rec.regime = "TREND"
    rec.bos = 1
    rec.fvg = 1
    rec.entry_price = 50_000.0
    rec.stop_loss = 49_500.0
    rec.take_profit = 51_000.0
    rec.confidence = 77.78
    rec.score = 7
    rec.result = "OPEN"
    rec.pnl = 0.0
    return rec


def _save_closed_trade(journal, execution_lane, result, pnl=-50.0):
    tid = journal.save_trade(_record(), execution_lane=execution_lane)
    journal.update_trade_result(tid, result, 49_500.0 if result == "LOSS" else 51_000.0, pnl)
    return tid


# ── No filter (backward-compatible default) ─────────────────────────────

def test_no_filter_counts_zero_initially(journal):
    assert journal.get_consecutive_losses() == 0


def test_no_filter_counts_across_every_lane_combined(journal):
    """Documents the pre-fix (still-available) behavior: with no
    execution_lane argument, losses from every lane count together --
    this is what made the original bug possible when RiskEngine called
    this with no filter at all."""
    _save_closed_trade(journal, "TRAINING", "LOSS")
    _save_closed_trade(journal, "PAPER", "LOSS")
    _save_closed_trade(journal, "LIVE", "LOSS")
    assert journal.get_consecutive_losses() == 3


# ── LIVE-only filter (the actual fix, used by RiskEngine) ───────────────

def test_live_filter_ignores_training_and_paper_losses(journal):
    """The core regression case: three TRAINING-lane losses (normal,
    expected background-lane activity) must NOT count toward the
    LIVE-scoped streak that gates real trading."""
    _save_closed_trade(journal, "TRAINING", "LOSS")
    _save_closed_trade(journal, "TRAINING", "LOSS")
    _save_closed_trade(journal, "TRAINING", "LOSS")
    assert journal.get_consecutive_losses(execution_lane="LIVE") == 0
    # Unfiltered view still shows them -- confirms the filter, not just an
    # empty table, is what's producing the zero above.
    assert journal.get_consecutive_losses() == 3


def test_live_filter_counts_only_live_losses(journal):
    _save_closed_trade(journal, "PAPER", "LOSS")
    _save_closed_trade(journal, "LIVE", "LOSS")
    _save_closed_trade(journal, "LIVE", "LOSS")
    _save_closed_trade(journal, "TRAINING", "LOSS")
    assert journal.get_consecutive_losses(execution_lane="LIVE") == 2


def test_live_filter_streak_resets_on_live_win_even_with_later_training_losses(journal):
    """Training-lane losses recorded *after* a LIVE win must not resurrect
    a broken LIVE streak."""
    _save_closed_trade(journal, "LIVE", "LOSS")
    _save_closed_trade(journal, "LIVE", "WIN", pnl=50.0)
    _save_closed_trade(journal, "TRAINING", "LOSS")
    _save_closed_trade(journal, "TRAINING", "LOSS")
    assert journal.get_consecutive_losses(execution_lane="LIVE") == 0


def test_live_filter_with_no_live_trades_at_all_is_zero_not_blocking(journal):
    """A fresh deployment (or one running purely in PAPER/dev-test mode)
    with zero LIVE trades ever recorded must never be blocked by the
    LIVE-scoped gate -- this was the exact symptom observed in
    production: 'Consecutive losses: 3/3' at the very first boot, before
    any live trade had happened."""
    for _ in range(5):
        _save_closed_trade(journal, "TRAINING", "LOSS")
    assert journal.get_consecutive_losses(execution_lane="LIVE") == 0


def test_invalid_execution_lane_raises(journal):
    with pytest.raises(ValueError):
        journal.get_consecutive_losses(execution_lane="NOT_A_REAL_LANE")
