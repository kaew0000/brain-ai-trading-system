"""ml/predictor.py — Phase 3C: run-time inference (never places orders)"""
from __future__ import annotations
import numpy as np
from typing import Optional
from utils.logger import get_logger
logger = get_logger(__name__)

FEATURE_COLS = [
    "direction_enc","confidence","funding","open_interest","oi_delta",
    "liquidation_signal","fear_greed","regime_enc","volatility","atr",
    "smc_score","volume_score",
]

REGIME_ENC  = {"":0,"RANGE":1,"TREND":2,"SQUEEZE":3,"HIGH_VOLATILITY":4,
               "LOW_VOLATILITY":5,"BREAKOUT":6,"ACCUMULATION":7}
DIR_ENC     = {"":0,"SHORT":-1,"LONG":1}


def _build_x(features: dict) -> np.ndarray:
    direction_enc = DIR_ENC.get(features.get("direction",""), 0)
    regime_enc    = REGIME_ENC.get(features.get("regime",""), 0)
    row = [
        direction_enc,
        float(features.get("confidence", 0)),
        float(features.get("funding", 0)),
        float(features.get("open_interest", 0)),
        float(features.get("oi_delta", 0)),
        float(features.get("liquidation_signal", 0)),
        float(features.get("fear_greed", 50)),
        regime_enc,
        float(features.get("volatility", 0)),
        float(features.get("atr", 0)),
        float(features.get("smc_score", 0)),
        float(features.get("volume_score", 0)),
    ]
    return np.array(row, dtype=float).reshape(1, -1)


def predict_meta_label(model, features: dict) -> str:
    """
    Classify: TRADE or SKIP.
    Returns "TRADE" if model predicts win (1), "SKIP" if loss (0).
    Returns "TRADE" if model is None (fail-open so the system keeps trading).
    """
    if model is None:
        return "TRADE"
    try:
        X = _build_x(features)
        pred = model.predict(X)[0]
        return "TRADE" if float(pred) >= 0.5 else "SKIP"
    except Exception as exc:
        logger.debug(f"predict_meta_label failed: {exc}")
        return "TRADE"


def predict_outcome_probability(model, features: dict) -> float:
    """
    Estimate P(TP before SL) as 0-100.
    Returns 50.0 if model is None or fails (neutral).
    """
    if model is None:
        return 50.0
    try:
        X = _build_x(features)
        if hasattr(model, "predict_proba"):
            prob = model.predict_proba(X)[0][1]
        else:
            prob = float(model.predict(X)[0])
        return float(np.clip(prob, 0.0, 1.0) * 100.0)
    except Exception as exc:
        logger.debug(f"predict_outcome_probability failed: {exc}")
        return 50.0
