"""_derive_levels(): fixed-percent defaults preserved, sweep-anchored opt-in."""

from __future__ import annotations

import pytest

from config.settings import settings
from main import _derive_levels

pytestmark = pytest.mark.unit

MARK = 100.0


def _ctx(**m15) -> dict:
    return {"smc_m15": m15}


def _long_sweep(**extra) -> dict:
    d = {"sweep": True, "sweep_dir": "Bullish", "sweep_extreme": 98.0,
         "liquidity_high": 110.0}
    d.update(extra)
    return d


@pytest.fixture
def levels_on(monkeypatch):
    monkeypatch.setattr(settings, "SMC_SWEEP_LEVELS_ENABLED", True)


class TestDefaultsUnchanged:
    def test_sweep_ignored_when_flag_off(self):
        e, sl, tp = _derive_levels("LONG", MARK, _ctx(**_long_sweep()))
        assert (e, sl, tp) == (100.0, 98.2, 105.4)

    def test_short_fixed_percent(self):
        assert _derive_levels("SHORT", MARK, _ctx()) == (100.0, 101.8, 94.6)

    def test_percent_settings_are_used(self, monkeypatch):
        monkeypatch.setattr(settings, "LEVEL_SL_PCT", 0.01)
        monkeypatch.setattr(settings, "LEVEL_TP_PCT", 0.02)
        assert _derive_levels("LONG", MARK, _ctx()) == (100.0, 99.0, 102.0)


class TestSweepLevels:
    def test_long_sl_below_extreme_tp_at_liquidity(self, levels_on):
        e, sl, tp = _derive_levels("LONG", MARK, _ctx(**_long_sweep()))
        assert e == 100.0
        assert sl == pytest.approx(98.0 * 0.999, abs=0.01)   # 97.90
        assert tp == 110.0                                    # RR ~4.8

    def test_long_low_rr_target_falls_back_to_fixed_r(self, levels_on):
        _, sl, tp = _derive_levels(
            "LONG", MARK, _ctx(**_long_sweep(liquidity_high=101.0)))
        risk = 100.0 - sl
        assert tp == pytest.approx(100.0 + 3.0 * risk, abs=0.01)

    def test_short_mirror(self, levels_on):
        ctx = _ctx(sweep=True, sweep_dir="Bearish", sweep_extreme=102.0,
                   liquidity_low=90.0)
        e, sl, tp = _derive_levels("SHORT", MARK, ctx)
        assert sl == pytest.approx(102.0 * 1.001, abs=0.01)
        assert tp == 90.0

    def test_opposite_direction_sweep_ignored(self, levels_on):
        ctx = _ctx(sweep=True, sweep_dir="Bearish", sweep_extreme=102.0)
        assert _derive_levels("LONG", MARK, ctx) == (100.0, 98.2, 105.4)

    def test_too_wide_stop_falls_back(self, levels_on):
        ctx = _ctx(**_long_sweep(sweep_extreme=90.0))        # 10% risk
        assert _derive_levels("LONG", MARK, ctx) == (100.0, 98.2, 105.4)

    def test_extreme_above_entry_falls_back(self, levels_on):
        ctx = _ctx(**_long_sweep(sweep_extreme=101.0))
        assert _derive_levels("LONG", MARK, ctx) == (100.0, 98.2, 105.4)

    def test_missing_extreme_falls_back(self, levels_on):
        ctx = _ctx(sweep=True, sweep_dir="Bullish")
        assert _derive_levels("LONG", MARK, ctx) == (100.0, 98.2, 105.4)

    def test_no_sweep_falls_back(self, levels_on):
        assert _derive_levels("LONG", MARK, _ctx()) == (100.0, 98.2, 105.4)
