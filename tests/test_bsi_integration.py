"""Adapter behaviour, disabled bundle, execution prevention, config isolation. (SYNTHETIC data.)"""

import re
from datetime import timedelta
from pathlib import Path

import pytest
from tests._bsi_helpers import T0, make_strategy, mk_trade, small_cfg, synthetic_candles

from brain_strategy_intelligence.config import Config, load_config
from brain_strategy_intelligence.errors import ConfigError
from brain_strategy_intelligence.evaluation.evaluator import StrategyEvaluator
from brain_strategy_intelligence.integration.brain_bot_adapter import BrainBotAdapter, snapshot_from_market_context
from brain_strategy_intelligence.knowledge.repository import KnowledgeRepository
from brain_strategy_intelligence.knowledge.sqlite_store import SQLiteStrategyStore
from brain_strategy_intelligence.learning.trade_recorder import TradeRecorder
from brain_strategy_intelligence.ranking.ranker import StrategyRanker
from brain_strategy_intelligence.research.agent import ResearchAgent

pytestmark = pytest.mark.unit

NOW = T0 + timedelta(minutes=1)
CTX = {
    "symbol": "BTCUSDT",
    "timestamp": T0.isoformat(),
    "mark_price": 65000.0,
    "regime": "TREND",
    "regime_conf": 0.7,
    "trend_bias": "LONG_BIAS",
    "trend_strength": "STRONG",
    "futures_signal": "LONG",
    "fear_greed": 40,
    "macro_risk": False,
    "futures": {"funding": {"rate": 0.0001}, "open_interest": {"value": 1234.5}},
}
RISK = {"trading_allowed": True, "max_leverage": 3, "risk_pct": 0.01}


def build(cfg=None, repo=None):
    cfg = cfg or small_cfg()
    repo = repo or KnowledgeRepository(SQLiteStrategyStore(":memory:"))
    return BrainBotAdapter(
        cfg,
        repo,
        ResearchAgent(None, cfg),
        StrategyRanker(cfg.ranking),
        recorder=TradeRecorder(":memory:"),
        clock=lambda: NOW,
    ), repo


def test_market_context_mapping_uses_verified_brain_bot_keys():
    s = snapshot_from_market_context(CTX, RISK)
    assert (s.symbol, s.regime, s.trend_bias, s.funding_rate, s.open_interest, s.fear_greed) == (
        "BTCUSDT",
        "TREND",
        "LONG_BIAS",
        0.0001,
        1234.5,
        40,
    )
    assert s.critical_missing() == []
    assert snapshot_from_market_context({**CTX, "regime": ""}, RISK).regime is None  # nothing guessed


def test_ok_flow_returns_advisory_candidates_ranked_when_evaluated():
    ad, repo = build()
    repo.add_new(make_strategy("t-1"))
    repo.add_new(make_strategy("t-2", description="other trend text"))
    ev = StrategyEvaluator(ad.cfg).evaluate(
        repo.get("t-1"), synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)"
    )
    repo.record_evaluation(ev)
    rec = ad.recommend(snapshot_from_market_context(CTX, RISK))
    assert rec.status == "OK" and rec.advisory_only is True and rec.may_execute is False
    by = {c.strategy_id: c for c in rec.candidates}
    assert by["t-1"].rank == 1 and by["t-1"].evaluation_status == "COMPLETE"
    assert by["t-2"].rank is None and by["t-2"].evaluation_status == "NOT_EVALUATED" and by["t-2"].recommend_backtest
    assert rec.candidates[0].strategy_id == "t-1" and rec.research_mode == "offline_rules"


def test_disabled_bundle_does_nothing_and_never_touches_storage():
    class Boom:
        def __getattr__(self, name):
            raise AssertionError(f"storage touched: {name}")

    cfg = load_config(env={"BSI_ENABLED": "false"})
    ad = BrainBotAdapter(
        cfg, KnowledgeRepository(Boom(), embedder=None), ResearchAgent(None, cfg), StrategyRanker(cfg.ranking)
    )
    assert ad.recommend(CTX).status == "DISABLED"
    assert ad.record_closed_trade(mk_trade()).status == "rejected"


def test_fail_closed_cases():
    ad, repo = build()
    repo.add_new(make_strategy("t-1"))
    assert ad.recommend({**CTX, "mark_price": -1}).status == "REJECTED_INVALID_SNAPSHOT"
    assert ad.recommend({"garbage": 1}).status == "REJECTED_INVALID_SNAPSHOT"
    no_risk = snapshot_from_market_context(CTX, None)
    r = ad.recommend(no_risk)
    assert r.status == "REJECTED_MISSING_DATA" and r.candidates == [] and "risk" in r.missing_data
    no_regime = snapshot_from_market_context({**CTX, "regime": None}, RISK)
    assert ad.recommend(no_regime).status == "REJECTED_MISSING_DATA"
    blocked = snapshot_from_market_context(CTX, {**RISK, "trading_allowed": False})
    assert ad.recommend(blocked).status == "REJECTED_RISK_BLOCKED"
    stale = snapshot_from_market_context({**CTX, "timestamp": (T0 - timedelta(hours=2)).isoformat()}, RISK)
    assert ad.recommend(stale).status == "REJECTED_STALE_SNAPSHOT"


def test_internal_error_becomes_error_status_not_exception():
    ad, repo = build()
    ad.retriever = None  # type: ignore[assignment]  # force an internal failure
    r = ad.recommend(snapshot_from_market_context(CTX, RISK))
    assert r.status == "ERROR" and r.may_execute is False


def test_record_closed_trade_validates_and_dedupes():
    ad, _ = build()
    assert ad.record_closed_trade(mk_trade("z")).status == "recorded"
    assert ad.record_closed_trade(mk_trade("z")).status == "duplicate"
    assert ad.record_closed_trade({"trade_id": "bad"}).status == "rejected"
    assert ad.record_closed_trade(mk_trade("o", status="OPEN")).status == "rejected"


def test_adapter_exposes_no_execution_surface():
    names = {n for n in dir(BrainBotAdapter) if not n.startswith("_")}
    assert names <= {"from_config", "recommend", "record_closed_trade", "recorder"}
    assert not any(re.search(r"(^|_)(order|execute|place|submit|cancel|leverage)", n) for n in names)


def test_default_yaml_matches_code_defaults_and_is_research_only():
    yaml = pytest.importorskip("yaml")
    path = Path(__file__).resolve().parent.parent / "config" / "strategy_intelligence.yaml"
    assert Config.model_validate(yaml.safe_load(path.read_text())) == Config()
    assert Config().bundle.mode == "research_only"


@pytest.mark.parametrize("mode", ["live", "paper", "execution", ""])
def test_non_research_modes_are_rejected(mode):
    with pytest.raises(ConfigError):
        load_config(env={}, overrides={"bundle": {"mode": mode}})


def test_config_isolation(tmp_path, monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", "should-never-be-read")
    monkeypatch.setenv("EXECUTION_MODE", "live")  # a Brain Bot variable: must have no effect here
    before = load_config()
    assert before.bundle.mode == "research_only" and before.fingerprint() == Config().fingerprint()
    p = tmp_path / "c.yaml"
    p.write_text("evaluation:\n  fee_bps: 9\n")
    a, b = load_config(p), load_config()
    assert a.evaluation.fee_bps == 9 and b.evaluation.fee_bps == Config().evaluation.fee_bps  # no shared state
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("unknown_section: 1\n")
    with pytest.raises(ConfigError):
        load_config(bad)
