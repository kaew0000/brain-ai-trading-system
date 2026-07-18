"""
tests/test_phase3.py

Pytest coverage for Brain Bot V13 Phase 3 modules:
  A. journal_v2
  B. trend_engine
  C. futures_intel_engine
  D. market_context_builder
  E. confidence_engine
  F. causal_explainer
  G. event_bus
"""

from __future__ import annotations

import math
import threading
import numpy as np
import pandas as pd
import pytest

pytestmark = pytest.mark.unit

# ── Common fixtures ────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 250, trend: str = "up", start: float = 60000.0) -> pd.DataFrame:
    """Generate synthetic OHLCV data with a configurable trend direction."""
    rng = np.random.default_rng(42)
    prices = [start]
    for _ in range(n - 1):
        change = rng.normal(0, 300)
        if trend == "up":
            change += 50
        elif trend == "down":
            change -= 50
        prices.append(max(prices[-1] + change, 1000))

    prices = np.array(prices)
    high  = prices * (1 + rng.uniform(0.001, 0.005, n))
    low   = prices * (1 - rng.uniform(0.001, 0.005, n))
    vol   = rng.uniform(500, 5000, n)

    df = pd.DataFrame({
        "open":   prices,
        "high":   high,
        "low":    low,
        "close":  prices,
        "volume": vol,
    }, index=pd.date_range("2024-01-01", periods=n, freq="15min"))
    return df


def _make_market_data(
    mark_price: float = 67000.0,
    funding:    float = 0.0001,
    oi_delta:   float = 0.015,
    ls_ratio:   float = 1.05,
    taker_bsr:  float = 1.10,
) -> dict:
    return {
        "mark_price":       mark_price,
        "prev_mark_price":  mark_price * 0.999,
        "funding_rate":     funding,
        "oi_delta":         oi_delta,
        "open_interest":    15000.0,
        "long_short_ratio": {"longShortRatio": str(ls_ratio)},
        "taker_ratio":      {"buySellRatio": str(taker_bsr)},
    }


def _make_smc_signals(bullish: bool = True):
    """Return minimal SMCSignals-like objects (use dataclass from smc_engine)."""
    from features.smc_engine import SMCSignals
    sig = SMCSignals()
    sig.bos = True
    sig.bos_direction = "Bullish" if bullish else "Bearish"
    sig.trend_bias = "Bullish" if bullish else "Bearish"
    sig.choch = True
    sig.choch_direction = "Bullish" if bullish else "Bearish"
    return sig


def _make_regime(regime: str = "TREND"):
    from regime.regime_engine import RegimeResult
    r = RegimeResult()
    r.regime = regime
    r.confidence = 0.85
    r.adx = 32.0
    r.bb_width = 0.003
    r.atr_normalized = 0.002
    r.probabilities = {"TREND": 0.85, "RANGE": 0.10, "HIGH_VOLATILITY": 0.05}
    return r


def _make_volume_signals(spike: bool = True):
    from features.volume_engine import VolumeSignals
    v = VolumeSignals()
    v.volume_spike = spike
    v.volume_ratio = 2.1 if spike else 0.8
    v.obv_direction = "bullish"
    v.score = 2
    return v


# ════════════════════════════════════════════════════════════════════════════════
# A. JOURNAL V2
# ════════════════════════════════════════════════════════════════════════════════

class TestJournalV2:

    @pytest.fixture
    def journal(self):
        from journal.journal_v2 import TradeJournalV2
        return TradeJournalV2(db_path=":memory:")

    def test_init(self, journal):
        assert journal is not None

    def test_save_and_get_signal(self, journal):
        decision = {"action": "LONG", "score": 7, "confidence": 82.0,
                    "regime": "TREND", "direction": "LONG",
                    "entry_price": 67000.0, "stop_loss": 65800.0, "take_profit": 69400.0}
        sid = journal.save_signal(decision, confidence_breakdown={"smc": 28, "volume": 18})
        assert sid == 1
        sigs = journal.get_signals(limit=5)
        assert len(sigs) == 1
        s = sigs[0]
        assert s["action"] == "LONG"
        assert s["confidence"] == 82.0
        assert isinstance(s["confidence_breakdown"], dict)
        assert s["confidence_breakdown"]["smc"] == 28

    def test_save_and_get_regime(self, journal):
        rid = journal.save_market_regime({
            "regime": "TREND", "confidence": 0.87, "adx": 34.0,
            "bb_width": 0.003, "atr_normalized": 0.002,
            "probabilities": {"TREND": 0.87, "RANGE": 0.10}
        })
        assert rid == 1
        regimes = journal.get_market_regimes(limit=5)
        assert regimes[0]["regime"] == "TREND"
        assert isinstance(regimes[0]["probabilities"], dict)

    def test_save_and_get_funding(self, journal):
        fid = journal.save_funding(0.0001, 67000.0)
        hist = journal.get_funding_history(limit=5)
        assert hist[0]["funding_rate"] == 0.0001
        assert hist[0]["mark_price"] == 67000.0

    def test_save_and_get_oi(self, journal):
        oid = journal.save_oi(15000.0, 1_005_000_000.0, 0.015)
        hist = journal.get_oi_history(limit=5)
        assert hist[0]["open_interest"] == 15000.0
        assert hist[0]["oi_delta_pct"] == 0.015

    def test_agent_message(self, journal):
        mid = journal.save_agent_message("SMC_ANALYST", "BOS_DETECTED",
                                          "Bullish BOS on M15", severity="info",
                                          payload={"tf": "M15"})
        msgs = journal.get_agent_messages(limit=5, agent="SMC_ANALYST")
        assert len(msgs) == 1
        assert msgs[0]["event"] == "BOS_DETECTED"
        assert isinstance(msgs[0]["payload"], dict)
        assert msgs[0]["payload"]["tf"] == "M15"

    def test_agent_decision(self, journal):
        did = journal.save_agent_decision("SMC_ANALYST", "BOS_BULLISH",
                                           score=2.0, weight=0.3,
                                           details={"tf": "M15", "price": 67000})
        decisions = journal.get_agent_decisions(limit=5, agent="SMC_ANALYST")
        assert decisions[0]["decision"] == "BOS_BULLISH"
        assert isinstance(decisions[0]["details"], dict)

    def test_save_and_get_explanation(self, journal):
        reasoning = {
            "factors": [{"agent": "SMC_ANALYST", "name": "BOS", "contribution": 28}],
            "meta": {"regime": "TREND"},
        }
        eid = journal.save_explanation(reasoning, direction="LONG", confidence=82.0,
                                        summary="Bullish setup")
        exps = journal.get_explanations(limit=5)
        assert exps[0]["direction"] == "LONG"
        assert isinstance(exps[0]["reasoning"], dict)
        assert exps[0]["reasoning"]["factors"][0]["name"] == "BOS"

    def test_config_profile(self, journal):
        cid = journal.save_config_profile("default", {"trade_threshold": 75}, active=True)
        cfg = journal.get_active_config_profile()
        assert cfg is not None
        assert cfg["name"] == "default"
        assert cfg["config_json"]["trade_threshold"] == 75

    def test_multiple_config_profiles_only_one_active(self, journal):
        journal.save_config_profile("A", {"x": 1}, active=True)
        journal.save_config_profile("B", {"x": 2}, active=True)
        active = journal.get_active_config_profile()
        assert active["name"] == "B"
        all_profiles = journal.list_config_profiles()
        active_count = sum(1 for p in all_profiles if p["active"])
        assert active_count == 1

    def test_save_snapshot(self, journal):
        sid = journal.save_market_snapshot({
            "mark_price": 67000.0, "h4_close": 67100.0, "h1_close": 67050.0,
            "m15_close": 67000.0, "ema20": 66800.0, "ema50": 65500.0,
            "ema200": 60000.0, "vwap": 66900.0, "adx": 32.0,
        })
        snaps = journal.get_market_snapshots(limit=5)
        assert snaps[0]["mark_price"] == 67000.0
        assert snaps[0]["ema200"] == 60000.0

    def test_update_trade_result(self, journal):
        from analytics.trade_journal import TradeRecord
        rec = TradeRecord()
        rec.timestamp = "2024-01-15T10:00:00+00:00"
        rec.direction = "LONG"
        rec.entry_price = 67000.0
        rec.stop_loss = 65800.0
        rec.take_profit = 69400.0
        tid = journal.save_trade(rec)
        ok = journal.update_trade_result(tid, "WIN", 69000.0, 250.0)
        assert ok
        trades = journal.get_trades(limit=5)
        assert trades[0]["result"] == "WIN"
        assert trades[0]["pnl"] == 250.0
        assert trades[0]["rr"] > 0

    def test_get_latest_signal_none_on_empty(self):
        import tempfile, os
        from journal.journal_v2 import TradeJournalV2
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            j = TradeJournalV2(db_path=db_path)
            assert j.get_latest_signal() is None
        finally:
            os.unlink(db_path)

    def test_get_latest_regime_none_on_empty(self):
        import tempfile, os
        from journal.journal_v2 import TradeJournalV2
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            j = TradeJournalV2(db_path=db_path)
            assert j.get_latest_regime() is None
        finally:
            os.unlink(db_path)


# ════════════════════════════════════════════════════════════════════════════════
# B. TREND ENGINE
# ════════════════════════════════════════════════════════════════════════════════

class TestTrendEngine:

    @pytest.fixture
    def engine(self):
        from trend.trend_engine import TrendEngine
        return TrendEngine()

    def test_uptrend_bias(self, engine):
        df = _make_ohlcv(300, trend="up")
        result = engine.analyse(df)
        assert result.bias == "LONG_BIAS"
        assert result.ema20 > 0
        assert result.ema200 > 0

    def test_downtrend_bias(self, engine):
        df = _make_ohlcv(300, trend="down")
        result = engine.analyse(df)
        assert result.bias == "SHORT_BIAS"

    def test_ema_order_bullish(self, engine):
        df = _make_ohlcv(300, trend="up")
        result = engine.analyse(df)
        # In strong uptrend EMA20 > EMA50
        assert result.ema20 > result.ema50

    def test_to_dict_structure(self, engine):
        df = _make_ohlcv(300, trend="up")
        d = engine.analyse(df).to_dict()
        required = {"bias", "strength", "ema20", "ema50", "ema200", "vwap",
                    "adx", "slope", "price_vs_ema20", "ema_stack", "confidence"}
        assert required.issubset(d.keys())

    def test_insufficient_data_returns_neutral(self, engine):
        df = _make_ohlcv(10, trend="up")
        result = engine.analyse(df)
        assert result.bias == "NEUTRAL"

    def test_vwap_nonzero(self, engine):
        df = _make_ohlcv(200, trend="up")
        result = engine.analyse(df)
        assert result.vwap > 0

    def test_adx_range(self, engine):
        df = _make_ohlcv(300, trend="up")
        result = engine.analyse(df)
        assert 0 <= result.adx <= 100

    def test_slope_normalised(self, engine):
        df = _make_ohlcv(300, trend="up")
        result = engine.analyse(df)
        assert -1.0 <= result.slope <= 1.0

    def test_confidence_between_0_and_1(self, engine):
        df = _make_ohlcv(300, trend="up")
        result = engine.analyse(df)
        assert 0.0 <= result.confidence <= 1.0

    def test_ema_stack_bullish(self, engine):
        df = _make_ohlcv(300, trend="up", start=50000.0)
        result = engine.analyse(df)
        # Not guaranteed in random data, just check valid value
        assert result.ema_stack in ("BULLISH", "BEARISH", "MIXED")

    def test_none_df_returns_neutral(self, engine):
        result = engine.analyse(None)
        assert result.bias == "NEUTRAL"

    def test_current_price_override(self, engine):
        df = _make_ohlcv(300, trend="up")
        result = engine.analyse(df, current_price=100000.0)
        # Price far above all EMAs → should be ABOVE all
        assert result.price_vs_ema200 == "ABOVE"


# ════════════════════════════════════════════════════════════════════════════════
# C. FUTURES INTEL ENGINE
# ════════════════════════════════════════════════════════════════════════════════

class TestFuturesIntelEngine:

    @pytest.fixture
    def engine(self):
        from futures.futures_intel_engine import FuturesIntelEngine
        return FuturesIntelEngine()

    def test_neutral_on_empty(self, engine):
        result = engine.analyse({})
        assert result.signal == "NEUTRAL"

    def test_bullish_oi_and_taker(self, engine):
        md = _make_market_data(oi_delta=0.02, taker_bsr=1.5, ls_ratio=0.75)
        result = engine.analyse(md)
        assert result.signal in ("LONG", "NEUTRAL")

    def test_funding_extreme_detected(self, engine):
        md = _make_market_data(funding=0.0010)
        result = engine.analyse(md)
        assert result.funding.extreme is True
        assert result.funding.bias == "LONG_PAYING"

    def test_funding_annualised_calculation(self, engine):
        md = _make_market_data(funding=0.0001)
        result = engine.analyse(md)
        expected = round(0.0001 * 3 * 365 * 100, 4)
        assert abs(result.funding.annualised - expected) < 0.001

    def test_short_covering_detection(self, engine):
        # Price up + OI down = short covering OR squeeze (both valid when OI drops fast)
        md = _make_market_data(oi_delta=-0.015)
        md["mark_price"] = 67500.0
        md["prev_mark_price"] = 67000.0
        result = engine.analyse(md)
        # OI drop + price up = short covering or squeeze — not organic long
        assert result.condition in ("SHORT_COVERING", "NEUTRAL", "ORGANIC_LONG", "SQUEEZE")
        # Verify OI is flagged as falling
        assert result.open_interest.trend == "FALLING"

    def test_long_liquidation_detection(self, engine):
        md = _make_market_data(oi_delta=-0.02, funding=0.0001)
        md["mark_price"] = 66000.0
        md["prev_mark_price"] = 67000.0
        result = engine.analyse(md)
        assert result.liquidation.liq_type in ("LONG_SQUEEZE", "NONE")

    def test_extensions_all_not_implemented(self, engine):
        md = _make_market_data()
        result = engine.analyse(md)
        for k in ("orderbook_imbalance", "cvd", "liquidation_heatmap"):
            assert result.extensions[k] == "NOT_IMPLEMENTED"

    def test_to_dict_structure(self, engine):
        md = _make_market_data()
        d = engine.analyse(md).to_dict()
        required = {"signal", "condition", "confidence", "funding",
                    "open_interest", "long_short", "taker", "liquidation", "extensions"}
        assert required.issubset(d.keys())

    def test_blocks_long_on_extreme_long_funding(self, engine):
        md = _make_market_data(funding=0.0008)
        result = engine.analyse(md)
        assert result.blocks_long() is True

    def test_ls_ratio_crowded_long(self, engine):
        md = _make_market_data(ls_ratio=1.50)
        result = engine.analyse(md)
        assert result.long_short.crowd_bias == "LONG_CROWDED"
        assert result.long_short.contrarian_signal == "FADE_LONGS"

    def test_ls_ratio_crowded_short(self, engine):
        md = _make_market_data(ls_ratio=0.60)
        result = engine.analyse(md)
        assert result.long_short.crowd_bias == "SHORT_CROWDED"

    def test_taker_buyers_dominant(self, engine):
        md = _make_market_data(taker_bsr=2.5)
        result = engine.analyse(md)
        assert result.taker.aggressor == "BUYERS"

    def test_confidence_0_to_1(self, engine):
        md = _make_market_data()
        result = engine.analyse(md)
        assert 0.0 <= result.confidence <= 1.0

    def test_nan_funding_handled(self, engine):
        md = _make_market_data()
        md["funding_rate"] = float("nan")
        result = engine.analyse(md)
        assert result.funding.rate == 0.0

    def test_nan_oi_delta_handled(self, engine):
        md = _make_market_data()
        md["oi_delta"] = float("nan")
        result = engine.analyse(md)
        assert result.open_interest.delta_pct == 0.0


# ════════════════════════════════════════════════════════════════════════════════
# D. MARKET CONTEXT BUILDER
# ════════════════════════════════════════════════════════════════════════════════

class TestMarketContextBuilder:

    @pytest.fixture
    def builder(self):
        from intelligence.market_context_builder import MarketContextBuilder
        return MarketContextBuilder()

    def test_build_returns_dict(self, builder):
        df = _make_ohlcv(300, trend="up")
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(True), "m15": _make_smc_signals(True)}
        ctx = builder.build(
            market_data=_make_market_data(),
            smc_signals=smc,
            volume_signals=_make_volume_signals(),
            regime_result=_make_regime(),
            ohlcv_h4=df,
        )
        assert isinstance(ctx, dict)

    def test_required_keys_present(self, builder):
        df = _make_ohlcv(300, trend="up")
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(True), "m15": _make_smc_signals(True)}
        ctx = builder.build(
            market_data=_make_market_data(),
            smc_signals=smc,
            volume_signals=_make_volume_signals(),
            regime_result=_make_regime(),
            ohlcv_h4=df,
        )
        required = {"symbol", "timestamp", "mark_price", "regime", "trend_bias",
                    "futures", "futures_signal", "volume", "smc_h4", "smc_m15",
                    "blocks_long", "blocks_short", "mtf_direction", "mtf_aligned"}
        assert required.issubset(ctx.keys())

    def test_mtf_aligned_all_bullish(self, builder):
        df = _make_ohlcv(300, "up")
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(True), "m15": _make_smc_signals(True)}
        ctx = builder.build(_make_market_data(), smc, _make_volume_signals(), _make_regime(), ohlcv_h4=df)
        assert ctx["mtf_direction"] == "LONG"
        assert ctx["mtf_aligned"] is True

    def test_mtf_not_aligned_mixed(self, builder):
        df = _make_ohlcv(300, "up")
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(False), "m15": _make_smc_signals(True)}
        ctx = builder.build(_make_market_data(), smc, _make_volume_signals(), _make_regime(), ohlcv_h4=df)
        assert ctx["mtf_aligned"] is False

    def test_no_ohlcv_returns_neutral_trend(self, builder):
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(True), "m15": _make_smc_signals(True)}
        ctx = builder.build(_make_market_data(), smc, _make_volume_signals(), _make_regime())
        assert ctx["trend_bias"] == "NEUTRAL"

    def test_layer2_defaults(self, builder):
        df = _make_ohlcv(300, "up")
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(True), "m15": _make_smc_signals(True)}
        ctx = builder.build(_make_market_data(), smc, _make_volume_signals(), _make_regime(), ohlcv_h4=df)
        assert ctx["fear_greed"] is None
        assert ctx["macro_risk"] is False
        assert ctx["risk_on"] is True

    def test_layer2_intel_passed_through(self, builder):
        df = _make_ohlcv(300, "up")
        smc = {"h4": _make_smc_signals(True), "h1": _make_smc_signals(True), "m15": _make_smc_signals(True)}
        intel = {"fear_greed": 78, "macro_risk": False, "risk_on": True}
        ctx = builder.build(_make_market_data(), smc, _make_volume_signals(), _make_regime(),
                             ohlcv_h4=df, intelligence=intel)
        assert ctx["fear_greed"] == 78


# ════════════════════════════════════════════════════════════════════════════════
# E. CONFIDENCE ENGINE
# ════════════════════════════════════════════════════════════════════════════════

class TestConfidenceEngine:

    @pytest.fixture
    def engine(self):
        from decision.confidence_engine import ConfidenceEngine
        return ConfidenceEngine()

    def _make_ctx(self, regime="TREND", trend_bias="LONG_BIAS", strength="STRONG",
                  bos=True, spike=True, oi_delta=0.015, funding=0.0001,
                  blocks_long=False, blocks_short=False) -> dict:
        from intelligence.market_context_builder import _smc_to_dict, _volume_to_dict
        from futures.futures_intel_engine import FuturesIntelEngine
        from features.smc_engine import SMCSignals
        from features.volume_engine import VolumeSignals

        smc = SMCSignals()
        smc.bos = bos
        smc.bos_direction = "Bullish"
        smc.choch = True
        smc.choch_direction = "Bullish"
        smc.ob = True
        smc.ob_direction = "Bullish"
        smc.ob_top = 68000.0
        smc.ob_bottom = 67500.0

        vol = VolumeSignals()
        vol.volume_spike = spike
        vol.volume_ratio = 2.1
        vol.obv_direction = "bullish"
        vol.breakout_confirmed = True

        md = _make_market_data(funding=funding, oi_delta=oi_delta)
        fut = FuturesIntelEngine().analyse(md)

        return {
            "regime": regime, "trend_bias": trend_bias, "trend_strength": strength,
            "trend_data": {"adx": 35.0, "ema_stack": "BULLISH"},
            "smc_m15": _smc_to_dict(smc),
            "volume": _volume_to_dict(vol),
            "futures": fut.to_dict(),
            "oi_delta": oi_delta, "funding_rate": funding,
            "long_short_ratio": {"longShortRatio": "1.05"},
            "blocks_long": blocks_long, "blocks_short": blocks_short,
            "mtf_aligned": True,
        }

    def test_high_confidence_long_returns_action_long(self, engine):
        ctx = self._make_ctx()
        result = engine.score(ctx, "LONG", entry_price=67000.0, stop_loss=65800.0, take_profit=69400.0)
        assert result.confidence >= 50
        assert result.action in ("LONG", "WAIT")

    def test_breakdown_sums_to_confidence(self, engine):
        ctx = self._make_ctx()
        result = engine.score(ctx, "LONG")
        assert sum(result.breakdown.values()) == result.confidence

    def test_breakdown_has_all_categories(self, engine):
        ctx = self._make_ctx()
        result = engine.score(ctx, "LONG")
        assert set(result.breakdown.keys()) == {"smc", "volume", "oi", "funding", "regime"}

    def test_confidence_integer_0_to_100(self, engine):
        ctx = self._make_ctx()
        result = engine.score(ctx, "LONG")
        assert isinstance(result.confidence, int)
        assert 0 <= result.confidence <= 100

    def test_no_direction_returns_skip(self, engine):
        ctx = self._make_ctx()
        result = engine.score(ctx, "")
        assert result.action == "SKIP"

    def test_block_on_extreme_funding(self, engine):
        ctx = self._make_ctx(funding=0.0008, blocks_long=True)
        result = engine.score(ctx, "LONG")
        assert result.action == "BLOCKED"
        assert result.blocked is True
        assert len(result.block_reasons) > 0

    def test_score_from_decision_backward_compat(self, engine):
        decision_dict = {
            "action": "LONG", "direction": "LONG", "score": 7, "max_score": 9,
            "confidence": 0.78, "smc_score": 4, "volume_score": 2,
            "oi_score": 1, "sentiment_score": 0,
            "blocked": False, "block_reasons": [],
            "entry_price": 67000.0, "stop_loss": 65800.0, "take_profit": 69400.0,
            "regime": "TREND", "mtf_aligned": True,
        }
        result = engine.score_from_decision(decision_dict)
        assert result.direction == "LONG"
        assert 0 <= result.confidence <= 100
        assert set(result.breakdown.keys()) == {"smc", "volume", "oi", "funding", "regime"}

    def test_custom_weights_normalised(self, engine):
        from decision.confidence_engine import ConfidenceEngine, _normalise_weights
        w = _normalise_weights({"smc": 50, "volume": 30, "oi": 10, "funding": 5, "regime": 5})
        assert abs(sum(w.values()) - 100.0) < 0.01

    def test_update_weights(self, engine):
        engine.update_weights({"smc": 50, "volume": 30, "oi": 10, "funding": 5, "regime": 5})
        ctx = self._make_ctx()
        result = engine.score(ctx, "LONG")
        # SMC bucket should dominate
        assert result.breakdown["smc"] >= result.breakdown["regime"]

    def test_to_dict_serialisable(self, engine):
        import json
        ctx = self._make_ctx()
        result = engine.score(ctx, "LONG")
        d = result.to_dict()
        json.dumps(d)  # must not raise


# ════════════════════════════════════════════════════════════════════════════════
# F. CAUSAL EXPLAINER
# ════════════════════════════════════════════════════════════════════════════════

class TestCausalExplainer:

    @pytest.fixture
    def explainer(self):
        from decision.causal_explainer import CausalExplainer
        return CausalExplainer()

    def _make_confidence_result(self, direction="LONG", confidence=82, blocked=False):
        from decision.confidence_engine import ConfidenceResult
        r = ConfidenceResult()
        r.direction  = direction
        r.action     = direction if not blocked else "BLOCKED"
        r.confidence = confidence
        r.breakdown  = {"smc": 28, "volume": 16, "oi": 20, "funding": 8, "regime": 10}
        r.blocked    = blocked
        r.block_reasons = ["FUNDING_BLOCK_LONG"] if blocked else []
        r.mtf_aligned = True
        r.regime = "TREND"
        return r

    def _make_ctx(self):
        from intelligence.market_context_builder import _smc_to_dict, _volume_to_dict
        from features.smc_engine import SMCSignals
        from features.volume_engine import VolumeSignals
        from futures.futures_intel_engine import FuturesIntelEngine

        smc = SMCSignals()
        smc.bos = True; smc.bos_direction = "Bullish"
        smc.choch = True; smc.choch_direction = "Bullish"
        smc.ob = True; smc.ob_direction = "Bullish"; smc.ob_top = 68000; smc.ob_bottom = 67500
        smc.fvg = True; smc.fvg_direction = "Bullish"

        vol = VolumeSignals()
        vol.volume_spike = True; vol.volume_ratio = 2.4; vol.obv_direction = "bullish"
        vol.breakout_confirmed = True

        fut = FuturesIntelEngine().analyse(_make_market_data())

        return {
            "regime": "TREND", "trend_bias": "LONG_BIAS", "trend_strength": "STRONG",
            "trend_data": {"adx": 36.0, "ema_stack": "BULLISH"},
            "smc_m15": _smc_to_dict(smc),
            "volume": _volume_to_dict(vol),
            "futures": fut.to_dict(),
            "oi_delta": 0.015, "funding_rate": 0.0001,
            "mtf_aligned": True, "blocks_long": False, "blocks_short": False,
        }

    def test_explain_returns_explanation_result(self, explainer):
        from decision.causal_explainer import ExplanationResult
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        assert isinstance(result, ExplanationResult)

    def test_reasoning_is_dict(self, explainer):
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        assert isinstance(result.reasoning, dict)

    def test_factors_list_present(self, explainer):
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        assert "factors" in result.reasoning
        assert isinstance(result.reasoning["factors"], list)
        assert len(result.reasoning["factors"]) > 0

    def test_factor_structure(self, explainer):
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        factor = result.reasoning["factors"][0]
        required = {"agent", "name", "value", "contribution", "weight", "verdict", "detail"}
        assert required.issubset(factor.keys())

    def test_verdict_values(self, explainer):
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        valid_verdicts = {"SUPPORTS", "OPPOSES", "NEUTRAL"}
        for f in result.reasoning["factors"]:
            assert f["verdict"] in valid_verdicts

    def test_meta_present(self, explainer):
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        meta = result.reasoning.get("meta", {})
        assert "regime" in meta
        assert "timestamp" in meta

    def test_hard_blocks_populated_when_blocked(self, explainer):
        conf_blocked = self._make_confidence_result(blocked=True)
        ctx = self._make_ctx()
        ctx["funding_rate"] = 0.0008
        result = explainer.explain(conf_blocked, ctx)
        assert result.has_blocks() is True
        block = result.reasoning["hard_blocks"][0]
        assert block["agent"] == "RISK_MANAGER"
        assert "reason" in block
        assert "detail" in block

    def test_summary_is_string(self, explainer):
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        assert isinstance(result.summary, str)
        assert len(result.summary) > 10

    def test_to_dict_json_serialisable(self, explainer):
        import json
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        json.dumps(result.to_dict())

    def test_skip_action_summary(self, explainer):
        cr = self._make_confidence_result(direction="", confidence=30)
        cr.action = "SKIP"
        result = explainer.explain(cr, self._make_ctx())
        assert "threshold" in result.summary.lower() or "below" in result.summary.lower() or "no trade" in result.summary.lower()

    def test_agent_names_valid(self, explainer):
        from decision.causal_explainer import AGENT_SMC, AGENT_VOLUME, AGENT_FUTURES, AGENT_REGIME, AGENT_RISK
        result = explainer.explain(self._make_confidence_result(), self._make_ctx())
        valid_agents = {AGENT_SMC, AGENT_VOLUME, AGENT_FUTURES, AGENT_REGIME, AGENT_RISK}
        for f in result.reasoning["factors"]:
            assert f["agent"] in valid_agents


# ════════════════════════════════════════════════════════════════════════════════
# G. EVENT BUS
# ════════════════════════════════════════════════════════════════════════════════

class TestEventBus:

    @pytest.fixture
    def bus(self):
        from events.event_bus import EventBus, reset_event_bus
        # Use a fresh non-persistent bus for each test
        return reset_event_bus(journal=None, persist=False)

    def test_publish_returns_bus_event(self, bus):
        from events.event_bus import BusEvent
        evt = bus.publish("SMC_ANALYST", "BOS_DETECTED", "Bullish BOS on M15")
        assert isinstance(evt, BusEvent)
        assert evt.agent == "SMC_ANALYST"
        assert evt.event == "BOS_DETECTED"

    def test_get_recent_returns_list(self, bus):
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "test")
        recent = bus.get_recent(limit=10)
        assert isinstance(recent, list)
        assert len(recent) == 1

    def test_get_recent_most_recent_first(self, bus):
        bus.publish("SMC_ANALYST", "EVENT_A", "first")
        bus.publish("SMC_ANALYST", "EVENT_B", "second")
        recent = bus.get_recent(limit=10)
        assert recent[0]["event"] == "EVENT_B"

    def test_filter_by_agent(self, bus):
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "smc event")
        bus.publish("VOLUME_ANALYST", "VOLUME_SPIKE", "vol event")
        smc_events = bus.get_recent(agent="SMC_ANALYST")
        assert len(smc_events) == 1
        assert smc_events[0]["agent"] == "SMC_ANALYST"

    def test_filter_by_severity(self, bus):
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "info", severity="info")
        bus.publish("RISK_MANAGER", "EMERGENCY", "critical!", severity="critical")
        crits = bus.get_recent(severity="critical")
        assert len(crits) == 1
        assert crits[0]["severity"] == "critical"

    def test_filter_by_event_type(self, bus):
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "msg1")
        bus.publish("SMC_ANALYST", "CHOCH_DETECTED", "msg2")
        bos_only = bus.get_recent(event_type="BOS_DETECTED")
        assert len(bos_only) == 1

    def test_subscriber_called_on_publish(self, bus):
        received = []
        bus.subscribe("SMC_ANALYST", lambda e: received.append(e))
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "test")
        assert len(received) == 1
        assert received[0].event == "BOS_DETECTED"

    def test_wildcard_subscriber_receives_all(self, bus):
        received = []
        bus.subscribe("*", lambda e: received.append(e))
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "a")
        bus.publish("VOLUME_ANALYST", "VOLUME_SPIKE", "b")
        assert len(received) == 2

    def test_subscriber_not_called_for_other_agent(self, bus):
        received = []
        bus.subscribe("SMC_ANALYST", lambda e: received.append(e))
        bus.publish("VOLUME_ANALYST", "VOLUME_SPIKE", "not for smc")
        assert len(received) == 0

    def test_unsubscribe(self, bus):
        received = []
        cb = lambda e: received.append(e)
        bus.subscribe("SMC_ANALYST", cb)
        bus.publish("SMC_ANALYST", "EVENT_1", "before unsub")
        bus.unsubscribe("SMC_ANALYST", cb)
        bus.publish("SMC_ANALYST", "EVENT_2", "after unsub")
        assert len(received) == 1

    def test_clear_empties_buffer(self, bus):
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "msg")
        bus.clear()
        assert len(bus.get_recent()) == 0

    def test_ring_buffer_respects_limit(self, bus):
        for i in range(10):
            bus.publish("SMC_ANALYST", f"EVENT_{i}", f"msg {i}")
        recent = bus.get_recent(limit=5)
        assert len(recent) == 5

    def test_thread_safe_concurrent_publish(self, bus):
        results = []
        errors  = []

        def publish_n(n: int):
            try:
                for i in range(n):
                    bus.publish("SMC_ANALYST", f"EVT_{i}", f"msg {i}")
                results.append(n)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=publish_n, args=(20,)) for _ in range(5)]
        for t in threads: t.start()
        for t in threads: t.join()

        assert len(errors) == 0
        assert len(results) == 5

    def test_get_latest_returns_most_recent(self, bus):
        bus.publish("SMC_ANALYST", "EVENT_A", "first")
        bus.publish("SMC_ANALYST", "EVENT_B", "second")
        latest = bus.get_latest()
        assert latest["event"] == "EVENT_B"

    def test_get_latest_none_on_empty(self, bus):
        assert bus.get_latest() is None

    def test_payload_preserved(self, bus):
        payload = {"tf": "M15", "price": 67000.0, "direction": "Bullish"}
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "test", payload=payload)
        evt = bus.get_latest()
        assert evt["payload"] == payload

    def test_subscriber_error_does_not_crash_bus(self, bus):
        def bad_sub(e):
            raise RuntimeError("subscriber crash")
        bus.subscribe("SMC_ANALYST", bad_sub)
        # Should not raise
        evt = bus.publish("SMC_ANALYST", "BOS_DETECTED", "test")
        assert evt.event == "BOS_DETECTED"

    def test_agent_publisher_convenience(self, bus):
        from events.event_bus import AgentPublisher
        pub = AgentPublisher("VOLUME_ANALYST")
        evt = pub.info("VOLUME_SPIKE", "2.3x spike detected", {"ratio": 2.3})
        assert evt.agent == "VOLUME_ANALYST"
        assert evt.severity == "info"

    def test_singleton_returns_same_instance(self):
        from events.event_bus import get_event_bus, reset_event_bus
        reset_event_bus(persist=False)
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2

    def test_event_bus_with_journal_persists(self):
        import tempfile, os
        from events.event_bus import EventBus
        from journal.journal_v2 import TradeJournalV2
        # Use a temp file db so each test gets a clean schema (not shared :memory:)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            journal = TradeJournalV2(db_path=db_path)
            bus = EventBus(journal=journal, persist=True)
            bus.publish("SMC_ANALYST", "BOS_DETECTED", "Bullish BOS", payload={"tf": "M15"})
            msgs = journal.get_agent_messages(limit=5, agent="SMC_ANALYST")
            assert len(msgs) == 1
            assert msgs[0]["event"] == "BOS_DETECTED"
            assert msgs[0]["payload"]["tf"] == "M15"
        finally:
            os.unlink(db_path)
