"""tests/test_risk_balance_gate_and_streak_epoch.py

Regression coverage for V16 §86 (live balance gate + stale-streak epoch).

Production symptom (2026-10-27 boot log): LIVE account balance 0.00 USDT, yet
the bot reported "CIRCUIT BREAKER TRIPPED: Consecutive losses: 3/3" -- three
LIVE-lane losses left in brain_bot_v13.db by an earlier, abruptly terminated
session. The real blocker (no funds) was never reported, and after funding the
account the stale streak would still have blocked trading.

Covered here:
  1. Zero/low balance is its own block reason, evaluated before the streak, and
     is NOT latched into _disabled_today (a deposit must resume trading at once).
  2. A funded account with a genuine 3-loss streak is STILL blocked (no loosening).
  3. unfunded -> funded transition starts a new streak epoch (old rows are kept).
  4. The unfunded marker and epoch survive a restart (abrupt shutdown).
  5. RISK_STREAK_RESET_ON_REFUND=False disables the epoch reset.
  6. An unconfigured MagicMock journal is never silently affected.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from config.settings import settings
from journal.journal_v2 import TradeJournalV2, TradeRecord
from risk.risk_engine import RiskEngine

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _instant_refund(monkeypatch):
    # the glitch guard (default 600 s) is covered by its own test below
    monkeypatch.setattr(settings, "RISK_REFUND_MIN_UNFUNDED_SECONDS", 0)


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test_balance_gate.db"))


def _loss(journal, lane="LIVE"):
    rec = TradeRecord()
    rec.timestamp = datetime.now(timezone.utc).isoformat()
    rec.symbol = "BTCUSDT"
    rec.direction = "SHORT"
    rec.entry_price, rec.stop_loss, rec.take_profit = 80_000.0, 81_000.0, 78_000.0
    rec.result = "OPEN"
    tid = journal.save_trade(rec, execution_lane=lane)
    journal.update_trade_result(tid, "LOSS", 81_000.0, -1.0)
    return tid


def _three_live_losses(journal):
    for _ in range(3):
        _loss(journal)


def test_zero_balance_reports_balance_not_streak(journal):
    _three_live_losses(journal)
    engine = RiskEngine(journal)
    ok, reason = engine.can_trade(0.0)
    assert ok is False
    assert "balance" in reason.lower()
    assert "consecutive" not in reason.lower()


def test_zero_balance_is_not_latched(journal):
    engine = RiskEngine(journal)
    engine.can_trade(0.0)
    assert engine._disabled_today is False


def test_zero_balance_without_any_trades_is_blocked(journal):
    ok, reason = RiskEngine(journal).can_trade(0.0)
    assert ok is False and "balance" in reason.lower()


def test_funded_account_with_real_streak_is_still_blocked(journal):
    _three_live_losses(journal)
    ok, reason = RiskEngine(journal).can_trade(500.0)
    assert ok is False
    assert "Consecutive losses" in reason


def test_refund_starts_new_epoch_and_keeps_old_rows(journal):
    _three_live_losses(journal)
    engine = RiskEngine(journal)
    assert engine.can_trade(0.0)[0] is False        # unfunded
    ok, reason = engine.can_trade(500.0)            # deposit arrives
    assert ok is True, reason
    # old history is archived, never deleted
    assert journal.get_consecutive_losses(execution_lane="LIVE") == 3
    # a genuine post-refund streak still trips the breaker
    for _ in range(3):
        _loss(journal)
    ok, reason = engine.can_trade(500.0)
    assert ok is False and "Consecutive losses: 3/" in reason


def test_unfunded_marker_survives_restart(journal):
    _three_live_losses(journal)
    RiskEngine(journal).can_trade(0.0)              # session 1 ends abruptly
    ok, reason = RiskEngine(journal).can_trade(500.0)   # session 2, funded
    assert ok is True, reason


def test_report_matches_gate_after_refund(journal):
    _three_live_losses(journal)
    engine = RiskEngine(journal)
    engine.can_trade(0.0)
    engine.can_trade(500.0)
    assert engine.report(500.0)["consecutive_losses"] == 0


def test_peek_agrees_with_gate_but_persists_nothing(journal):
    _three_live_losses(journal)
    engine = RiskEngine(journal)
    engine.can_trade(0.0)
    assert engine.peek_can_trade(500.0)[0] is True        # status matches the gate
    assert journal.get_risk_state("live_streak_epoch") is None   # ...without mutating
    assert engine.can_trade(500.0)[0] is True
    assert journal.get_risk_state("live_streak_epoch") is not None


def test_short_balance_glitch_does_not_wipe_real_streak(journal, monkeypatch):
    monkeypatch.setattr(settings, "RISK_REFUND_MIN_UNFUNDED_SECONDS", 600)
    _three_live_losses(journal)
    engine = RiskEngine(journal)
    engine.can_trade(0.0)                       # API glitch: "Balance: 0.00"
    ok, reason = engine.can_trade(500.0)        # next cycle: real balance back
    assert ok is False and "Consecutive losses" in reason
    assert journal.get_risk_state("live_unfunded_since") is None   # marker dropped


def test_long_unfunded_period_counts_as_refund(journal, monkeypatch):
    monkeypatch.setattr(settings, "RISK_REFUND_MIN_UNFUNDED_SECONDS", 600)
    _three_live_losses(journal)
    journal.set_risk_state("live_unfunded_since", "2026-10-20T00:00:00+00:00")
    assert RiskEngine(journal).can_trade(500.0)[0] is True


def test_flag_off_keeps_old_streak(journal, monkeypatch):
    monkeypatch.setattr(settings, "RISK_STREAK_RESET_ON_REFUND", False)
    _three_live_losses(journal)
    engine = RiskEngine(journal)
    engine.can_trade(0.0)
    ok, reason = engine.can_trade(500.0)
    assert ok is False and "Consecutive losses" in reason


def test_training_lane_losses_never_matter(journal):
    for _ in range(5):
        _loss(journal, lane="TRAINING")
    assert RiskEngine(journal).can_trade(500.0)[0] is True


def test_magicmock_journal_is_unaffected():
    journal = MagicMock()
    journal.get_consecutive_losses.return_value = 0
    journal.get_today_pnl.return_value = 0.0
    engine = RiskEngine(journal)
    assert engine.can_trade(1000.0)[0] is True
    assert engine.can_trade(0.0)[0] is False
