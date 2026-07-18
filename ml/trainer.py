"""ml/trainer.py — Phase 3C: Train meta-label + outcome predictor models"""
from __future__ import annotations
from typing import Optional
import pandas as pd
from utils.logger import get_logger
logger = get_logger(__name__)

FEATURE_COLS = [
    "direction_enc","confidence","funding","open_interest","oi_delta",
    "liquidation_signal","fear_greed","regime_enc","volatility","atr",
    "smc_score","volume_score",
]

def _validate_df(df: pd.DataFrame) -> bool:
    if df is None or len(df) < 30: return False
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing: logger.warning(f"Trainer: missing columns {missing}"); return False
    return True

def train_meta_label(df: pd.DataFrame) -> Optional[tuple]:
    """
    Binary classifier: should this signal be TRADE (1) or SKIP (0)?
    Priority 1 per spec. Uses XGBoost with sklearn fallback.
    Returns (model, metrics) or None.
    """
    if not _validate_df(df) or "result" not in df.columns: return None
    try:
        X = df[FEATURE_COLS].fillna(0).astype(float)
        y = df["result"].astype(float)
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score
        X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
        try:
            from xgboost import XGBClassifier
            model = XGBClassifier(n_estimators=100, max_depth=4, learning_rate=0.1,
                                   use_label_encoder=False, eval_metric="logloss",
                                   random_state=42, verbosity=0)
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(n_estimators=100, max_depth=4, random_state=42)
        model.fit(X_tr, y_tr)
        preds = model.predict(X_val)
        acc = accuracy_score(y_val, preds)
        wins = float(y_val.sum()); total = float(len(y_val))
        win_rate = wins / total if total > 0 else 0.0
        pnl_col = df.get("pnl", pd.Series(dtype=float))
        if "pnl" in df.columns and len(df) > 0:
            wins_pnl = df.loc[df["result"]==1.0, "pnl"].sum() if "pnl" in df else 0
            loss_pnl = abs(df.loc[df["result"]==0.0, "pnl"].sum()) if "pnl" in df else 1
            pf = wins_pnl / loss_pnl if loss_pnl > 0 else 0.0
        else:
            pf = 0.0
        fi = {}
        if hasattr(model,"feature_importances_"):
            fi = dict(zip(FEATURE_COLS, model.feature_importances_.tolist()))
        metrics = {"accuracy": acc, "win_rate": win_rate, "profit_factor": pf,
                   "max_drawdown": 0.0, "training_rows": len(X_tr),
                   "validation_rows": len(X_val), "feature_importance": fi}
        logger.info(f"MetaLabel trained: acc={acc:.3f} wr={win_rate:.3f}")
        return model, metrics
    except Exception as exc:
        logger.error(f"train_meta_label failed: {exc}", exc_info=True)
        return None

def train_outcome_predictor(df: pd.DataFrame) -> Optional[tuple]:
    """
    Regression/probability model: P(TP before SL) as 0-100.
    Priority 3 per spec.
    """
    if not _validate_df(df) or "result" not in df.columns: return None
    try:
        X = df[FEATURE_COLS].fillna(0).astype(float)
        y = df["result"].astype(float)
        from sklearn.model_selection import train_test_split
        from sklearn.linear_model import LogisticRegression
        X_tr, X_val, y_tr, y_val = train_test_split(X, y, test_size=0.2, random_state=42)
        model = LogisticRegression(max_iter=500, random_state=42)
        model.fit(X_tr, y_tr)
        probs = model.predict_proba(X_val)[:,1]
        from sklearn.metrics import roc_auc_score
        try: auc = roc_auc_score(y_val, probs)
        except Exception: auc = 0.5
        win_rate = float(y_val.mean()) if len(y_val) > 0 else 0.0
        metrics = {"auc": auc, "win_rate": win_rate, "profit_factor": 0.0,
                   "max_drawdown": 0.0, "training_rows": len(X_tr), "validation_rows": len(X_val)}
        logger.info(f"OutcomePredictor trained: auc={auc:.3f}")
        return model, metrics
    except Exception as exc:
        logger.error(f"train_outcome_predictor failed: {exc}", exc_info=True)
        return None
