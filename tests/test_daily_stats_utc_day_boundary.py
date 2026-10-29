"""tests/test_daily_stats_utc_day_boundary.py

V16 §91 regression: get_daily_stats()/get_today_pnl() defaulted `day` to the
host's LOCAL date (date.today()) while trade timestamps are stored in UTC and
SQLite's date(timestamp) is evaluated in UTC. On a UTC+7 host (Asia/Bangkok)
between 00:00 and 07:00 local time the two dates differ, so trades from the
current UTC day were not counted by RiskEngine.check_daily_loss().

The tests simulate that host deterministically with a fake clock (no
dependence on the real wall-clock time or the TZ of the machine running them):
the instant is 2026-10-28 20:00 UTC == 2026-10-29 03:00 in Bangkok.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.unit

_NOW_UTC = datetime(2026, 10, 28, 20, 0, 0, tzinfo=timezone.utc)
_LOCAL_DATE_BANGKOK = date(2026, 10, 29)   # what date.today() returns there


class _FakeDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW_UTC.astimezone(tz) if tz else _NOW_UTC.replace(tzinfo=None)


class _FakeDate(date):
    @classmethod
    def today(cls):
        return _LOCAL_DATE_BANGKOK


def _v2_journal(tmp_path):
    from journal.journal_v2 import TradeJournalV2
    return TradeJournalV2(db_path=str(tmp_path / "v2.db"))


def _v2_trade(journal, ts_iso, pnl):
    from journal.journal_v2 import TradeRecord
    rec = TradeRecord()
    rec.timestamp = ts_iso
    rec.symbol = "BTCUSDT"
    rec.direction = "LONG"
    rec.regime = "TREND"
    rec.entry_price, rec.stop_loss, rec.take_profit = 50_000.0, 49_500.0, 51_000.0
    rec.confidence, rec.score, rec.result, rec.pnl = 77.78, 7, "OPEN", 0.0
    tid = journal.save_trade(rec, execution_lane="LIVE")
    journal.update_trade_result(tid, "LOSS", 49_500.0, pnl)


def test_v2_default_day_is_utc_not_host_local_date(tmp_path):
    journal = _v2_journal(tmp_path)
    # Opened 19:30 UTC on 2026-10-28 == 02:30 local on 2026-10-29 (Bangkok).
    _v2_trade(journal, "2026-10-28T19:30:00+00:00", -100.0)
    with patch("journal.journal_v2.datetime", _FakeDatetime), \
         patch("journal.journal_v2.date", _FakeDate, create=True):
        stats = journal.get_daily_stats(execution_lane="LIVE")
        pnl = journal.get_today_pnl(execution_lane="LIVE")
    assert stats["date"] == "2026-10-28"
    assert stats["total_trades"] == 1
    assert pnl == pytest.approx(-100.0)


def test_v2_explicit_day_argument_is_unchanged(tmp_path):
    journal = _v2_journal(tmp_path)
    _v2_trade(journal, "2026-10-28T19:30:00+00:00", -100.0)
    assert journal.get_daily_stats(day="2026-10-28")["total_trades"] == 1
    assert journal.get_daily_stats(day="2026-10-29")["total_trades"] == 0


def test_v2_daily_loss_gate_sees_loss_in_the_early_morning_window(tmp_path):
    """End to end through RiskEngine: a loss beyond MAX_DAILY_LOSS booked in
    the current UTC day must block trading even when the host's local date
    has already rolled over."""
    from risk.risk_engine import RiskEngine
    journal = _v2_journal(tmp_path)
    _v2_trade(journal, "2026-10-28T19:30:00+00:00", -500.0)   # 5% of 10_000
    engine = RiskEngine(journal, lane="LIVE")
    with patch("journal.journal_v2.datetime", _FakeDatetime), \
         patch("journal.journal_v2.date", _FakeDate, create=True):
        ok, reason = engine.check_daily_loss(10_000.0)
    assert ok is False
    assert "Daily loss limit" in reason


def test_legacy_default_day_is_utc_not_host_local_date(tmp_path):
    from analytics.trade_journal import TradeJournal, TradeRecord
    with patch("analytics.trade_journal.settings") as ms:
        ms.JOURNAL_DB_PATH = str(tmp_path / "legacy.db")
        ms.SYMBOL = "BTCUSDT"
        journal = TradeJournal()
    rec = TradeRecord()
    rec.timestamp = "2026-10-28T19:30:00+00:00"
    rec.symbol = "BTCUSDT"
    rec.direction = "LONG"
    rec.result = "LOSS"
    rec.pnl = -100.0
    rec.rr = -1.0
    tid = journal.save_trade(rec)
    journal.update_trade_result(tid, "LOSS", 49_500.0, -100.0)
    with patch("analytics.trade_journal.datetime", _FakeDatetime), \
         patch("analytics.trade_journal.date", _FakeDate, create=True):
        stats = journal.get_daily_stats()
    assert stats["date"] == "2026-10-28"
    assert stats["total_trades"] == 1
    assert journal.get_daily_stats(day="2026-10-28")["total_trades"] == 1
