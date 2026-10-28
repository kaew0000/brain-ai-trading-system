"""V16 §89: RiskEngine's gate lane follows EXECUTION_MODE (paper -> TRAINING lane).

Production symptom (2026-10-28 paper boot, balance 4614.02 USDT): "Consecutive losses: 3/3"
from LIVE-lane rows written by earlier real-money sessions. Paper mode never writes LIVE
rows, so that streak could never clear and paper mode was blocked forever."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from journal.journal_v2 import TradeJournalV2, TradeRecord
from risk.risk_engine import RiskEngine

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "lane_follows_mode.db"))


def _loss(journal, lane):
    rec = TradeRecord()
    rec.timestamp = datetime.now(timezone.utc).isoformat()
    rec.symbol, rec.direction = "BTCUSDT", "SHORT"
    rec.entry_price, rec.stop_loss, rec.take_profit = 80_000.0, 81_000.0, 78_000.0
    rec.result = "OPEN"
    tid = journal.save_trade(rec, execution_lane=lane)
    journal.update_trade_result(tid, "LOSS", 81_000.0, -1.0)


def test_paper_engine_ignores_stale_live_losses(journal):
    for _ in range(3):
        _loss(journal, "LIVE")
    ok, reason = RiskEngine(journal, lane="TRAINING").can_trade(4614.02)
    assert ok is True, reason


def test_paper_engine_still_gates_on_its_own_losses(journal):
    for _ in range(3):
        _loss(journal, "TRAINING")
    ok, reason = RiskEngine(journal, lane="TRAINING").can_trade(4614.02)
    assert ok is False and "Consecutive losses" in reason


def test_default_engine_is_still_live_only(journal):
    for _ in range(3):
        _loss(journal, "LIVE")
    assert RiskEngine(journal).can_trade(500.0)[0] is False
    for _ in range(5):
        _loss(journal, "TRAINING")
    j2 = TradeJournalV2(db_path=journal.db_path) if hasattr(journal, "db_path") else journal
    assert RiskEngine(j2).can_trade(500.0)[0] is False   # unchanged: still the LIVE streak


def test_live_engine_unaffected_by_training_losses(journal):
    for _ in range(5):
        _loss(journal, "TRAINING")
    assert RiskEngine(journal, lane="LIVE").can_trade(500.0)[0] is True


def test_report_uses_engine_lane(journal):
    for _ in range(3):
        _loss(journal, "LIVE")
    assert RiskEngine(journal, lane="TRAINING").report(4614.02)["consecutive_losses"] == 0
    assert RiskEngine(journal).report(4614.02)["consecutive_losses"] == 3


def test_epoch_state_is_per_lane(journal):
    live = RiskEngine(journal, lane="LIVE")
    paper = RiskEngine(journal, lane="TRAINING")
    live.can_trade(0.0)    # marks LIVE unfunded
    assert journal.get_risk_state("live_unfunded_since") is not None
    assert journal.get_risk_state("training_unfunded_since") is None
    assert paper._unfunded_since is None


def test_invalid_lane_rejected(journal):
    with pytest.raises(ValueError):
        RiskEngine(journal, lane="BOGUS")
