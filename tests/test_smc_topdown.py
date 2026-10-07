"""Top-down SMC state machine, M5 fetch, context wiring and hard blocks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from config.settings import settings
from decision.confidence_engine import ConfidenceEngine
from features.smc_engine import SMCSignals
from features.smc_topdown import evaluate_topdown

pytestmark = pytest.mark.unit

PRICE = 100.0


def _sig(**kw) -> SMCSignals:
    s = SMCSignals()
    for k, v in kw.items():
        setattr(s, k, v)
    return s


def _long_frames(with_m5: bool = True):
    h4 = _sig(trend_bias="Bullish")
    h1 = _sig(trend_bias="Bullish", ob=True, ob_direction="Bullish",
              ob_bottom=99.0, ob_top=101.0)
    m15 = _sig(trend_bias="Bullish", sweep=True, sweep_direction="Bullish",
               choch=True, choch_direction="Bullish")
    m5 = _sig(trend_bias="Bullish", choch=True, choch_direction="Bullish",
              fvg=True, fvg_direction="Bullish") if with_m5 else None
    return h4, h1, m15, m5


class TestStateMachine:
    def test_ready_long_full_sequence(self):
        r = evaluate_topdown("LONG", *_long_frames(), PRICE)
        assert (r.state, r.ready, r.m5_used) == ("READY", True, True)

    def test_ready_without_m5_skips_entry_step(self):
        r = evaluate_topdown("LONG", *_long_frames(with_m5=False), PRICE)
        assert r.ready and not r.m5_used

    def test_ready_short_mirror(self):
        h4 = _sig(trend_bias="Bearish")
        h1 = _sig(trend_bias="Bearish", fvg=True, fvg_direction="Bearish",
                  fvg_bottom=99.5, fvg_top=101.0)
        m15 = _sig(trend_bias="Bearish", sweep=True, sweep_direction="Bearish",
                   choch=True, choch_direction="Bearish")
        assert evaluate_topdown("SHORT", h4, h1, m15, None, PRICE).ready

    def test_no_direction_is_no_bias(self):
        r = evaluate_topdown("", *_long_frames(), PRICE)
        assert r.state == "NO_BIAS" and not r.ready

    def test_wait_bias_when_h4_neutral(self):
        h4, h1, m15, m5 = _long_frames()
        h4.trend_bias = ""
        assert evaluate_topdown("LONG", h4, h1, m15, m5, PRICE).state == "WAIT_BIAS"

    def test_wait_zone_when_price_outside_h1_zone(self):
        r = evaluate_topdown("LONG", *_long_frames(), 110.0)
        assert r.state == "WAIT_ZONE"

    def test_zone_tolerance_applies(self):
        r = evaluate_topdown("LONG", *_long_frames(), 101.1)   # 0.1% above top
        assert r.state == "READY"

    def test_wait_sweep_choch_needs_both(self):
        h4, h1, m15, m5 = _long_frames()
        m15.sweep = False
        assert evaluate_topdown("LONG", h4, h1, m15, m5, PRICE).state == "WAIT_SWEEP_CHOCH"
        h4, h1, m15, m5 = _long_frames()
        m15.choch = False
        assert evaluate_topdown("LONG", h4, h1, m15, m5, PRICE).state == "WAIT_SWEEP_CHOCH"

    def test_opposite_direction_sweep_does_not_count(self):
        h4, h1, m15, m5 = _long_frames()
        m15.sweep_direction = "Bearish"
        assert evaluate_topdown("LONG", h4, h1, m15, m5, PRICE).state == "WAIT_SWEEP_CHOCH"

    def test_wait_entry_when_m5_has_no_trigger(self):
        h4, h1, m15, m5 = _long_frames()
        m5.choch = False
        assert evaluate_topdown("LONG", h4, h1, m15, m5, PRICE).state == "WAIT_ENTRY"

    def test_conflict_when_m5_opposes(self):
        h4, h1, m15, m5 = _long_frames()
        m5.trend_bias = "Bearish"
        r = evaluate_topdown("LONG", h4, h1, m15, m5, PRICE)
        assert r.state == "CONFLICT" and r.conflict and not r.ready

    def test_conflict_when_h1_opposes(self):
        h4, h1, m15, m5 = _long_frames()
        h1.trend_bias = "Bearish"
        assert evaluate_topdown("LONG", h4, h1, m15, m5, PRICE).conflict

    def test_to_dict_shape(self):
        d = evaluate_topdown("LONG", *_long_frames(), PRICE).to_dict()
        assert set(d) == {"direction", "state", "ready", "conflict", "m5_used", "reasons"}


class TestConfidenceBlocks:
    @staticmethod
    def _blocks(td: dict, direction: str = "LONG") -> list[str]:
        return ConfidenceEngine._check_blocks({"topdown": td}, direction)

    def test_defaults_never_block(self):
        assert self._blocks({"state": "WAIT_ZONE", "ready": False, "conflict": True}) == []

    def test_gate_blocks_when_not_ready(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_TOPDOWN_GATE_ENABLED", True)
        assert self._blocks({"state": "WAIT_ZONE", "ready": False}) == ["TOPDOWN_WAIT_ZONE"]
        assert self._blocks({"state": "READY", "ready": True}) == []

    def test_conflict_flag_blocks_only_on_conflict(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_TF_CONFLICT_BLOCKS_TRADE", True)
        out = self._blocks({"state": "CONFLICT", "conflict": True, "reasons": ["opposing: M5"]})
        assert out and out[0].startswith("TF_CONFLICT")
        assert self._blocks({"state": "WAIT_ZONE", "conflict": False}) == []

    def test_missing_topdown_or_direction_never_blocks(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_TOPDOWN_GATE_ENABLED", True)
        assert ConfidenceEngine._check_blocks({}, "LONG") == []
        assert self._blocks({"state": "WAIT_ZONE", "ready": False}, direction="") == []


class TestM5Fetch:
    @staticmethod
    def _provider(monkeypatch):
        monkeypatch.setattr("binance.um_futures.UMFutures.time",
                            lambda self: {"serverTime": 1_700_000_000_000})
        monkeypatch.setattr(settings, "BINANCE_TESTNET", True)
        from data.binance_provider import BinanceDataProvider
        return BinanceDataProvider()

    @staticmethod
    def _df():
        n = 60
        return pd.DataFrame({"open": np.full(n, 1.0), "high": np.full(n, 2.0),
                             "low": np.full(n, 0.5), "close": np.full(n, 1.5),
                             "volume": np.full(n, 3.0)})

    def test_disabled_by_default_adds_nothing(self, monkeypatch):
        dp = self._provider(monkeypatch)
        called = []
        monkeypatch.setattr(dp, "get_ohlcv", lambda *a, **k: called.append(a) or self._df())
        out: dict = {}
        dp._fetch_optional_m5(out)
        assert out == {} and called == []

    def test_enabled_adds_m5(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_M5_ENABLED", True)
        dp = self._provider(monkeypatch)
        monkeypatch.setattr(dp, "get_ohlcv", lambda *a, **k: self._df())
        out: dict = {}
        dp._fetch_optional_m5(out)
        assert "m5" in out and len(out["m5"]) == 60

    def test_m5_failure_is_non_fatal(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_M5_ENABLED", True)
        dp = self._provider(monkeypatch)

        def boom(*a, **k):
            raise RuntimeError("network")
        monkeypatch.setattr(dp, "get_ohlcv", boom)
        out: dict = {}
        dp._fetch_optional_m5(out)          # must not raise
        assert out == {}

    def test_core_timeframes_unchanged(self):
        from data.binance_provider import _ohlcv_timeframes
        assert [k for k, _ in _ohlcv_timeframes()] == ["h4", "h1", "m15"]


class TestContextBuilder:
    @staticmethod
    def _build(with_m5: bool) -> dict:
        from features.smc_engine import SMCEngine
        from features.volume_engine import VolumeEngine
        from intelligence.market_context_builder import MarketContextBuilder
        from regime.regime_engine import RegimeEngine

        rng = np.random.default_rng(1)

        def mk(n=200):
            c = 50000 + np.cumsum(rng.standard_normal(n) * 150)
            return pd.DataFrame({
                "open": c, "high": c + abs(rng.standard_normal(n) * 80),
                "low": c - abs(rng.standard_normal(n) * 80), "close": c,
                "volume": rng.random(n) * 100 + 10,
            }, index=pd.date_range("2026-01-01", periods=n, freq="15min"))

        ohlcv = {"h4": mk(), "h1": mk(), "m15": mk()}
        if with_m5:
            ohlcv["m5"] = mk()
        return MarketContextBuilder().build(
            market_data={"ohlcv": ohlcv, "mark_price": float(ohlcv["m15"]["close"].iloc[-1])},
            smc_signals=SMCEngine().analyze_mtf(ohlcv),
            volume_signals=VolumeEngine().analyze(ohlcv["m15"]),
            regime_result=RegimeEngine().classify(ohlcv["h1"]),
            ohlcv_h4=ohlcv["h4"], ohlcv_h1=ohlcv["h1"],
        )

    def test_without_m5_context_is_backward_compatible(self):
        ctx = self._build(with_m5=False)
        assert ctx["smc_m5"] == {}
        assert ctx["topdown"]["m5_used"] is False
        assert {"smc_h4", "smc_h1", "smc_m15", "mtf_direction", "mtf_aligned"} <= set(ctx)

    def test_with_m5_context_carries_m5_and_topdown(self):
        ctx = self._build(with_m5=True)
        assert "sweep" in ctx["smc_m5"] and "choch" in ctx["smc_m5"]
        assert ctx["topdown"]["m5_used"] is True
        assert ctx["topdown"]["state"] in {
            "NO_BIAS", "CONFLICT", "WAIT_BIAS", "WAIT_ZONE",
            "WAIT_SWEEP_CHOCH", "WAIT_ENTRY", "READY"}

    def test_smc_dict_has_sweep_keys(self):
        from intelligence.market_context_builder import _smc_to_dict
        d = _smc_to_dict(_sig(sweep=True, sweep_direction="Bullish"))
        assert d["sweep"] is True and d["sweep_dir"] == "Bullish"
