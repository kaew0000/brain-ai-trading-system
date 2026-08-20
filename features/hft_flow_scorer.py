"""features/hft_flow_scorer.py — V16 Phase 4C Track B, HFT-3: combines
HFT-2's raw microstructure features (features.microstructure_engine.
HFTFlowSignal) into HFT_FLOW_SCORE (-100..+100) and a 5-state enum.

Scope discipline (HFT-3 only — see the Phase 4C Track B design review §4/§6):
  This module ONLY fills in HFTFlowSignal.score/.state. It does NOT touch
  decision/confidence_engine.py, does NOT compute a contradiction penalty
  against SMC/Volume/OI/Regime (design review §8/§9's Hybrid model), and
  is NOT called from anywhere in the ConfidenceEngine/CEO-gate/RiskEngine/
  execution path. Per the design review's roadmap, decision integration
  is a separate, later, separately-approved phase — HFT-4 (shadow mode)
  only requires this score to exist and be observable/logged, explicitly
  with NO trading impact.

Design (per design review §4/§6, and this module's own settings, all
config-driven — see config/settings.py's "HFT-3 Flow Score" section):
  1. depth_imbalance is used directly (already bounded to [-1, 1] by
     MicrostructureEngine's construction — see that module's docstring).
  2. delta and cvd_slope are raw volume-unit measurements with no natural
     bound; each is normalized to [-1, 1] via a configurable divisor
     (HFT_FLOW_DELTA_NORMALIZER / HFT_FLOW_CVD_SLOPE_NORMALIZER) and
     clamped. These divisors are explicitly flagged in settings.py as
     provisional — no historical data exists yet to calibrate them per
     symbol (design review §17).
  3. The three normalized components are combined via a weighted average
     (weights configurable, normalized by their own sum — mirroring
     decision.confidence_engine.ConfidenceEngine._normalise_weights()'s
     convention, for consistency with the rest of this codebase).
  4. trade_intensity is applied as a MAGNITUDE DAMPENER on the combined
     score, not a 4th directional input (design review §6 is explicit
     about this distinction) — a quiet/thin market's reading is trusted
     less but never zeroed outright (a configurable floor multiplier
     prevents that), and intensity can never flip or invent a direction
     since it only ever scales the already-computed combined value.
  5. HARD GATE (design review §10): if `feature_confidence <= 0.0`
     (stale/disconnected/invalid book, from HFT-1/HFT-2), the score is
     forced to 0.0 and state to NEUTRAL — unconditionally, before any of
     the above combination logic runs. This is the literal implementation
     of "feature_confidence=0 means contribute nothing", now that there
     is finally a score for it to gate.
"""
from __future__ import annotations

import dataclasses

from config.settings import settings
from features.microstructure_engine import HFTFlowSignal
from utils.logger import get_logger

logger = get_logger(__name__)

STRONG_BUY_FLOW = "STRONG_BUY_FLOW"
BUY_FLOW = "BUY_FLOW"
NEUTRAL = "NEUTRAL"
SELL_FLOW = "SELL_FLOW"
STRONG_SELL_FLOW = "STRONG_SELL_FLOW"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class HFTFlowScorer:
    """Stateless — compute() is a pure function of its input plus this
    instance's (config-driven) parameters. Unlike MicrostructureEngine,
    there is no cross-call state to maintain here."""

    def __init__(
        self,
        *,
        delta_normalizer: float | None = None,
        cvd_slope_normalizer: float | None = None,
        weight_depth_imbalance: float | None = None,
        weight_delta: float | None = None,
        weight_cvd_slope: float | None = None,
        intensity_reference: float | None = None,
        min_intensity_multiplier: float | None = None,
        strong_threshold: float | None = None,
        moderate_threshold: float | None = None,
    ) -> None:
        self._delta_normalizer = delta_normalizer if delta_normalizer is not None else settings.HFT_FLOW_DELTA_NORMALIZER
        self._cvd_slope_normalizer = (
            cvd_slope_normalizer if cvd_slope_normalizer is not None else settings.HFT_FLOW_CVD_SLOPE_NORMALIZER
        )
        self._w_depth = weight_depth_imbalance if weight_depth_imbalance is not None else settings.HFT_FLOW_WEIGHT_DEPTH_IMBALANCE
        self._w_delta = weight_delta if weight_delta is not None else settings.HFT_FLOW_WEIGHT_DELTA
        self._w_cvd_slope = weight_cvd_slope if weight_cvd_slope is not None else settings.HFT_FLOW_WEIGHT_CVD_SLOPE
        self._intensity_reference = (
            intensity_reference if intensity_reference is not None else settings.HFT_FLOW_INTENSITY_REFERENCE
        )
        self._min_intensity_multiplier = (
            min_intensity_multiplier if min_intensity_multiplier is not None else settings.HFT_FLOW_MIN_INTENSITY_MULTIPLIER
        )
        self._strong_threshold = strong_threshold if strong_threshold is not None else settings.HFT_FLOW_STRONG_THRESHOLD
        self._moderate_threshold = (
            moderate_threshold if moderate_threshold is not None else settings.HFT_FLOW_MODERATE_THRESHOLD
        )

    def score(self, signal: HFTFlowSignal) -> HFTFlowSignal:
        """Returns a NEW HFTFlowSignal with .score/.state filled in — does
        not mutate the input. Every other field is copied through
        unchanged (dataclasses.replace), so callers can always trust the
        returned object carries the same raw features the input had."""
        if signal.feature_confidence <= 0.0:
            # Hard gate — see module docstring point 5. No combination
            # logic below is even evaluated; this is not "compute then
            # override", it's "never compute at all" when data isn't
            # trustworthy.
            return dataclasses.replace(signal, score=0.0, state=NEUTRAL)

        norm_depth = _clamp(signal.depth_imbalance, -1.0, 1.0)
        norm_delta = self._normalize(signal.delta, self._delta_normalizer)
        norm_cvd_slope = self._normalize(signal.cvd_slope, self._cvd_slope_normalizer)

        total_weight = self._w_depth + self._w_delta + self._w_cvd_slope
        if total_weight <= 0:
            logger.warning("HFTFlowScorer: total weight <= 0, returning NEUTRAL")
            return dataclasses.replace(signal, score=0.0, state=NEUTRAL)

        combined = (
            norm_depth * self._w_depth + norm_delta * self._w_delta + norm_cvd_slope * self._w_cvd_slope
        ) / total_weight

        intensity_multiplier = self._intensity_multiplier(signal.trade_intensity)

        raw_score = combined * intensity_multiplier * 100.0
        final_score = _clamp(raw_score, -100.0, 100.0)
        final_state = self._classify(final_score)

        return dataclasses.replace(signal, score=final_score, state=final_state)

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _normalize(value: float, normalizer: float) -> float:
        if normalizer <= 0:
            return 0.0
        return _clamp(value / normalizer, -1.0, 1.0)

    def _intensity_multiplier(self, trade_intensity: float) -> float:
        if self._intensity_reference <= 0:
            return 1.0
        return _clamp(
            trade_intensity / self._intensity_reference,
            self._min_intensity_multiplier,
            1.0,
        )

    def _classify(self, score: float) -> str:
        if score >= self._strong_threshold:
            return STRONG_BUY_FLOW
        if score >= self._moderate_threshold:
            return BUY_FLOW
        if score <= -self._strong_threshold:
            return STRONG_SELL_FLOW
        if score <= -self._moderate_threshold:
            return SELL_FLOW
        return NEUTRAL
