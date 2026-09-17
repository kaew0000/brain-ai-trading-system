"""
tests/test_fee_backfill.py

V16: Fee/Commission Backfill (journal/fee_backfill.py +
journal/journal_v2.py's get_trades_missing_fees()).

Uses a tmp_path-backed temp-file DB per test, same reasoning as
tests/test_execution_attribution.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2
from journal.fee_backfill import backfill_commission_fees, _sum_commission


pytestmark = pytest.mark.unit


def _open_trade(journal: TradeJournalV2, order_id: str = "111", ts: str | None = None) -> int:
    rec = TradeRecord()
    rec.timestamp   = ts or datetime.now(timezone.utc).isoformat()
    rec.symbol      = "BTCUSDT"
    rec.direction   = "LONG"
    rec.entry_price = 67000.0
    rec.stop_loss   = 65800.0
    rec.take_profit = 69400.0
    rec.quantity    = 0.01
    rec.order_id    = order_id
    return journal.save_trade(rec, execution_lane="LIVE")


@pytest.fixture
def journal(tmp_path):
    db = str(tmp_path / "test_journal.db")
    return TradeJournalV2(db_path=db)


class _FakeClient:
    """Stand-in for UMFutures — records calls, returns canned trades."""

    def __init__(self, trades_by_order: dict[int, list[dict]] | None = None, raise_on: set[int] | None = None):
        self.trades_by_order = trades_by_order or {}
        self.raise_on = raise_on or set()
        self.calls: list[tuple[str, int]] = []

    def get_account_trades(self, symbol: str, orderId: int, **kwargs):
        self.calls.append((symbol, orderId))
        if orderId in self.raise_on:
            raise RuntimeError("simulated API error")
        return self.trades_by_order.get(orderId, [])


# ══════════════════════════════════════════════════════════════════════════
# TradeJournalV2.get_trades_missing_fees()
# ══════════════════════════════════════════════════════════════════════════

class TestGetTradesMissingFees:

    def test_returns_trade_with_order_id_and_no_fees(self, journal):
        _open_trade(journal, order_id="111")
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = journal.get_trades_missing_fees(since_iso=since, limit=10)
        assert len(out) == 1
        assert out[0]["order_id"] == "111"
        assert out[0]["fees_exit"] is None

    def test_excludes_trade_with_no_order_id(self, journal):
        _open_trade(journal, order_id="")
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = journal.get_trades_missing_fees(since_iso=since, limit=10)
        assert out == []

    def test_excludes_trade_outside_lookback_window(self, journal):
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        _open_trade(journal, order_id="111", ts=old_ts)
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = journal.get_trades_missing_fees(since_iso=since, limit=10)
        assert out == []

    def test_excludes_trade_that_already_has_fees_entry(self, journal):
        tid = _open_trade(journal, order_id="111")
        journal.save_execution_attribution(tid, fees_entry=0.05)
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = journal.get_trades_missing_fees(since_iso=since, limit=10)
        assert out == []

    def test_respects_limit(self, journal):
        for i in range(5):
            _open_trade(journal, order_id=str(100 + i))
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = journal.get_trades_missing_fees(since_iso=since, limit=2)
        assert len(out) == 2

    def test_surfaces_close_order_id_when_present(self, journal):
        tid = _open_trade(journal, order_id="111")
        journal.save_execution_attribution(tid, order_id="222")  # close-side order id
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        out = journal.get_trades_missing_fees(since_iso=since, limit=10)
        assert out[0]["close_order_id"] == "222"


# ══════════════════════════════════════════════════════════════════════════
# _sum_commission()
# ══════════════════════════════════════════════════════════════════════════

class TestSumCommission:

    def test_sums_single_asset(self):
        trades = [
            {"commission": "0.078", "commissionAsset": "USDT"},
            {"commission": "0.012", "commissionAsset": "USDT"},
        ]
        total, asset = _sum_commission(trades)
        assert total == pytest.approx(0.09)
        assert asset == "USDT"

    def test_mixed_asset_returns_none(self):
        trades = [
            {"commission": "0.078", "commissionAsset": "USDT"},
            {"commission": "0.0001", "commissionAsset": "BNB"},
        ]
        total, asset = _sum_commission(trades)
        assert total is None
        assert asset is None

    def test_empty_list_returns_none(self):
        assert _sum_commission([]) == (None, None)

    def test_malformed_commission_returns_none(self):
        trades = [{"commission": "not-a-number", "commissionAsset": "USDT"}]
        total, asset = _sum_commission(trades)
        assert total is None


# ══════════════════════════════════════════════════════════════════════════
# backfill_commission_fees()
# ══════════════════════════════════════════════════════════════════════════

class TestBackfillCommissionFees:

    def test_noop_when_disabled(self, journal, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", False)
        client = _FakeClient()
        result = backfill_commission_fees(journal, client)
        assert result["candidates"] == 0
        assert client.calls == []

    def test_noop_when_journal_or_client_missing(self, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", True)
        result = backfill_commission_fees(None, _FakeClient())
        assert result["candidates"] == 0

    def test_fills_entry_fee_for_candidate(self, journal, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", True)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_LOOKBACK_HOURS", 24)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_MAX_TRADES_PER_RUN", 50)
        tid = _open_trade(journal, order_id="111")
        client = _FakeClient(trades_by_order={
            111: [{"commission": "0.078", "commissionAsset": "USDT"}],
        })

        result = backfill_commission_fees(journal, client)

        assert result["candidates"] == 1
        assert result["entry_filled"] == 1
        assert client.calls == [("BTCUSDT", 111)]
        attribution = journal.get_trade_attribution(tid)
        assert attribution["fees"] == pytest.approx(0.078)

    def test_fills_entry_and_exit_fee_when_close_order_id_known(self, journal, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", True)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_LOOKBACK_HOURS", 24)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_MAX_TRADES_PER_RUN", 50)
        tid = _open_trade(journal, order_id="111")
        journal.save_execution_attribution(tid, order_id="222")  # close-side order id
        client = _FakeClient(trades_by_order={
            111: [{"commission": "0.078", "commissionAsset": "USDT"}],
            222: [{"commission": "0.081", "commissionAsset": "USDT"}],
        })

        result = backfill_commission_fees(journal, client)

        assert result["entry_filled"] == 1
        assert result["exit_filled"] == 1
        attribution = journal.get_trade_attribution(tid)
        assert attribution["fees"] == pytest.approx(0.159)

    def test_never_fetches_exit_fee_without_close_order_id(self, journal, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", True)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_LOOKBACK_HOURS", 24)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_MAX_TRADES_PER_RUN", 50)
        _open_trade(journal, order_id="111")  # no close order id ever recorded
        client = _FakeClient(trades_by_order={
            111: [{"commission": "0.078", "commissionAsset": "USDT"}],
        })

        backfill_commission_fees(journal, client)

        assert client.calls == [("BTCUSDT", 111)]  # only the entry-side call

    def test_api_error_is_caught_and_counted(self, journal, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", True)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_LOOKBACK_HOURS", 24)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_MAX_TRADES_PER_RUN", 50)
        _open_trade(journal, order_id="111")
        client = _FakeClient(raise_on={111})

        result = backfill_commission_fees(journal, client)

        assert result["candidates"] == 1
        assert result["entry_filled"] == 0
        assert result["errors"] == 0  # a failed fetch is not a save error — just nothing to save

    def test_mixed_asset_order_left_unfilled_not_crashed(self, journal, monkeypatch):
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_ENABLED", True)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_LOOKBACK_HOURS", 24)
        monkeypatch.setattr("journal.fee_backfill.settings.FEE_BACKFILL_MAX_TRADES_PER_RUN", 50)
        _open_trade(journal, order_id="111")
        client = _FakeClient(trades_by_order={
            111: [
                {"commission": "0.078", "commissionAsset": "USDT"},
                {"commission": "0.0001", "commissionAsset": "BNB"},
            ],
        })

        result = backfill_commission_fees(journal, client)

        assert result["entry_filled"] == 0
        assert result["errors"] == 0
