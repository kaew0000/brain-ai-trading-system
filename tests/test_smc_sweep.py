"""Liquidity-sweep detection (SMCEngine) and its use in SMCAnalyst."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.smc_analyst import SMCAnalyst
from config.settings import settings
from features.smc_engine import SMCEngine, SMCSignals

pytestmark = pytest.mark.unit


def _df(n: int = 60, close: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({
        "open": np.full(n, 100.0), "high": np.full(n, 101.0),
        "low": np.full(n, 99.0), "close": np.full(n, close),
        "volume": np.full(n, 10.0),
    })


def _liq(liquidity: int, level: float, swept: float) -> pd.DataFrame:
    return pd.DataFrame({"Liquidity": [liquidity], "Level": [level],
                         "End": [5.0], "Swept": [swept]})


class TestExtractSweep:
    def test_bullish_sweep_of_equal_lows_with_reclaim(self):
        df = _df(close=100.0)
        df.loc[55, "low"] = 97.0                       # wick below 98
        sig = SMCSignals()
        SMCEngine()._extract_sweep(df, _liq(-1, 98.0, 55.0), sig)
        assert sig.sweep and sig.sweep_direction == "Bullish"
        assert sig.sweep_level == 98.0
        assert sig.sweep_extreme == 97.0
        assert sig.sweep_bars_ago == 4

    def test_bearish_sweep_of_equal_highs_with_reclaim(self):
        df = _df(close=100.0)
        df.loc[55, "high"] = 104.0
        sig = SMCSignals()
        SMCEngine()._extract_sweep(df, _liq(1, 102.0, 55.0), sig)
        assert sig.sweep and sig.sweep_direction == "Bearish"
        assert sig.sweep_extreme == 104.0

    def test_no_reclaim_is_not_a_sweep(self):
        df = _df(close=96.0)                           # still below 98
        sig = SMCSignals()
        SMCEngine()._extract_sweep(df, _liq(-1, 98.0, 55.0), sig)
        assert not sig.sweep

    def test_reclaim_requirement_can_be_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_SWEEP_REQUIRES_RECLAIM", False)
        sig = SMCSignals()
        SMCEngine()._extract_sweep(_df(close=96.0), _liq(-1, 98.0, 55.0), sig)
        assert sig.sweep

    def test_stale_sweep_ignored(self):
        sig = SMCSignals()
        SMCEngine()._extract_sweep(_df(), _liq(-1, 98.0, 10.0), sig)
        assert not sig.sweep

    def test_unswept_or_missing_frame_ignored(self):
        sig = SMCSignals()
        SMCEngine()._extract_sweep(_df(), _liq(-1, 98.0, 0.0), sig)
        SMCEngine()._extract_sweep(_df(), None, sig)
        assert not sig.sweep

    def test_defaults_are_neutral(self):
        s = SMCSignals()
        assert (s.sweep, s.sweep_direction, s.sweep_bars_ago) == (False, "", -1)
        assert "sweep" in s.to_dict()


def _ctx(sweep_dir: str = "") -> dict:
    return {
        "symbol": "BTCUSDT", "mtf_aligned": False, "mtf_direction": "",
        "smc_m15": {
            "choch": True, "choch_dir": "Bullish", "trend_bias": "LONG_BIAS",
            "sweep": bool(sweep_dir), "sweep_dir": sweep_dir,
            "sweep_level": 98.0, "sweep_bars_ago": 3,
        },
        "smc_h1": {}, "smc_h4": {},
    }


class TestAnalystSweep:
    def test_default_flags_leave_scoring_unchanged(self):
        base = SMCAnalyst().analyse(_ctx(""))
        with_sweep = SMCAnalyst().analyse(_ctx("Bullish"))
        assert base.signal == with_sweep.signal == "LONG"
        assert base.confidence == with_sweep.confidence

    def test_liquidity_verdict_reflects_sweep(self):
        r = SMCAnalyst().analyse(_ctx("Bullish"))
        liq = next(f for f in r.factors if f.get("name") == "Liquidity"
                   or getattr(f, "name", "") == "Liquidity")
        verdict = liq["verdict"] if isinstance(liq, dict) else liq.verdict
        assert verdict == "SUPPORTS"

    def test_sweep_scoring_adds_a_point_symmetrically(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_SWEEP_SCORING_ENABLED", True)
        bull = SMCAnalyst().analyse(_ctx("Bullish"))
        none = SMCAnalyst().analyse(_ctx(""))
        assert bull.signal == "LONG"
        assert bull.confidence == pytest.approx(3 / 8 * 100)
        assert none.confidence == pytest.approx(2 / 8 * 100)

    def test_choch_gate_requires_same_direction_sweep(self, monkeypatch):
        monkeypatch.setattr(settings, "SMC_CHOCH_REQUIRES_SWEEP", True)
        assert SMCAnalyst().analyse(_ctx("")).confidence < \
            SMCAnalyst().analyse(_ctx("Bullish")).confidence
        assert SMCAnalyst().analyse(_ctx("Bearish")).confidence == \
            SMCAnalyst().analyse(_ctx("")).confidence

    def test_raw_exposes_sweep(self):
        r = SMCAnalyst().analyse(_ctx("Bullish"))
        assert r.raw["sweep"] is True and r.raw["sweep_dir"] == "Bullish"


def test_engine_direction_names_map_to_signal_in_factor_verdicts():
    ctx = _ctx("")
    ctx["smc_m15"].update({"bos": True, "bos_dir": "Bullish"})
    r = SMCAnalyst().analyse(ctx)
    bos = next(f for f in r.factors
               if (f["name"] if isinstance(f, dict) else f.name) == "BOS")
    assert (bos["verdict"] if isinstance(bos, dict) else bos.verdict) == "SUPPORTS"
