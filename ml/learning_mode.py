"""
ml/learning_mode.py — Phase 3C: Nightly retrain + safe promotion

Behavior (per spec):
  1. Export training DataFrame from FeatureStore
  2. Train meta-label model
  3. Validate against held-out set
  4. Promote ONLY IF: Win Rate↑ AND Profit Factor↑ AND Drawdown not worse
  5. Never auto-promote a failing model
  6. Reload MLAdvisor on promotion
"""
from __future__ import annotations
from datetime import datetime, timezone
from utils.logger import get_logger
logger = get_logger(__name__)


def run_nightly_retrain(min_rows: int = 50, symbol: str | None = None) -> dict:
    """
    Full retrain + conditional promotion cycle.
    Safe to call from a scheduler (never raises — all errors logged and
    returned in the result dict so the caller can decide what to do).
    """
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "skipped",
        "rows_available": 0,
        "meta_label": {"trained": False, "promoted": False, "reason": ""},
        "outcome_predictor": {"trained": False, "promoted": False, "reason": ""},
    }

    try:
        from research.dataset_builder import get_dataset_builder
        builder = get_dataset_builder()
        df = builder.export_training_dataframe(min_rows=min_rows, symbol=symbol)
        result["rows_available"] = builder.row_count(labelled_only=True)

        if df is None:
            result["status"] = "insufficient_data"
            result["meta_label"]["reason"] = f"need >={min_rows} labelled rows"
            logger.info(f"LearningMode: insufficient data ({result['rows_available']} rows)")
            return result

        result["status"] = "running"
        from ml.model_registry import get_model_registry
        reg = get_model_registry()

        # ── Meta-label model ──────────────────────────────────────────────
        from ml.trainer import train_meta_label
        train_result = train_meta_label(df)
        if train_result is None:
            result["meta_label"]["reason"] = "training failed"
        else:
            model, metrics = train_result
            result["meta_label"]["trained"] = True
            if reg.should_promote(metrics, "meta_label"):
                model_id = reg.register(
                    "meta_label", model, "xgboost_or_gbm",
                    int(metrics.get("training_rows", 0)), metrics,
                    notes="auto-promoted by learning_mode",
                )
                reg.promote(model_id, "meta_label")
                result["meta_label"]["promoted"] = True
                result["meta_label"]["reason"] = (
                    f"promoted #{model_id} "
                    f"wr={metrics.get('win_rate',0):.3f} "
                    f"pf={metrics.get('profit_factor',0):.3f}"
                )
                # Reload advisor so it picks up the new model immediately
                try:
                    from ml.ml_advisor import get_ml_advisor
                    get_ml_advisor().reload()
                except Exception:
                    pass
                logger.info(f"LearningMode: meta_label promoted #{model_id}")
            else:
                result["meta_label"]["reason"] = "metrics did not beat current model"
                logger.info("LearningMode: meta_label trained but not promoted (metrics worse)")

        # ── Outcome predictor ─────────────────────────────────────────────
        from ml.trainer import train_outcome_predictor
        op_result = train_outcome_predictor(df)
        if op_result is None:
            result["outcome_predictor"]["reason"] = "training failed"
        else:
            op_model, op_metrics = op_result
            result["outcome_predictor"]["trained"] = True
            if reg.should_promote(op_metrics, "outcome_predictor"):
                op_id = reg.register(
                    "outcome_predictor", op_model, "logistic_regression",
                    int(op_metrics.get("training_rows", 0)), op_metrics,
                )
                reg.promote(op_id, "outcome_predictor")
                result["outcome_predictor"]["promoted"] = True
                result["outcome_predictor"]["reason"] = f"promoted #{op_id}"
            else:
                result["outcome_predictor"]["reason"] = "metrics did not beat current"

        result["status"] = "completed"
        logger.info(f"LearningMode: nightly retrain done | "
                    f"meta_label_promoted={result['meta_label']['promoted']} "
                    f"op_promoted={result['outcome_predictor']['promoted']}")

    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        logger.error(f"run_nightly_retrain failed: {exc}", exc_info=True)

    return result
