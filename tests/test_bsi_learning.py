"""Trade recording, duplicates, incomplete outcomes, classification, reporting. (SYNTHETIC trades.)"""

import pytest
from datetime import timedelta

from tests._bsi_helpers import T0, mk_trade

from brain_strategy_intelligence.config import LearningCfg
from brain_strategy_intelligence.learning.outcome_analyzer import OutcomeAnalyzer
from brain_strategy_intelligence.learning.trade_recorder import TradeRecorder, mfe_mae, net_pnl

pytestmark = pytest.mark.unit


def test_record_then_duplicate_then_conflict():
    r = TradeRecorder()
    assert r.record(mk_trade("a")).status == "recorded"
    assert r.record(mk_trade("a")).status == "duplicate"
    c = r.record(mk_trade("a", realized_pnl=50.0))
    assert c.status == "conflict" and r.count() == 1
    assert r.verified_trades()[0].realized_pnl == 1.0  # stored row NOT overwritten


def test_open_cancelled_and_incomplete_trades_are_rejected():
    r = TradeRecorder()
    assert r.record(mk_trade("o", status="OPEN")).status == "rejected"
    assert r.record(mk_trade("c", status="CANCELLED")).status == "rejected"
    res = r.record(mk_trade("m", exit_price=None, fees=None))
    assert res.status == "rejected" and any("exit_price" in x for x in res.reasons)
    assert r.record(mk_trade("t", exit_time=T0 - timedelta(hours=1))).status == "rejected"
    assert r.count() == 0


def test_only_verified_trades_are_used_for_outcomes():
    r = TradeRecorder()
    r.record(mk_trade("v", verified=True))
    r.record(mk_trade("u", verified=False))
    assert [t.trade_id for t in r.verified_trades()] == ["v"]
    assert r.mark_verified("u") and len(r.verified_trades()) == 2
    assert not r.mark_verified("nope")


def test_net_pnl_and_mfe_mae():
    t = mk_trade(entry_price=100, quantity=2, realized_pnl=10, fees=1, funding=0.5, path_high=110, path_low=95)
    assert net_pnl(t) == 8.5 and mfe_mae(t) == (20.0, 10.0)
    s = mk_trade(direction="SHORT", entry_price=100, quantity=2, path_high=110, path_low=95)
    assert mfe_mae(s) == (10.0, 20.0)
    assert mfe_mae(mk_trade()) == (None, None)  # unknown path -> not fabricated


def test_failure_classification_priority_and_rules():
    a = OutcomeAnalyzer(LearningCfg())
    loss = dict(realized_pnl=-5.0, exit_price=95.0)
    assert a.classify(mk_trade(**loss)).failure_class == "normal_variance"
    assert (
        a.classify(
            mk_trade(**loss, data_quality_flags=["stale_price"], expected_slippage_bps=1, realized_slippage_bps=50)
        ).failure_class
        == "data_quality"
    )
    assert (
        a.classify(mk_trade(**loss, expected_slippage_bps=2, realized_slippage_bps=20)).failure_class
        == "poor_execution"
    )
    assert (
        a.classify(mk_trade(**loss, regime="RANGE"), declared_regimes=["TREND"]).failure_class
        == "incorrect_market_assumption"
    )
    win = a.classify(mk_trade())
    assert win.outcome == "WIN" and win.failure_class is None


def test_degradation_needs_enough_samples_on_both_sides():
    a = OutcomeAnalyzer(LearningCfg(min_samples_degradation=20))
    base = [
        mk_trade(f"b{i}", exit_time=T0 + timedelta(minutes=i), realized_pnl=1.0 if i % 10 else -1.0) for i in range(30)
    ]
    recent = [
        mk_trade(f"r{i}", exit_time=T0 + timedelta(hours=1, minutes=i), realized_pnl=-1.0 if i % 10 else 1.0)
        for i in range(20)
    ]
    loss = mk_trade("last", exit_time=T0 + timedelta(hours=5), realized_pnl=-1.0)
    assert a.classify(loss, prior_trades=base + recent).failure_class == "possible_strategy_degradation"
    assert a.classify(loss, prior_trades=base[:10]).failure_class == "normal_variance"  # too few samples


def test_analysis_has_no_lookahead_and_report_excludes_unverified():
    a = OutcomeAnalyzer(LearningCfg())
    ts = [mk_trade(f"x{i}", exit_time=T0 + timedelta(minutes=i), realized_pnl=-2.0) for i in range(3)]
    ts.append(mk_trade("unver", verified=False, exit_time=T0 + timedelta(minutes=9)))
    out = a.analyze_all(ts)
    assert [o.trade_id for o in out] == ["x0", "x1", "x2"]
    rep = a.performance_report(ts, {"s-one": ["TREND"]})
    assert rep["verified_trades"] == 3 and rep["excluded_unverified_or_open"] == 1
    assert (
        rep["strategies"][0]["low_sample"] is True and rep["strategies"][0]["failure_classes"]["normal_variance"] == 3
    )
