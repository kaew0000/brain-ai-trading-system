"""
ml/ml_advisor.py — Phase 3C: MLAdvisor (CEO Agent integration)

Flow per spec:
  Signal → ConfidenceEngine → MLAdvisor → CEO Agent → RiskEngine → Execution

MLAdvisor MAY:
  - increase/decrease confidence
  - recommend SKIP (sets decision.action = "WAIT" and adds a block reason)

MLAdvisor CANNOT:
  - place orders
  - change position size
  - bypass RiskEngine
  - run if no model is available (fail-open: returns decision unchanged)
"""
from __future__ import annotations
import threading
from datetime import datetime, timezone
from utils.logger import get_logger
logger = get_logger(__name__)

# How much MLAdvisor can move confidence in either direction (guard-rails)
MAX_CONFIDENCE_BOOST  = 10.0   # percentage points
MAX_CONFIDENCE_REDUCE = 20.0   # percentage points


class MLAdvisor:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_prediction: dict | None = None
        self._calibrator = None
        self._calibrator_loaded = False

    def _load_calibrator(self) -> None:
        if not self._calibrator_loaded:
            try:
                from ml.model_registry import get_model_registry
                self._calibrator = get_model_registry().load_active("confidence_calibrator")
                self._calibrator_loaded = True
            except Exception as exc:
                logger.debug(f"MLAdvisor: calibrator load failed: {exc}")
                self._calibrator_loaded = True

    def reload(self) -> None:
        """Force model reload (called by learning_mode after promotion)."""
        self._calibrator_loaded = False
        self._calibrator = None
        from ml.meta_label import get_meta_label_filter
        get_meta_label_filter().reload()

    def advise(self, decision, market_context: dict) -> object:
        """
        Apply ML advisory to a ConfidenceResult-like decision object.
        Returns the (possibly modified) decision — same object type, same
        public API, never raises. If models are unavailable, returns
        decision unchanged so the system behaves exactly as it did without ML.
        """
        if decision is None:
            return decision

        if decision.action not in ("LONG", "SHORT"):
            return decision   # WAIT decisions — nothing to advise on

        try:
            self._load_calibrator()

            # Build the feature vector for the predictor from current context
            from research.trade_snapshot import build_feature_vector
            features = build_feature_vector(
                mission=None,
                trade_row={
                    "direction": decision.action,
                    "entry_price": getattr(decision, "entry_price", 0.0),
                    "stop_loss":   getattr(decision, "stop_loss",   0.0),
                    "take_profit": getattr(decision, "take_profit", 0.0),
                },
                market_context=market_context,
                intelligence=None,
            )
            features["confidence"] = float(getattr(decision, "confidence", 0.0))

            # 1. Meta-label: TRADE or SKIP?
            from ml.meta_label import get_meta_label_filter
            label, outcome_prob = get_meta_label_filter().evaluate(features)

            # 2. Calibrated confidence
            raw_conf = float(getattr(decision, "confidence", 0.0))
            from ml.confidence_calibrator import calibrate_confidence
            cal_conf = calibrate_confidence(raw_conf, self._calibrator)

            # 3. Apply to decision
            original_conf  = raw_conf
            original_action = decision.action

            if label == "SKIP":
                # ML recommends skipping — set to WAIT and add block reason
                decision.action    = "WAIT"
                decision.blocked   = True
                decision.block_reasons = list(getattr(decision,"block_reasons",[]) or []) + [
                    f"MLAdvisor:SKIP (meta_label outcome_prob={outcome_prob:.1f}%)"
                ]
                logger.info(f"MLAdvisor: SKIP recommended "
                            f"(outcome_prob={outcome_prob:.1f}%)")
            else:
                # Calibrate confidence — guard-railed so ML can't override large
                delta = cal_conf - raw_conf
                delta = max(-MAX_CONFIDENCE_REDUCE, min(MAX_CONFIDENCE_BOOST, delta))
                decision.confidence = float(max(0.0, min(100.0, raw_conf + delta)))
                if abs(delta) > 0.5:
                    logger.info(f"MLAdvisor: confidence {raw_conf:.1f}% → "
                                f"{decision.confidence:.1f}% (delta={delta:+.1f})")

            # Log prediction for /api/ml/status and for ml_predictions table
            pred_record = {
                "timestamp":            datetime.now(timezone.utc).isoformat(),
                "original_action":      original_action,
                "label":                label,
                "outcome_probability":  outcome_prob,
                "raw_confidence":       original_conf,
                "calibrated_confidence": getattr(decision, "confidence", original_conf),
            }
            with self._lock:
                self._last_prediction = pred_record

            self._persist_prediction(pred_record, decision)

        except Exception as exc:
            logger.error(f"MLAdvisor.advise failed (returning decision unchanged): {exc}",
                         exc_info=True)

        return decision

    def _persist_prediction(self, record: dict, decision) -> None:
        try:
            from database.db import ManagedConn, get_db_path
            with ManagedConn(get_db_path()) as c:
                c.execute(
                    """INSERT INTO ml_predictions
                       (timestamp,model_type,model_version,raw_confidence,
                        calibrated_confidence,meta_label,outcome_probability)
                       VALUES (?,?,?,?,?,?,?)""",
                    (record["timestamp"], "ml_advisor", "active",
                     record["raw_confidence"], record["calibrated_confidence"],
                     record["label"], record["outcome_probability"]),
                )
                c.commit()
        except Exception as exc:
            logger.debug(f"MLAdvisor._persist_prediction failed: {exc}")

    def get_last_prediction(self) -> dict | None:
        with self._lock:
            return dict(self._last_prediction) if self._last_prediction else None

    def status(self) -> dict:
        from ml.model_registry import get_model_registry
        try:
            reg = get_model_registry()
            meta = reg.get_active("meta_label")
            cal  = reg.get_active("confidence_calibrator")
            pred = reg.get_active("outcome_predictor")
        except Exception:
            meta = cal = pred = None
        return {
            "meta_label_active":            meta is not None,
            "calibrator_active":            cal  is not None,
            "outcome_predictor_active":     pred is not None,
            "last_prediction":              self.get_last_prediction(),
            "timestamp":                    datetime.now(timezone.utc).isoformat(),
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_advisor: MLAdvisor | None = None
_advisor_lock = threading.Lock()


def get_ml_advisor() -> MLAdvisor:
    global _advisor
    if _advisor is None:
        with _advisor_lock:
            if _advisor is None:
                _advisor = MLAdvisor()
    return _advisor


def reset_ml_advisor() -> MLAdvisor:
    global _advisor
    with _advisor_lock:
        _advisor = MLAdvisor()
    return _advisor
