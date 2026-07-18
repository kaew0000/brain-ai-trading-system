"""ml/model_registry.py — Persist & load trained models with promotion gating"""
from __future__ import annotations
import json
import os
import pickle
import threading
from datetime import datetime, timezone
from typing import Optional, Any
from database.db import ManagedConn, get_db_path
from utils.logger import get_logger
logger = get_logger(__name__)

MODEL_TYPES = ("meta_label", "confidence_calibrator", "outcome_predictor")
_MODELS_DIR = "ml_models"

class ModelRegistry:
    def __init__(self, db_path: Optional[str]=None, models_dir: str=_MODELS_DIR) -> None:
        self.db_path = db_path or get_db_path()
        self.models_dir = models_dir
        os.makedirs(models_dir, exist_ok=True)
        self._lock = threading.Lock()

    def _conn(self) -> ManagedConn:
        return ManagedConn(self.db_path)

    def register(self, model_type: str, model_obj: Any, algorithm: str,
                 training_rows: int, metrics: dict, notes: str="") -> int:
        version = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.models_dir, f"{model_type}_{version}.pkl")
        with open(path,"wb") as f: pickle.dump(model_obj, f)
        fi = metrics.get("feature_importance",{})
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO model_registry
                   (created_at,model_type,version,active,algorithm,training_rows,
                    win_rate,profit_factor,max_drawdown,feature_importance,metrics_json,model_path,notes)
                   VALUES (?,?,?,0,?,?,?,?,?,?,?,?,?)""",
                (datetime.now(timezone.utc).isoformat(), model_type, version, algorithm,
                 training_rows, float(metrics.get("win_rate",0)),
                 float(metrics.get("profit_factor",0)), float(metrics.get("max_drawdown",0)),
                 json.dumps(fi), json.dumps(metrics), path, notes))
            c.commit()
            return cur.lastrowid

    def promote(self, model_id: int, model_type: str) -> bool:
        """Promote model_id — deactivate current active, activate new."""
        with self._lock:
            with self._conn() as c:
                c.execute("UPDATE model_registry SET active=0 WHERE model_type=?", (model_type,))
                c.execute("UPDATE model_registry SET active=1 WHERE id=?", (model_id,))
                c.commit()
        logger.info(f"ModelRegistry: promoted #{model_id} ({model_type})")
        return True

    def should_promote(self, new_metrics: dict, model_type: str) -> bool:
        """Promotion rules: Win Rate↑ AND Profit Factor↑ AND Drawdown not worse."""
        current = self.get_active(model_type)
        if current is None: return True
        nwr = float(new_metrics.get("win_rate",0))
        npf = float(new_metrics.get("profit_factor",0))
        ndd = float(new_metrics.get("max_drawdown",0))
        return (nwr > float(current.get("win_rate",0)) and
                npf > float(current.get("profit_factor",0)) and
                ndd <= float(current.get("max_drawdown",999)))

    def get_active(self, model_type: str) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM model_registry WHERE model_type=? AND active=1 ORDER BY id DESC LIMIT 1",
                (model_type,)).fetchone()
        return dict(row) if row else None

    def load_active(self, model_type: str) -> Optional[Any]:
        meta = self.get_active(model_type)
        if meta is None: return None
        path = meta.get("model_path","")
        if not path or not os.path.exists(path): return None
        try:
            with open(path,"rb") as f: return pickle.load(f)
        except Exception as exc:
            logger.error(f"ModelRegistry.load_active({model_type}) failed: {exc}")
            return None

    def list_models(self, model_type: Optional[str]=None, limit: int=50) -> list[dict]:
        with self._conn() as c:
            if model_type:
                rows = c.execute(
                    "SELECT * FROM model_registry WHERE model_type=? ORDER BY id DESC LIMIT ?",
                    (model_type, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM model_registry ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

_registry: Optional[ModelRegistry] = None
_registry_lock = threading.Lock()

def get_model_registry() -> ModelRegistry:
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None: _registry = ModelRegistry()
    return _registry

def reset_model_registry(db_path: Optional[str]=None) -> ModelRegistry:
    global _registry
    with _registry_lock: _registry = ModelRegistry(db_path=db_path)
    return _registry
