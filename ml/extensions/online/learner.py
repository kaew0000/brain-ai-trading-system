"""
OnlineLearner - River Integration for Brain AI Trading System
===============================================================

Provides real-time incremental learning capabilities:
    - Online classification (buy/sell/hold signals)
    - Online regression (price/return prediction)
    - Adaptive feature scaling
    - Concept drift detection
    - Model persistence

Usage:
    learner = OnlineLearner(task="classification")
    learner.learn(x_features, y_label)  # Update model one sample at a time
    prediction = learner.predict(x_features)  # Real-time prediction
"""

import os
import json
import pickle
import logging
from typing import Dict, List, Optional, Union, Any, Literal
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import deque
from datetime import datetime

import numpy as np

# River imports
from river import (
    compose,
    preprocessing,
    linear_model,
    tree,
    ensemble,
    metrics as river_metrics,
    drift,
    stats,
)
from river.drift import ADWIN

logger = logging.getLogger(__name__)


@dataclass
class OnlineModelConfig:
    """Configuration for online learning model."""
    task: Literal["classification", "regression"] = "classification"
    model_type: Literal["logistic", "hoeffding_tree", "adaptive_random_forest"] = "logistic"
    feature_scaler: Literal["standard", "minmax", "none"] = "standard"
    drift_detector: bool = True
    drift_threshold: float = 0.002
    window_size: int = 1000
    learning_rate: float = 0.01
    l2_reg: float = 0.0


class ConceptDriftTracker:
    """
    Tracks concept drift in market regime using ADWIN.

    When drift is detected, triggers model adaptation or retraining signal.
    """

    def __init__(self, delta: float = 0.002):
        self.adwin = ADWIN(delta=delta)
        self.drift_detected_count = 0
        self.last_drift_time = None
        self.drift_history = deque(maxlen=100)

    def update(self, prediction_error: float) -> bool:
        """
        Update drift detector with latest prediction error.

        Args:
            prediction_error: Absolute prediction error

        Returns:
            True if drift detected, False otherwise
        """
        self.adwin.update(prediction_error)

        if self.adwin.drift_detected:
            self.drift_detected_count += 1
            self.last_drift_time = datetime.now()
            self.drift_history.append({
                "time": self.last_drift_time.isoformat(),
                "error": prediction_error,
                "window_size": self.adwin.width,
            })
            logger.warning(
                f"Concept drift detected! Count: {self.drift_detected_count}, "
                f"Error: {prediction_error:.4f}"
            )
            return True

        return False

    def get_stats(self) -> Dict[str, Any]:
        """Get drift detection statistics."""
        return {
            "drift_detected_count": self.drift_detected_count,
            "last_drift_time": self.last_drift_time.isoformat() if self.last_drift_time else None,
            "current_window_size": self.adwin.width,
            "drift_history": list(self.drift_history),
        }


class OnlineLearner:
    """
    Main online learning adapter using River.

    Supports both classification (direction prediction) and regression
    (return prediction) tasks with automatic feature scaling and
    concept drift detection.
    """

    def __init__(
        self,
        config: Optional[OnlineModelConfig] = None,
        model_dir: str = "models/online",
        n_classes: int = 3,  # buy, sell, hold
    ):
        """
        Initialize online learner.

        Args:
            config: Model configuration
            model_dir: Directory to save/load models
            n_classes: Number of classes for classification
        """
        self.config = config or OnlineModelConfig()
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.n_classes = n_classes

        # Build model pipeline
        self.model = self._build_model()

        # Metrics tracking
        self.metrics = {
            "accuracy": river_metrics.Accuracy(),
            "precision": river_metrics.Precision(),
            "recall": river_metrics.Recall(),
            "f1": river_metrics.F1(),
            "mae": river_metrics.MAE(),
            "rmse": river_metrics.RMSE(),
        }

        # Concept drift tracking
        self.drift_tracker = ConceptDriftTracker(delta=self.config.drift_threshold)

        # Experience replay buffer for catastrophic forgetting prevention
        self.replay_buffer = deque(maxlen=self.config.window_size)

        # Training statistics
        self.n_samples = 0
        self.n_drift_adaptations = 0
        self.learning_history = deque(maxlen=1000)

        logger.info(f"Initialized OnlineLearner: {self.config.task} - {self.config.model_type}")

    def _build_model(self):
        """Build the River model pipeline."""
        # Feature preprocessing
        preprocessor = compose.Pipeline()

        if self.config.feature_scaler == "standard":
            preprocessor |= preprocessing.StandardScaler()
        elif self.config.feature_scaler == "minmax":
            preprocessor |= preprocessing.MinMaxScaler()

        # Model selection
        if self.config.task == "classification":
            if self.config.model_type == "logistic":
                model = linear_model.SoftmaxRegression(
                    optimizer=linear_model.optimizers.SGD(self.config.learning_rate),
                    l2=self.config.l2_reg,
                )
            elif self.config.model_type == "hoeffding_tree":
                model = tree.HoeffdingTreeClassifier()
            elif self.config.model_type == "adaptive_random_forest":
                model = ensemble.AdaptiveRandomForestClassifier()
            else:
                raise ValueError(f"Unknown model type: {self.config.model_type}")

        else:  # regression
            if self.config.model_type == "logistic":
                model = linear_model.LinearRegression(
                    optimizer=linear_model.optimizers.SGD(self.config.learning_rate),
                    l2=self.config.l2_reg,
                )
            elif self.config.model_type == "hoeffding_tree":
                model = tree.HoeffdingTreeRegressor()
            elif self.config.model_type == "adaptive_random_forest":
                model = ensemble.AdaptiveRandomForestRegressor()
            else:
                raise ValueError(f"Unknown model type: {self.config.model_type}")

        preprocessor |= model
        return preprocessor

    def learn(self, x: Dict[str, float], y: Union[int, float]) -> Dict[str, Any]:
        """
        Learn from one sample (online update).

        Args:
            x: Feature dictionary {feature_name: value}
            y: Target label (int for classification, float for regression)

        Returns:
            Dictionary with prediction, metrics, and drift status
        """
        # Make prediction before learning (for metrics)
        y_pred = self.model.predict_one(x)

        # Calculate error for drift detection
        if self.config.task == "classification":
            error = 0.0 if y_pred == y else 1.0
        else:
            error = abs(y_pred - y) if y_pred is not None else 1.0

        # Check for concept drift
        drift_detected = self.drift_tracker.update(error)

        if drift_detected:
            self.n_drift_adaptations += 1
            # Replay recent samples to adapt faster
            self._replay_buffer()

        # Learn from current sample
        self.model.learn_one(x, y)

        # Add to replay buffer
        self.replay_buffer.append((x, y))

        # Update metrics
        self._update_metrics(y, y_pred)

        self.n_samples += 1

        # Log learning history
        self.learning_history.append({
            "timestamp": datetime.now().isoformat(),
            "true": y,
            "pred": y_pred,
            "error": error,
            "drift": drift_detected,
        })

        return {
            "prediction": y_pred,
            "error": error,
            "drift_detected": drift_detected,
            "n_samples": self.n_samples,
        }

    def predict(self, x: Dict[str, float]) -> Union[int, float]:
        """
        Make prediction on single sample.

        Args:
            x: Feature dictionary

        Returns:
            Predicted label/value
        """
        return self.model.predict_one(x)

    def predict_proba(self, x: Dict[str, float]) -> Dict[str, float]:
        """
        Get prediction probabilities (classification only).

        Args:
            x: Feature dictionary

        Returns:
            Dictionary of class probabilities
        """
        if self.config.task != "classification":
            raise ValueError("predict_proba only available for classification")

        proba = self.model.predict_proba_one(x)
        return dict(proba) if proba else {}

    def _update_metrics(self, y_true, y_pred):
        """Update online metrics."""
        if y_pred is None:
            return

        if self.config.task == "classification":
            self.metrics["accuracy"].update(y_true, y_pred)
            self.metrics["precision"].update(y_true, y_pred)
            self.metrics["recall"].update(y_true, y_pred)
            self.metrics["f1"].update(y_true, y_pred)
        else:
            self.metrics["mae"].update(y_true, y_pred)
            self.metrics["rmse"].update(y_true, y_pred)

    def _replay_buffer(self, n_samples: int = 50):
        """Replay recent samples to prevent catastrophic forgetting."""
        if len(self.replay_buffer) == 0:
            return

        # Sample from buffer (recent samples weighted more)
        samples = list(self.replay_buffer)[-n_samples:]

        for x, y in samples:
            self.model.learn_one(x, y)

        logger.info(f"Replayed {len(samples)} samples from buffer")

    def get_metrics(self) -> Dict[str, float]:
        """Get current performance metrics."""
        metrics_dict = {}

        for name, metric in self.metrics.items():
            try:
                metrics_dict[name] = metric.get()
            except:
                metrics_dict[name] = 0.0

        metrics_dict["n_samples"] = self.n_samples
        metrics_dict["n_drift_adaptations"] = self.n_drift_adaptations

        return metrics_dict

    def save(self, path: Optional[str] = None):
        """Save model to disk."""
        if path is None:
            path = self.model_dir / f"online_model_{datetime.now():%Y%m%d_%H%M%S}.pkl"

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "model": self.model,
            "config": asdict(self.config),
            "n_samples": self.n_samples,
            "n_drift_adaptations": self.n_drift_adaptations,
            "metrics": self.get_metrics(),
            "drift_stats": self.drift_tracker.get_stats(),
        }

        with open(path, "wb") as f:
            pickle.dump(state, f)

        # Also save config as JSON for readability
        with open(path.with_suffix(".json"), "w") as f:
            json.dump(state["config"], f, indent=2, default=str)

        logger.info(f"Model saved to {path}")
        return path

    def load(self, path: str):
        """Load model from disk."""
        with open(path, "rb") as f:
            state = pickle.load(f)

        self.model = state["model"]
        self.config = OnlineModelConfig(**state["config"])
        self.n_samples = state["n_samples"]
        self.n_drift_adaptations = state["n_drift_adaptations"]

        logger.info(f"Model loaded from {path}")

    def get_feature_importance(self, x: Dict[str, float]) -> Dict[str, float]:
        """
        Get feature importance using permutation-like approach.

        Args:
            x: Sample to explain

        Returns:
            Dictionary of feature importances
        """
        base_pred = self.predict(x)
        importances = {}

        for feature, value in x.items():
            # Perturb feature
            x_perturbed = x.copy()
            x_perturbed[feature] = 0  # Zero out
            perturbed_pred = self.predict(x_perturbed)

            # Importance = change in prediction
            if self.config.task == "classification":
                importances[feature] = 1.0 if base_pred != perturbed_pred else 0.0
            else:
                importances[feature] = abs(base_pred - perturbed_pred)

        # Normalize
        total = sum(importances.values())
        if total > 0:
            importances = {k: v / total for k, v in importances.items()}

        return importances


class MultiSymbolOnlineLearner:
    """
    Manages separate online learners for multiple trading symbols.

    Useful when different symbols have different market microstructures
    that require separate models.
    """

    def __init__(
        self,
        symbols: List[str],
        config: Optional[OnlineModelConfig] = None,
        model_dir: str = "models/online",
    ):
        self.symbols = symbols
        self.config = config or OnlineModelConfig()
        self.model_dir = Path(model_dir)

        # Create learner per symbol
        self.learners = {}
        for symbol in symbols:
            symbol_dir = self.model_dir / symbol
            self.learners[symbol] = OnlineLearner(
                config=self.config,
                model_dir=str(symbol_dir),
            )

        logger.info(f"Initialized MultiSymbolOnlineLearner for {len(symbols)} symbols")

    def learn(self, symbol: str, x: Dict[str, float], y: Union[int, float]) -> Dict[str, Any]:
        """Learn for specific symbol."""
        if symbol not in self.learners:
            # Auto-create for new symbol
            self.learners[symbol] = OnlineLearner(
                config=self.config,
                model_dir=str(self.model_dir / symbol),
            )

        return self.learners[symbol].learn(x, y)

    def predict(self, symbol: str, x: Dict[str, float]) -> Union[int, float]:
        """Predict for specific symbol."""
        if symbol not in self.learners:
            raise ValueError(f"No learner for symbol: {symbol}")

        return self.learners[symbol].predict(x)

    def get_all_metrics(self) -> Dict[str, Dict[str, float]]:
        """Get metrics for all symbols."""
        return {
            symbol: learner.get_metrics()
            for symbol, learner in self.learners.items()
        }

    def save_all(self):
        """Save all models."""
        for symbol, learner in self.learners.items():
            learner.save()

    def load_all(self):
        """Load all models from disk."""
        for symbol in self.symbols:
            symbol_dir = self.model_dir / symbol
            model_files = list(symbol_dir.glob("*.pkl"))
            if model_files:
                latest = max(model_files, key=lambda p: p.stat().st_mtime)
                self.learners[symbol].load(str(latest))
