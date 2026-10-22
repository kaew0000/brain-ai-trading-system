"""Ranking: transparency, stability, insufficient samples, never profit-only. (Metrics are SYNTHETIC test values.)"""

import pytest
from tests._bsi_helpers import make_strategy, mk_metrics
from pydantic import ValidationError

from brain_strategy_intelligence.config import RankingCfg
from brain_strategy_intelligence.ranking.ranker import StrategyRanker
from brain_strategy_intelligence.schemas import (
    EvaluationResult,
    SensitivityResult,
    WalkForwardSummary,
    WalkForwardWindow,
)

pytestmark = pytest.mark.unit


def wf(frac, n=6):
    w = [
        WalkForwardWindow(
            train_range=(0, 1), test_range=(2, 3), chosen_params={}, train_net_pnl=1, test_net_pnl=1, test_trades=5
        )
    ] * n
    return WalkForwardSummary(windows=w, profitable_fraction=frac, total_test_net_pnl=10, total_test_trades=30)


def sens(frac):
    return SensitivityResult(
        base_net_pnl=1.0,
        neighbours=[{"param": "a", "value": 1, "net_pnl": 1.0}],
        positive_neighbour_fraction=frac,
        max_relative_change=0.5,
    )


def ev(sid, oos=None, ins=None, wf_=None, sens_=None, status="COMPLETE", label="SYNTHETIC(t)"):
    return EvaluationResult(
        evaluation_id=sid + "-ev",
        strategy_id=sid,
        strategy_version=1,
        symbol="SYNUSDT",
        timeframe="15m",
        data_label=label,
        status=status,
        incomplete_reasons=[] if status == "COMPLETE" else ["x"],
        in_sample=ins or mk_metrics(),
        out_of_sample=oos or mk_metrics(),
        walk_forward=wf_ or wf(0.8),
        sensitivity=sens_ or sens(0.8),
    )


def test_incomplete_evaluations_are_unranked_with_reason():
    r = StrategyRanker(RankingCfg()).rank([(make_strategy("a-a"), ev("a-a", status="INCOMPLETE"))])
    e = r.entries[0]
    assert e.status == "UNRANKED" and e.rank is None and e.score is None and "incomplete" in e.reasons[0]


def test_profit_alone_cannot_win():
    flashy = ev(
        "flashy",
        oos=mk_metrics(
            net_pnl=5000, return_pct=50, max_drawdown_pct=45, trade_count=4, profit_factor=9.0, return_over_drawdown=1.1
        ),
        wf_=wf(0.34),
        sens_=sens(0.2),
    )
    steady = ev(
        "steady",
        oos=mk_metrics(
            net_pnl=300, return_pct=3, max_drawdown_pct=3, trade_count=120, profit_factor=1.6, return_over_drawdown=1.0
        ),
        wf_=wf(0.9),
        sens_=sens(0.9),
    )
    r = StrategyRanker(RankingCfg()).rank([(make_strategy("flashy"), flashy), (make_strategy("steady"), steady)])
    assert [e.strategy_id for e in r.entries] == ["steady", "flashy"]
    flash = r.entries[1]
    assert any("only 4 OOS trades" in x for x in flash.limitations)


def test_few_trades_lowers_reliability_and_score():
    many = ev("many", oos=mk_metrics(trade_count=200))
    few = ev("few", oos=mk_metrics(trade_count=5))
    r = {
        e.strategy_id: e
        for e in StrategyRanker(RankingCfg()).rank([(make_strategy("many"), many), (make_strategy("few"), few)]).entries
    }
    assert r["few"].breakdown["reliability"] < r["many"].breakdown["reliability"] and r["few"].score < r["many"].score


def test_negative_oos_is_penalised():
    pos = ev("pos")
    neg = ev("neg", oos=mk_metrics(net_pnl=-100, return_pct=-1, return_over_drawdown=-0.2, profit_factor=0.8))
    r = {
        e.strategy_id: e
        for e in StrategyRanker(RankingCfg()).rank([(make_strategy("pos"), pos), (make_strategy("neg"), neg)]).entries
    }
    assert r["neg"].score < r["pos"].score and any("negative OOS" in x for x in r["neg"].reasons)


def test_degradation_is_detected():
    degraded = ev("degr", ins=mk_metrics(return_pct=30.0, bars=1000), oos=mk_metrics(return_pct=1.0, bars=1000))
    r = StrategyRanker(RankingCfg()).rank([(make_strategy("degr"), degraded)]).entries[0]
    assert r.breakdown["degradation"] < 0.1 and any("overfitting" in x for x in r.reasons)


def test_ranking_is_deterministic_stable_and_ties_break_by_id():
    items = [(make_strategy(f"s-{i}"), ev(f"s-{i}")) for i in "cab"]  # identical metrics -> tie
    r1 = StrategyRanker(RankingCfg()).rank(items)
    r2 = StrategyRanker(RankingCfg()).rank(list(reversed(items)))
    assert [e.strategy_id for e in r1.entries] == ["s-a", "s-b", "s-c"] == [e.strategy_id for e in r2.entries]
    assert [e.rank for e in r1.entries] == [1, 2, 3]


def test_ranking_never_changes_validation_status_and_notes_it():
    s = make_strategy("st")
    e = StrategyRanker(RankingCfg()).rank([(s, ev("st"))]).entries[0]
    assert e.validation_status.value == "unvalidated" and any("not validated" in x for x in e.limitations)
    assert any("SYNTHETIC" in x for x in e.limitations)


def test_weights_must_sum_to_one_and_be_non_negative():
    with pytest.raises(ValidationError):
        RankingCfg(weights={"a": 0.5, "b": 0.2})
    with pytest.raises(ValidationError):
        RankingCfg(weights={"a": 1.5, "b": -0.5})
    assert abs(sum(RankingCfg().weights.values()) - 1.0) < 1e-9
