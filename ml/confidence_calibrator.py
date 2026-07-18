"""ml/confidence_calibrator.py — Phase 3C: calibrate_confidence() via Platt/Isotonic"""
from __future__ import annotations
from typing import Optional
import numpy as np
from utils.logger import get_logger
logger = get_logger(__name__)

def train_calibrator(confidences: list, outcomes: list, method: str="isotonic") -> Optional[object]:
    """
    Train a calibrator mapping raw confidence (0-100) → calibrated win probability (0-100).
    method: 'platt' (Platt Scaling via LogisticRegression) or 'isotonic'
    Returns the fitted calibrator object, or None on failure.
    """
    if len(confidences) < 10:
        logger.warning("Calibrator: need >= 10 samples"); return None
    try:
        X = np.array(confidences, dtype=float).reshape(-1, 1) / 100.0
        y = np.array(outcomes, dtype=float)
        if method == "platt":
            from sklearn.linear_model import LogisticRegression
            cal = LogisticRegression(max_iter=1000)
        else:
            from sklearn.isotonic import IsotonicRegression
            cal = IsotonicRegression(out_of_bounds="clip")
        cal.fit(X.ravel() if method=="isotonic" else X, y)
        logger.info(f"Calibrator trained ({method}) on {len(y)} samples")
        return cal
    except Exception as exc:
        logger.error(f"train_calibrator failed: {exc}", exc_info=True)
        return None

def calibrate_confidence(raw_confidence: float, calibrator) -> float:
    """
    Map raw_confidence (0-100) to calibrated win probability (0-100).
    Returns raw_confidence unchanged if calibrator is None or fails.
    """
    if calibrator is None: return raw_confidence
    try:
        x = np.array([raw_confidence / 100.0])
        if hasattr(calibrator, "predict_proba"):
            prob = calibrator.predict_proba(x.reshape(1,-1))[0][1]
        else:
            prob = float(calibrator.predict(x)[0])
        return float(np.clip(prob, 0.0, 1.0) * 100.0)
    except Exception as exc:
        logger.debug(f"calibrate_confidence failed: {exc}")
        return raw_confidence
