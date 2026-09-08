"""
ml/learning_mode.py — Phase 3C: Nightly retrain + safe promotion
V16 §58: gated promotion via the governance layer (Phase 2)

Behavior (per spec):
  1. Export training DataFrame from FeatureStore
  2. Train meta-label model
  3. Validate against held-out set
  4. Promote ONLY IF: Win Rate↑ AND Profit Factor↑ AND Drawdown not worse
  5. Never auto-promote a failing model
  6. Reload MLAdvisor on promotion

§58 addition: "promote" above no longer always means "make it active
immediately". When settings.MODEL_PROMOTION_REQUIRES_APPROVAL is True
(the default), a model that beats should_promote()'s gate is registered
as a candidate (saved, but left inactive) and a governance
UpdateProposal is created for a human to review instead — see
governance/__init__.py and docs/architecture.md §58 for the full
rationale. Only when MODEL_PROMOTION_REQUIRES_APPROVAL is explicitly
set False does this module still promote unattended, exactly as it did
before §58.
"""
from __future__ import annotations
from datetime import datetime, timezone
from config.settings import settings
from utils.logger import get_logger
logger = get_logger(__name__)


def _register_and_gate_promotion(
    reg, model_type: str, model_obj, algorithm: str, metrics: dict,
    notes: str, builder, symbol: str | None,
) -> tuple[bool, str, int | None]:
    """Only call this once reg.should_promote(metrics, model_type) is
    already True — mirrors the pre-§58 call pattern exactly: register()
    only ever runs for a model that already beat the promotion gate.

    Registers the model (always saved to disk/DB as a candidate,
    active=0), then either promotes it immediately
    (MODEL_PROMOTION_REQUIRES_APPROVAL=False) or creates a pending
    governance proposal for a human to review (True, the default).

    Returns (promoted, reason, proposal_id) — proposal_id is None
    whenever promoted is True (nothing pending) or a proposal couldn't
    be created.
    """
    model_id = reg.register(
        model_type, model_obj, algorithm,
        int(metrics.get("training_rows", 0)), metrics, notes=notes,
    )

    if not settings.MODEL_PROMOTION_REQUIRES_APPROVAL:
        reg.promote(model_id, model_type)
        if model_type == "meta_label":
            try:
                from ml.ml_advisor import get_ml_advisor
                get_ml_advisor().reload()
            except Exception:
                pass
        return True, (
            f"promoted #{model_id} "
            f"wr={metrics.get('win_rate', 0):.3f} "
            f"pf={metrics.get('profit_factor', 0):.3f}"
        ), None

    try:
        from governance.proposal_store import get_proposal_store
        from governance.update_proposal import UpdateProposal
        from agents.update_review_agent import get_update_review_agent

        before = reg.get_active(model_type) or {}
        proposal_metrics = dict(metrics)
        proposal_metrics["model_id"] = model_id
        proposal_metrics["model_type"] = model_type
        if builder is not None:
            lane_breakdown = builder.get_lane_breakdown(symbol=symbol)
            if lane_breakdown:
                proposal_metrics["training_rows_by_lane"] = lane_breakdown

        proposal = UpdateProposal(
            proposal_type="model_promotion",
            target=f"model_registry.{model_type}",
            before=before,
            after=metrics,
            rationale=(
                f"Nightly retrain: {model_type} #{model_id} beat "
                f"should_promote()'s gate (win_rate "
                f"{before.get('win_rate', 0):.3f}->{metrics.get('win_rate', 0):.3f}, "
                f"profit_factor {before.get('profit_factor', 0):.3f}->"
                f"{metrics.get('profit_factor', 0):.3f}, max_drawdown "
                f"{before.get('max_drawdown', 0):.3f}->{metrics.get('max_drawdown', 0):.3f})."
            ),
            metrics=proposal_metrics,
            generated_by="ml.learning_mode.run_nightly_retrain",
        )
        store = get_proposal_store()
        proposal_id = store.create(proposal)
        proposal.id = proposal_id

        review = get_update_review_agent().review(proposal)
        store.set_review(proposal_id, review.verdict, review.reasoning, review.score)

        logger.critical(
            f"GOVERNANCE: {model_type} #{model_id} registered but NOT "
            f"promoted -- pending human approval as proposal #{proposal_id} "
            f"(review: {review.verdict or 'unscored'}, score={review.score:.2f})"
        )
        return False, (
            f"registered #{model_id} but not promoted -- pending human "
            f"approval as proposal #{proposal_id} "
            f"(review: {review.verdict or 'unscored'})"
        ), proposal_id
    except Exception as exc:
        # A failure to create the proposal must NOT fall back to
        # promoting unattended — that would silently defeat the whole
        # point of MODEL_PROMOTION_REQUIRES_APPROVAL. The model stays
        # registered (inactive) either way; whoever notices this error
        # can create/approve a proposal manually.
        logger.error(
            f"LearningMode: failed to create governance proposal for "
            f"{model_type} #{model_id} -- left un-promoted, NOT falling "
            f"back to auto-promote: {exc}", exc_info=True,
        )
        return False, (
            f"registered #{model_id} but governance proposal creation "
            f"failed ({exc}) -- left un-promoted, needs manual review"
        ), None


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
                promoted, reason, proposal_id = _register_and_gate_promotion(
                    reg, "meta_label", model, "xgboost_or_gbm", metrics,
                    "auto-promoted by learning_mode", builder, symbol,
                )
                result["meta_label"]["promoted"] = promoted
                result["meta_label"]["reason"] = reason
                if proposal_id is not None:
                    result["meta_label"]["proposal_id"] = proposal_id
                logger.info(f"LearningMode: meta_label {reason}")
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
                promoted, reason, proposal_id = _register_and_gate_promotion(
                    reg, "outcome_predictor", op_model, "logistic_regression",
                    op_metrics, "", builder, symbol,
                )
                result["outcome_predictor"]["promoted"] = promoted
                result["outcome_predictor"]["reason"] = reason
                if proposal_id is not None:
                    result["outcome_predictor"]["proposal_id"] = proposal_id
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
