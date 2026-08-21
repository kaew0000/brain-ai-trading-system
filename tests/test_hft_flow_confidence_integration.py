"""tests/test_hft_flow_confidence_integration.py — V16 Phase 4C Track B, HFT-5.

Covers decision/confidence_engine.py's HFT flow integration:
- The additive hft_flow category (weight 0.0 by default — inert, but
  functional when explicitly raised).
- The contradiction penalty/block tiers (gated behind
  settings.HFT_FLOW_CONTRADICTION_ENABLED, default False).
- Backward-compat defaults: with everything at its shipped default, this
  is byte-identical to before HFT-5 (see tests/test_hft_shadow_mode.py
  for the fuller end-to-end proof; this file focuses on the mechanism
  itself, in isolation, at both default and explicitly-enabled settings).
"""
import pytest

from decision.confidence_engine import ConfidenceEngine, DEFAULT_WEIGHTS

pytestmark = pytest.mark.unit


def _hft_flow(score=0.0, state="NEUTRAL", feature_confidence=1.0):
    return {
        "score": score, "state": state, "feature_confidence": feature_confidence,
        "depth_imbalance": 0.0, "delta": 0.0, "cvd": 0.0, "cvd_slope": 0.0,
        "aggressive_buy_volume": 0.0, "aggressive_sell_volume": 0.0,
        "trade_intensity": 0.0, "spread": 0.0, "mid_price": 0.0,
        "data_age_ms": 10, "book_valid": True, "sequence_valid": True,
        "stream_connected": True,
    }


def _ctx(hft_flow=None, blocks_long=False, blocks_short=False):
    ctx = {
        "regime": "TREND", "trend_bias": "LONG_BIAS", "trend_strength": "STRONG",
        "smc_m15": {}, "volume": {},
        "futures": {"funding": {}, "open_interest": {}},
        "oi_delta": 0.0, "funding_rate": 0.0001,
        "blocks_long": blocks_long, "blocks_short": blocks_short,
        "mtf_aligned": True,
    }
    if hft_flow is not None:
        ctx["futures"]["hft_flow"] = hft_flow
    return ctx


def _engine(weights=None):
    return ConfidenceEngine(weights=weights)


# ── Default weight (0.0) — inert, but breakdown key visible when data active ─

def test_default_weight_is_zero():
    assert DEFAULT_WEIGHTS["hft_flow"] == 0.0


def test_breakdown_gains_hft_flow_key_only_when_feature_confidence_positive():
    engine = _engine()
    ctx_inactive = _ctx(hft_flow=_hft_flow(score=90.0, feature_confidence=0.0))
    ctx_active = _ctx(hft_flow=_hft_flow(score=90.0, feature_confidence=1.0))
    result_inactive = engine.score(ctx_inactive, "LONG")
    result_active = engine.score(ctx_active, "LONG")
    assert "hft_flow" not in result_inactive.breakdown
    assert result_active.breakdown["hft_flow"] == 0   # weight still 0.0 by default


def test_no_hft_flow_key_at_all_leaves_breakdown_unchanged():
    engine = _engine()
    ctx = _ctx(hft_flow=None)   # futures dict has no "hft_flow" key at all
    result = engine.score(ctx, "LONG")
    assert "hft_flow" not in result.breakdown
    assert set(result.breakdown.keys()) == {"smc", "volume", "oi", "funding", "regime"}


# ── Additive term actually working when weight is explicitly raised ─────────

def test_positive_weight_and_aligned_flow_increases_confidence():
    baseline_weights = dict(DEFAULT_WEIGHTS)
    hft_weights = dict(DEFAULT_WEIGHTS)
    hft_weights["hft_flow"] = 20.0
    baseline_engine = _engine(weights=baseline_weights)
    hft_engine = _engine(weights=hft_weights)

    ctx = _ctx(hft_flow=_hft_flow(score=80.0, state="STRONG_BUY_FLOW", feature_confidence=1.0))
    baseline_result = baseline_engine.score(ctx, "LONG")
    hft_result = hft_engine.score(ctx, "LONG")

    assert hft_result.breakdown["hft_flow"] > 0
    assert hft_result.confidence >= baseline_result.confidence


def test_opposing_flow_contributes_zero_to_additive_term_not_negative():
    hft_weights = dict(DEFAULT_WEIGHTS)
    hft_weights["hft_flow"] = 20.0
    engine = _engine(weights=hft_weights)
    ctx = _ctx(hft_flow=_hft_flow(score=-80.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert result.breakdown["hft_flow"] == 0   # not negative — additive term floors at 0


def test_neutral_flow_contributes_zero():
    hft_weights = dict(DEFAULT_WEIGHTS)
    hft_weights["hft_flow"] = 20.0
    engine = _engine(weights=hft_weights)
    ctx = _ctx(hft_flow=_hft_flow(score=0.0, state="NEUTRAL", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert result.breakdown["hft_flow"] == 0


def test_short_direction_uses_opposite_sign_convention():
    hft_weights = dict(DEFAULT_WEIGHTS)
    hft_weights["hft_flow"] = 20.0
    engine = _engine(weights=hft_weights)
    ctx = _ctx(hft_flow=_hft_flow(score=-80.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "SHORT")
    assert result.breakdown["hft_flow"] > 0   # sell flow favors a SHORT


# ── _score_hft_flow direct unit tests ────────────────────────────────────

def test_score_hft_flow_zero_confidence_returns_zero():
    ctx = _ctx(hft_flow=_hft_flow(score=100.0, feature_confidence=0.0))
    assert ConfidenceEngine._score_hft_flow(ctx, "LONG") == 0.0


def test_score_hft_flow_scales_with_magnitude():
    ctx = _ctx(hft_flow=_hft_flow(score=50.0, feature_confidence=1.0))
    assert ConfidenceEngine._score_hft_flow(ctx, "LONG") == pytest.approx(0.5)


def test_score_hft_flow_clamped_at_one():
    ctx = _ctx(hft_flow=_hft_flow(score=100.0, feature_confidence=1.0))
    assert ConfidenceEngine._score_hft_flow(ctx, "LONG") == pytest.approx(1.0)


def test_score_hft_flow_empty_direction_returns_zero():
    ctx = _ctx(hft_flow=_hft_flow(score=100.0, feature_confidence=1.0))
    assert ConfidenceEngine._score_hft_flow(ctx, "") == 0.0


# ── Contradiction penalty — gated OFF by default ─────────────────────────

def test_contradiction_disabled_by_default_ignores_extreme_opposing_flow(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", False)
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=-100.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert "hft_flow_contradiction_penalty" not in result.breakdown
    assert result.blocked is False


def test_contradiction_enabled_reduce_tier_subtracts_points(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD", 70.0)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD", 90.0)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_PENALTY_POINTS", 15)
    engine = _engine()
    ctx_clean = _ctx(hft_flow=_hft_flow(score=0.0, feature_confidence=1.0))
    ctx_opposing = _ctx(hft_flow=_hft_flow(score=-80.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    clean_result = engine.score(ctx_clean, "LONG")
    opposing_result = engine.score(ctx_opposing, "LONG")
    assert opposing_result.breakdown["hft_flow_contradiction_penalty"] == -15
    assert opposing_result.confidence == max(0, clean_result.confidence - 15)
    assert opposing_result.blocked is False   # reduce tier only, not block


def test_contradiction_below_reduce_threshold_no_penalty(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD", 70.0)
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=-50.0, state="SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert "hft_flow_contradiction_penalty" not in result.breakdown


def test_contradiction_aligned_flow_never_penalized(monkeypatch):
    """hft_flow agreeing with direction must never trigger the
    contradiction path, regardless of magnitude."""
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", True)
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=100.0, state="STRONG_BUY_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert "hft_flow_contradiction_penalty" not in result.breakdown
    assert result.blocked is False


def test_contradiction_penalty_never_drives_confidence_negative(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD", 70.0)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD", 999.0)   # disable block tier
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_PENALTY_POINTS", 999)   # deliberately huge
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=-80.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert result.confidence == 0
    assert sum(result.breakdown.values()) == result.confidence   # invariant holds even here


# ── Contradiction block tier — the most extreme case ─────────────────────

def test_contradiction_block_tier_forces_blocked_action(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD", 90.0)
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=-95.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert result.blocked is True
    assert result.action == "BLOCKED"
    assert any("HFT_FLOW_CONTRADICTION_BLOCK" in r for r in result.block_reasons)


def test_contradiction_block_tier_disabled_by_default_even_at_max_opposition(monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", False)
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=-100.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert result.blocked is False


def test_contradiction_block_tier_requires_more_extreme_than_reduce_tier(monkeypatch):
    """A score that crosses the reduce threshold but not the block
    threshold must reduce, not block."""
    from config.settings import settings
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD", 70.0)
    monkeypatch.setattr(settings, "HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD", 90.0)
    engine = _engine()
    ctx = _ctx(hft_flow=_hft_flow(score=-75.0, state="STRONG_SELL_FLOW", feature_confidence=1.0))
    result = engine.score(ctx, "LONG")
    assert result.blocked is False
    assert "hft_flow_contradiction_penalty" in result.breakdown


# ── Settings defaults match the documented, shipped configuration ───────

def test_settings_defaults_are_fully_inert():
    from config.settings import Settings
    s = Settings()
    assert s.HFT_FLOW_CONTRADICTION_ENABLED is False
    assert s.HFT_FLOW_CONTRADICTION_REDUCE_THRESHOLD == 70.0
    assert s.HFT_FLOW_CONTRADICTION_BLOCK_THRESHOLD == 90.0
    assert s.HFT_FLOW_CONTRADICTION_PENALTY_POINTS == 15
