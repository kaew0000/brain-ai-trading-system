"""ml/meta_label.py — Phase 3C: MetaLabelFilter wraps model + predictor"""
from __future__ import annotations
from utils.logger import get_logger
logger = get_logger(__name__)


class MetaLabelFilter:
    """
    Thin wrapper: loads the active meta-label model from ModelRegistry and
    exposes a single evaluate() call for MLAdvisor to use each cycle.

    ML cannot place orders. It can only return TRADE / SKIP.
    """

    def __init__(self) -> None:
        self._model = None
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            try:
                from ml.model_registry import get_model_registry
                self._model = get_model_registry().load_active("meta_label")
                self._loaded = True
                status = "loaded" if self._model else "no_active_model"
                logger.info(f"MetaLabelFilter: {status}")
            except Exception as exc:
                logger.debug(f"MetaLabelFilter load failed: {exc}")
                self._loaded = True   # mark loaded so we don't retry every cycle

    def reload(self) -> None:
        """Force reload on next call (e.g. after learning_mode promotes a new model)."""
        self._loaded = False
        self._model = None

    def evaluate(self, features: dict) -> tuple[str, float]:
        """
        Returns (label, probability): label is "TRADE" or "SKIP",
        probability is the model's raw score (0-100).
        """
        self._ensure_loaded()
        from ml.predictor import predict_meta_label, predict_outcome_probability
        label = predict_meta_label(self._model, features)
        prob  = predict_outcome_probability(self._model, features)
        return label, prob


_filter: MetaLabelFilter | None = None

def get_meta_label_filter() -> MetaLabelFilter:
    global _filter
    if _filter is None:
        _filter = MetaLabelFilter()
    return _filter


def reset_meta_label_filter() -> MetaLabelFilter:
    global _filter
    _filter = MetaLabelFilter()
    return _filter
