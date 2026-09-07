"""tests/test_risk_override_persistence.py

Regression coverage for V16 BUG-LIVE-RISK-04 (2026-09-01): RiskEngine's
one-shot consecutive-loss override (BUG-LIVE-RISK-03, added 2026-08-31)
only lived in memory, so restarting the bot -- routine during normal
dev/test iteration -- silently discarded an operator's already-confirmed
override with no indication anything had been lost, forcing a re-run of
the same /api/system/risk/override-next-trade call after every restart.

Two things are covered here:
  1. journal.journal_v2.TradeJournalV2's new save/get/clear_risk_override()
     methods, against a real tmp_path-backed SQLite DB (project convention
     -- see tests/test_journal_v2_risk_gate_lane_scoping.py's fixture
     rationale for why :memory: isn't used here).
  2. risk.risk_engine.RiskEngine actually reading/writing through those
     methods at the right points, and -- critically -- that constructing
     RiskEngine with an unconfigured MagicMock() journal (the pattern
     used by nearly every other RiskEngine test in this suite:
     tests/test_execution.py, tests/test_p1b1_dynamic_risk.py,
     tests/test_audit_fixes.py, tests/test_agents.py,
     tests/test_capital_manager.py, tests/test_portfolio_manager.py)
     does NOT get silently armed by MagicMock's attribute
     auto-creation -- getattr(mock, "get_risk_override", None) returns a
     truthy MagicMock either way, so the restore logic must specifically
     require the persisted value to be a real string, not just truthy.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from journal.journal_v2 import TradeJournalV2
from risk.risk_engine import RiskEngine

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test_risk_override.db"))


# ── TradeJournalV2.save/get/clear_risk_override ─────────────────────────

def test_get_risk_override_is_none_when_nothing_saved(journal):
    assert journal.get_risk_override() is None


def test_save_then_get_round_trips(journal):
    journal.save_risk_override("stale streak from 2026-08-23, reviewed")
    assert journal.get_risk_override() == "stale streak from 2026-08-23, reviewed"


def test_save_overwrites_a_previous_value(journal):
    journal.save_risk_override("first reason")
    journal.save_risk_override("second reason")
    assert journal.get_risk_override() == "second reason"


def test_clear_removes_it(journal):
    journal.save_risk_override("some reason")
    journal.clear_risk_override()
    assert journal.get_risk_override() is None


def test_clear_when_nothing_saved_is_a_safe_noop(journal):
    journal.clear_risk_override()   # must not raise
    assert journal.get_risk_override() is None


def test_persists_across_separate_journal_instances_same_db_path(tmp_path):
    """The actual scenario this exists for: a bot restart constructs a
    brand-new TradeJournalV2 (and RiskEngine) pointed at the same
    on-disk DB file -- the override must still be there."""
    db_path = str(tmp_path / "test_risk_override_restart.db")
    j1 = TradeJournalV2(db_path=db_path)
    j1.save_risk_override("armed before restart")

    j2 = TradeJournalV2(db_path=db_path)   # simulates a fresh process
    assert j2.get_risk_override() == "armed before restart"


# ── RiskEngine integration: restore-on-init ──────────────────────────────

def test_risk_engine_restores_persisted_override_on_construction(journal):
    journal.save_risk_override("reviewed, confirmed stale")
    eng = RiskEngine(journal)
    assert eng.has_consecutive_loss_override() is True
    assert eng.consecutive_loss_override_reason() == "reviewed, confirmed stale"


def test_risk_engine_starts_unarmed_when_nothing_persisted(journal):
    eng = RiskEngine(journal)
    assert eng.has_consecutive_loss_override() is False


def test_restored_override_actually_bypasses_the_gate(journal):
    """Not just visible in state -- it must actually work, end to end,
    exactly like an override armed in the same process would."""
    journal.save_risk_override("restored override")
    eng = RiskEngine(journal)
    # streak=0 by default (no LIVE trades saved), so force a block via
    # settings patch would be more setup than needed here -- instead
    # save actual LIVE losses to genuinely trip the gate.
    from datetime import datetime, timezone
    from journal.journal_v2 import TradeRecord

    def _live_loss():
        rec = TradeRecord()
        rec.timestamp = datetime.now(timezone.utc).isoformat()
        rec.symbol, rec.direction, rec.regime = "BTCUSDT", "LONG", "TREND"
        rec.bos, rec.fvg = 1, 1
        rec.entry_price, rec.stop_loss, rec.take_profit = 50_000.0, 49_500.0, 51_000.0
        rec.confidence, rec.score, rec.result, rec.pnl = 77.0, 7, "OPEN", 0.0
        tid = journal.save_trade(rec, execution_lane="LIVE")
        journal.update_trade_result(tid, "LOSS", 49_500.0, -50.0)

    for _ in range(3):
        _live_loss()

    ok, reason = eng.can_trade(10_000.0)
    assert ok is True   # bypassed via the restored override
    assert reason == ""
    assert eng.has_consecutive_loss_override() is False   # one-shot, consumed
    assert journal.get_risk_override() is None   # persisted copy cleared too


# ── The MagicMock false-positive this whole fix had to guard against ────

def test_unconfigured_magicmock_journal_does_not_silently_arm_override():
    """Nearly every other RiskEngine test in this suite constructs it
    with a bare, unconfigured MagicMock() journal. MagicMock
    auto-creates any attribute accessed on it, so
    getattr(mock, 'get_risk_override', None) is truthy and calling it
    returns *another* MagicMock (also truthy, not None) -- if RiskEngine
    naively treated that as 'a persisted override exists', it would
    silently bypass the consecutive-loss gate on construction for
    every one of those tests. Requiring the restored value to actually
    be a str is what prevents that."""
    mock_journal = MagicMock()
    eng = RiskEngine(mock_journal)
    assert eng.has_consecutive_loss_override() is False
    assert eng.consecutive_loss_override_reason() is None


def test_magicmock_journal_explicitly_returning_a_string_still_restores():
    """The flip side: if a test *does* want to simulate a persisted
    override via a mock, configuring the return value explicitly still
    works -- only the unconfigured auto-attribute case is guarded
    against."""
    mock_journal = MagicMock()
    mock_journal.get_risk_override.return_value = "explicitly configured"
    eng = RiskEngine(mock_journal)
    assert eng.has_consecutive_loss_override() is True
    assert eng.consecutive_loss_override_reason() == "explicitly configured"


def test_journal_missing_the_method_entirely_degrades_to_unarmed():
    """A minimal stub/spec object that doesn't implement
    get_risk_override at all (unlike MagicMock, which auto-creates it)
    must not raise AttributeError."""
    class MinimalJournalStub:
        def get_consecutive_losses(self, execution_lane=None): return 0
        def get_today_pnl(self, execution_lane=None): return 0.0
        def get_daily_stats(self, execution_lane=None): return {"total_pnl": 0.0}

    eng = RiskEngine(MinimalJournalStub())
    assert eng.has_consecutive_loss_override() is False

    # override_next_trade_despite_streak / clear must also not raise
    # against a journal missing save_risk_override/clear_risk_override.
    eng.override_next_trade_despite_streak("test")
    assert eng.has_consecutive_loss_override() is True
    eng.clear_consecutive_loss_override()
    assert eng.has_consecutive_loss_override() is False
