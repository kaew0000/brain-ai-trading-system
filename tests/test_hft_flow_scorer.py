"""tests/test_hft_flow_scorer.py — V16 Phase 4C Track B, HFT-3.

Covers features/hft_flow_scorer.py: feature normalization/weighting into
HFT_FLOW_SCORE, intensity-based magnitude dampening (never a directional
flip), 5-state classification thresholds, and the hard feature_confidence
gate (design review §10) that must override every other computation.
"""
import pytest

from features.hft_flow_scorer import (
    BUY_FLOW,
    NEUTRAL,
    SELL_FLOW,
    STRONG_BUY_FLOW,
    STRONG_SELL_FLOW,
    HFTFlowScorer,
)
from features.microstructure_engine import HFTFlowSignal

pytestmark = pytest.mark.unit


def _signal(**overrides):
    base = dict(
        depth_imbalance=0.0,
        delta=0.0,
        cvd=0.0,
        cvd_slope=0.0,
        aggressive_buy_volume=0.0,
        aggressive_sell_volume=0.0,
        trade_intensity=10.0,   # saturate the intensity multiplier by default
        spread=0.5,
        mid_price=100.0,
        data_age_ms=10,
        book_valid=True,
        sequence_valid=True,
        stream_connected=True,
        feature_confidence=1.0,
    )
    base.update(overrides)
    return HFTFlowSignal(**base)


def _scorer(**overrides):
    defaults = dict(
        delta_normalizer=10.0,
        cvd_slope_normalizer=5.0,
        weight_depth_imbalance=1.0,
        weight_delta=0.0,
        weight_cvd_slope=0.0,
        intensity_reference=2.0,
        min_intensity_multiplier=0.3,
        strong_threshold=70.0,
        moderate_threshold=30.0,
    )
    defaults.update(overrides)
    return HFTFlowScorer(**defaults)


# ── Hard gate (design review §10) — overrides everything else ───────────

def test_zero_feature_confidence_forces_neutral_regardless_of_features():
    scorer = _scorer(weight_depth_imbalance=1.0)
    sig = _signal(feature_confidence=0.0, depth_imbalance=1.0, delta=1000.0, cvd_slope=1000.0)
    out = scorer.score(sig)
    assert out.score == 0.0
    assert out.state == NEUTRAL


def test_negative_feature_confidence_also_forces_neutral():
    scorer = _scorer()
    sig = _signal(feature_confidence=-0.5, depth_imbalance=1.0)
    out = scorer.score(sig)
    assert out.score == 0.0
    assert out.state == NEUTRAL


def test_positive_feature_confidence_allows_normal_scoring():
    scorer = _scorer(weight_depth_imbalance=1.0)
    sig = _signal(feature_confidence=1.0, depth_imbalance=0.5)
    out = scorer.score(sig)
    assert out.score != 0.0


# ── Other fields passed through unchanged ─────────────────────────────────

def test_score_does_not_mutate_input_and_preserves_other_fields():
    scorer = _scorer()
    sig = _signal(depth_imbalance=0.5, cvd=42.0, spread=1.23, mid_price=100.0)
    out = scorer.score(sig)
    assert sig.score == 0.0   # input untouched
    assert out.cvd == 42.0
    assert out.spread == 1.23
    assert out.mid_price == 100.0
    assert out is not sig


# ── Depth imbalance alone ─────────────────────────────────────────────────

def test_pure_depth_imbalance_positive_gives_positive_score():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0)
    sig = _signal(depth_imbalance=0.6)
    out = scorer.score(sig)
    assert out.score == pytest.approx(60.0)   # 0.6 * 100 * intensity(1.0, saturated)


def test_pure_depth_imbalance_negative_gives_negative_score():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0)
    sig = _signal(depth_imbalance=-0.6)
    out = scorer.score(sig)
    assert out.score == pytest.approx(-60.0)


def test_zero_depth_imbalance_gives_neutral_zero_score():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0)
    sig = _signal(depth_imbalance=0.0)
    out = scorer.score(sig)
    assert out.score == pytest.approx(0.0)
    assert out.state == NEUTRAL


# ── Delta / CVD-slope normalization ───────────────────────────────────────

def test_delta_normalized_and_weighted():
    scorer = _scorer(weight_depth_imbalance=0.0, weight_delta=1.0, weight_cvd_slope=0.0, delta_normalizer=10.0)
    sig = _signal(delta=5.0)   # 5/10 = 0.5 normalized
    out = scorer.score(sig)
    assert out.score == pytest.approx(50.0)


def test_delta_beyond_normalizer_clamped_to_one():
    scorer = _scorer(weight_depth_imbalance=0.0, weight_delta=1.0, weight_cvd_slope=0.0, delta_normalizer=10.0)
    sig = _signal(delta=1000.0)   # way beyond normalizer
    out = scorer.score(sig)
    assert out.score == pytest.approx(100.0)   # clamped, not 1000%


def test_cvd_slope_normalized_and_weighted():
    scorer = _scorer(weight_depth_imbalance=0.0, weight_delta=0.0, weight_cvd_slope=1.0, cvd_slope_normalizer=5.0)
    sig = _signal(cvd_slope=-2.5)   # -2.5/5 = -0.5
    out = scorer.score(sig)
    assert out.score == pytest.approx(-50.0)


def test_zero_normalizer_treated_as_zero_contribution_not_division_error():
    scorer = _scorer(weight_depth_imbalance=0.0, weight_delta=1.0, weight_cvd_slope=0.0, delta_normalizer=0.0)
    sig = _signal(delta=5.0)
    out = scorer.score(sig)   # must not raise ZeroDivisionError
    assert out.score == pytest.approx(0.0)


# ── Weighted combination of multiple components ──────────────────────────

def test_combined_weighted_average_of_all_three_components():
    scorer = _scorer(
        weight_depth_imbalance=1.0, weight_delta=1.0, weight_cvd_slope=1.0,
        delta_normalizer=10.0, cvd_slope_normalizer=5.0,
    )
    sig = _signal(depth_imbalance=0.3, delta=3.0, cvd_slope=1.0)   # norm: 0.3, 0.3, 0.2
    out = scorer.score(sig)
    expected = ((0.3 + 0.3 + 0.2) / 3.0) * 100.0
    assert out.score == pytest.approx(expected)


def test_weights_need_not_sum_to_one_normalized_internally():
    scorer_a = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0)
    scorer_b = _scorer(weight_depth_imbalance=10.0, weight_delta=0.0, weight_cvd_slope=0.0)
    sig = _signal(depth_imbalance=0.4)
    assert scorer_a.score(sig).score == pytest.approx(scorer_b.score(sig).score)


def test_all_zero_weights_returns_neutral_without_crashing():
    scorer = _scorer(weight_depth_imbalance=0.0, weight_delta=0.0, weight_cvd_slope=0.0)
    sig = _signal(depth_imbalance=0.9)
    out = scorer.score(sig)
    assert out.score == 0.0
    assert out.state == NEUTRAL


# ── Intensity dampening — magnitude only, never direction ───────────────

def test_low_intensity_dampens_score_but_keeps_same_sign():
    scorer = _scorer(
        weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0,
        intensity_reference=2.0, min_intensity_multiplier=0.3,
    )
    sig_full_intensity = _signal(depth_imbalance=0.6, trade_intensity=10.0)
    sig_low_intensity = _signal(depth_imbalance=0.6, trade_intensity=0.0)
    full = scorer.score(sig_full_intensity).score
    low = scorer.score(sig_low_intensity).score
    assert full == pytest.approx(60.0)
    assert low == pytest.approx(60.0 * 0.3)   # floored at min_intensity_multiplier
    assert low > 0   # same sign, never flipped
    assert low < full


def test_intensity_multiplier_never_below_floor():
    scorer = _scorer(
        weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0,
        intensity_reference=2.0, min_intensity_multiplier=0.25,
    )
    sig = _signal(depth_imbalance=0.5, trade_intensity=0.0)
    out = scorer.score(sig)
    assert out.score == pytest.approx(50.0 * 0.25)


def test_negative_score_direction_preserved_under_dampening():
    scorer = _scorer(
        weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0,
        intensity_reference=2.0, min_intensity_multiplier=0.3,
    )
    sig = _signal(depth_imbalance=-0.6, trade_intensity=0.0)
    out = scorer.score(sig)
    assert out.score < 0


def test_zero_intensity_reference_disables_dampening():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0, intensity_reference=0.0)
    sig = _signal(depth_imbalance=0.5, trade_intensity=0.0)
    out = scorer.score(sig)
    assert out.score == pytest.approx(50.0)   # full multiplier=1.0 when reference disabled


# ── State classification thresholds ───────────────────────────────────────

@pytest.mark.parametrize("depth_imbalance,expected_state", [
    (0.71, STRONG_BUY_FLOW),   # score ~71 >= strong(70)
    (0.71, STRONG_BUY_FLOW),
    (0.40, BUY_FLOW),          # score ~40, in [30,70)
    (0.10, NEUTRAL),           # score ~10, in (-30,30)
    (0.0, NEUTRAL),
    (-0.10, NEUTRAL),
    (-0.40, SELL_FLOW),
    (-0.71, STRONG_SELL_FLOW),
])
def test_state_classification_thresholds(depth_imbalance, expected_state):
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0)
    sig = _signal(depth_imbalance=depth_imbalance)
    out = scorer.score(sig)
    assert out.state == expected_state


def test_exact_strong_threshold_boundary_is_strong():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0, strong_threshold=70.0)
    sig = _signal(depth_imbalance=0.70)   # exactly 70.0
    out = scorer.score(sig)
    assert out.state == STRONG_BUY_FLOW


def test_exact_moderate_threshold_boundary_is_buy_flow_not_neutral():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=0.0, weight_cvd_slope=0.0, moderate_threshold=30.0)
    sig = _signal(depth_imbalance=0.30)   # exactly 30.0
    out = scorer.score(sig)
    assert out.state == BUY_FLOW


def test_score_hard_clamped_to_plus_minus_100():
    scorer = _scorer(weight_depth_imbalance=1.0, weight_delta=1.0, weight_cvd_slope=1.0,
                      delta_normalizer=0.001, cvd_slope_normalizer=0.001)
    sig = _signal(depth_imbalance=1.0, delta=1000.0, cvd_slope=1000.0)
    out = scorer.score(sig)
    assert out.score == 100.0
    assert -100.0 <= out.score <= 100.0
