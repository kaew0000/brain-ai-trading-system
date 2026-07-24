"""research/dataset_builder.py — Phase 3B: orchestration + ML export"""
from __future__ import annotations
import threading
import pandas as pd
from research.feature_store import FeatureStore
from research.trade_snapshot import build_feature_vector, build_outcome
from utils.logger import get_logger
logger = get_logger(__name__)

REGIME_ENCODING = {"":0,"RANGE":1,"TREND":2,"SQUEEZE":3,"HIGH_VOLATILITY":4,
                   "LOW_VOLATILITY":5,"BREAKOUT":6,"ACCUMULATION":7}
DIRECTION_ENCODING = {"":0,"SHORT":-1,"LONG":1}

class DatasetBuilder:
    def __init__(self, store: FeatureStore | None=None) -> None:
        self._store = store or FeatureStore()
        self._lock = threading.Lock()

    def capture_closed_mission(self, mission=None, trade_row: dict | None=None,
                                market_context: dict | None=None,
                                intelligence: dict | None=None) -> int | None:
        try:
            tr = trade_row or {}
            features = build_feature_vector(mission, tr, market_context, intelligence)
            result, pnl, ht = build_outcome(tr)
            mid = getattr(mission,"id",None) if mission is not None else None
            tid = tr.get("id"); sym = tr.get("symbol") or (mission.symbol if mission else "BTCUSDT")
            with self._lock:
                row_id = self._store.save_row(features, mission_id=mid, trade_id=tid, symbol=sym)
                if result is not None:
                    self._store.update_outcome(row_id, result, pnl, ht)
            logger.info(f"DatasetBuilder: captured row #{row_id} (mission={mid} trade={tid} labelled={result is not None})")
            return row_id
        except Exception as exc:
            logger.error(f"DatasetBuilder.capture_closed_mission failed: {exc}", exc_info=True)
            return None

    def export_training_dataframe(self, min_rows: int=30, limit: int=10_000,
                                   symbol: str | None=None) -> pd.DataFrame | None:
        try:
            rows = self._store.get_training_rows(limit=limit, symbol=symbol)
            if len(rows) < min_rows:
                logger.info(f"DatasetBuilder: only {len(rows)} labelled rows (need >={min_rows}) — skip")
                return None
            df = pd.DataFrame(rows)
            df["direction_enc"] = df["direction"].map(DIRECTION_ENCODING).fillna(0)
            df["regime_enc"] = df["regime"].map(REGIME_ENCODING).fillna(0)
            keep = ["direction_enc","confidence","funding","open_interest","oi_delta",
                    "liquidation_signal","fear_greed","regime_enc","volatility","atr",
                    "smc_score","volume_score","result","pnl","holding_time_s","id","trade_id"]
            return df[[c for c in keep if c in df.columns]].copy()
        except Exception as exc:
            logger.error(f"export_training_dataframe failed: {exc}", exc_info=True)
            return None

    def row_count(self, labelled_only: bool=True) -> int:
        try: return self._store.count(labelled_only=labelled_only)
        except Exception: return 0

_db: DatasetBuilder | None = None
_db_lock = threading.Lock()

def get_dataset_builder() -> DatasetBuilder:
    global _db
    if _db is None:
        with _db_lock:
            if _db is None: _db = DatasetBuilder()
    return _db

def reset_dataset_builder(store: FeatureStore | None=None) -> DatasetBuilder:
    global _db
    with _db_lock: _db = DatasetBuilder(store=store)
    return _db
