"""
HPOManager - Optuna Integration for Brain AI Trading System
============================================================

Automated hyperparameter optimization for trading strategies:
    - Strategy parameter tuning (lookback, threshold, position size)
    - RL hyperparameter tuning (learning rate, network architecture)
    - Multi-objective optimization (return vs risk vs trades)
    - Distributed optimization support
    - Trial pruning for early stopping

Usage:
    hpo = HPOManager(strategy_fn=my_strategy, backtest_fn=my_backtest)
    best_params = hpo.optimize(n_trials=100, study_name="brain_v16")

    # Use best params
    strategy = my_strategy(**best_params)
"""

import os
import json
import logging
from typing import Dict, List, Optional, Callable, Any, Tuple, Literal
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from functools import partial

import numpy as np

# Optuna imports
import optuna
from optuna.samplers import TPESampler, CmaEsSampler, RandomSampler
from optuna.pruners import MedianPruner, HyperbandPruner
from optuna.visualization import plot_optimization_history, plot_param_importances

# Suppress Optuna logging verbosity
optuna.logging.set_verbosity(optuna.logging.WARNING)

logger = logging.getLogger(__name__)


@dataclass
class HPOConfig:
    """Configuration for hyperparameter optimization."""
    study_name: str = "brain_hpo"
    direction: Literal["maximize", "minimize"] = "maximize"
    n_trials: int = 100
    timeout: Optional[int] = None  # seconds
    n_jobs: int = 1
    sampler: Literal["tpe", "cmaes", "random"] = "tpe"
    pruner: Literal["median", "hyperband", "none"] = "median"
    n_startup_trials: int = 10
    n_warmup_steps: int = 5
    storage: Optional[str] = None  # e.g. "sqlite:///optuna.db"
    seed: Optional[int] = 42


@dataclass
class ParamSpace:
    """
    Define parameter search space for Optuna.

    Example:
        space = ParamSpace()
        space.add_int("lookback", 10, 100)
        space.add_float("threshold", 0.1, 0.9, log=True)
        space.add_categorical("model_type", ["lstm", "gru", "transformer"])
    """

    def __init__(self):
        self.params: List[Dict[str, Any]] = []

    def add_int(self, name: str, low: int, high: int, step: int = 1, log: bool = False):
        """Add integer parameter."""
        self.params.append({
            "name": name,
            "type": "int",
            "low": low,
            "high": high,
            "step": step,
            "log": log,
        })

    def add_float(self, name: str, low: float, high: float, step: Optional[float] = None, log: bool = False):
        """Add float parameter."""
        self.params.append({
            "name": name,
            "type": "float",
            "low": low,
            "high": high,
            "step": step,
            "log": log,
        })

    def add_categorical(self, name: str, choices: List[Any]):
        """Add categorical parameter."""
        self.params.append({
            "name": name,
            "type": "categorical",
            "choices": choices,
        })

    def suggest(self, trial: optuna.Trial) -> Dict[str, Any]:
        """Suggest parameters from trial."""
        params = {}
        for p in self.params:
            if p["type"] == "int":
                params[p["name"]] = trial.suggest_int(
                    p["name"], p["low"], p["high"], step=p.get("step", 1), log=p.get("log", False)
                )
            elif p["type"] == "float":
                params[p["name"]] = trial.suggest_float(
                    p["name"], p["low"], p["high"], step=p.get("step"), log=p.get("log", False)
                )
            elif p["type"] == "categorical":
                params[p["name"]] = trial.suggest_categorical(p["name"], p["choices"])
        return params


class HPOManager:
    """
    Main HPO manager using Optuna.

    Supports:
    - Single-objective optimization (e.g. maximize Sharpe)
    - Multi-objective optimization (e.g. maximize return + minimize drawdown)
    - Distributed optimization across multiple machines
    - Automatic trial pruning
    - Best model persistence
    """

    def __init__(
        self,
        objective_fn: Optional[Callable] = None,
        param_space: Optional[ParamSpace] = None,
        config: Optional[HPOConfig] = None,
        results_dir: str = "hpo_results",
    ):
        """
        Initialize HPO manager.

        Args:
            objective_fn: Function(trial, params) -> float (higher is better)
            param_space: Parameter search space
            config: HPO configuration
            results_dir: Directory to save results
        """
        self.objective_fn = objective_fn
        self.param_space = param_space or ParamSpace()
        self.config = config or HPOConfig()
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.study: Optional[optuna.Study] = None
        self.best_params: Optional[Dict[str, Any]] = None
        self.optimization_history: List[Dict[str, Any]] = []

        logger.info(f"Initialized HPOManager: {self.config.study_name}")

    def _create_study(self) -> optuna.Study:
        """Create Optuna study with configured sampler and pruner."""
        # Sampler
        if self.config.sampler == "tpe":
            sampler = TPESampler(
                n_startup_trials=self.config.n_startup_trials,
                seed=self.config.seed,
            )
        elif self.config.sampler == "cmaes":
            sampler = CmaEsSampler(seed=self.config.seed)
        elif self.config.sampler == "random":
            sampler = RandomSampler(seed=self.config.seed)
        else:
            sampler = TPESampler()

        # Pruner
        if self.config.pruner == "median":
            pruner = MedianPruner(
                n_startup_trials=self.config.n_startup_trials,
                n_warmup_steps=self.config.n_warmup_steps,
            )
        elif self.config.pruner == "hyperband":
            pruner = HyperbandPruner(
                min_resource=1,
                max_resource=self.config.n_trials,
            )
        else:
            pruner = optuna.pruners.NopPruner()

        study = optuna.create_study(
            study_name=self.config.study_name,
            direction=self.config.direction,
            sampler=sampler,
            pruner=pruner,
            storage=self.config.storage,
            load_if_exists=True,
        )

        return study

    def _objective_wrapper(self, trial: optuna.Trial) -> float:
        """Wrapper that handles parameter suggestion and error catching."""
        try:
            # Suggest parameters
            params = self.param_space.suggest(trial)

            # Call user objective function
            if self.objective_fn is None:
                raise ValueError("No objective function provided")

            score = self.objective_fn(trial, params)

            # Log trial
            self.optimization_history.append({
                "trial_number": trial.number,
                "params": params,
                "score": score,
                "timestamp": datetime.now().isoformat(),
            })

            return score

        except Exception as e:
            logger.error(f"Trial {trial.number} failed: {e}")
            raise optuna.TrialPruned()

    def optimize(
        self,
        n_trials: Optional[int] = None,
        timeout: Optional[int] = None,
        show_progress: bool = True,
    ) -> Dict[str, Any]:
        """
        Run hyperparameter optimization.

        Args:
            n_trials: Number of trials (overrides config)
            timeout: Timeout in seconds (overrides config)
            show_progress: Show progress bar

        Returns:
            Dictionary with best_params, best_score, study_stats
        """
        n_trials = n_trials or self.config.n_trials
        timeout = timeout or self.config.timeout

        self.study = self._create_study()

        logger.info(f"Starting optimization: {n_trials} trials, timeout={timeout}s")

        self.study.optimize(
            self._objective_wrapper,
            n_trials=n_trials,
            timeout=timeout,
            n_jobs=self.config.n_jobs,
            show_progress_bar=show_progress,
            catch=(Exception,),
        )

        # Extract results
        self.best_params = self.study.best_params
        best_score = self.study.best_value

        results = {
            "study_name": self.config.study_name,
            "best_params": self.best_params,
            "best_score": best_score,
            "n_trials_completed": len(self.study.trials),
            "n_trials_pruned": len([t for t in self.study.trials if t.state == optuna.trial.TrialState.PRUNED]),
            "optimization_time": sum([t.duration.total_seconds() for t in self.study.trials if t.duration]),
            "timestamp": datetime.now().isoformat(),
        }

        # Save results
        self._save_results(results)

        logger.info(f"Optimization complete. Best score: {best_score:.4f}")
        logger.info(f"Best params: {self.best_params}")

        return results

    def _save_results(self, results: Dict[str, Any]):
        """Save optimization results to disk."""
        # JSON results
        results_path = self.results_dir / f"{self.config.study_name}_results.json"
        with open(results_path, "w") as f:
            json.dump(results, f, indent=2, default=str)

        # Save study for later analysis
        study_path = self.results_dir / f"{self.config.study_name}_study.pkl"
        import joblib
        joblib.dump(self.study, study_path)

        # Save optimization history
        history_path = self.results_dir / f"{self.config.study_name}_history.json"
        with open(history_path, "w") as f:
            json.dump(self.optimization_history, f, indent=2, default=str)

        logger.info(f"Results saved to {self.results_dir}")

    def get_param_importance(self) -> Dict[str, float]:
        """Get parameter importance from completed study."""
        if self.study is None:
            raise ValueError("No study available. Run optimize() first.")

        try:
            importance = optuna.importance.get_param_importances(self.study)
            return dict(importance)
        except Exception as e:
            logger.warning(f"Could not compute param importance: {e}")
            return {}

    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """Get full optimization history."""
        return self.optimization_history

    def plot_history(self, save_path: Optional[str] = None):
        """Plot optimization history (requires plotly)."""
        if self.study is None:
            raise ValueError("No study available")

        fig = plot_optimization_history(self.study)
        if save_path:
            fig.write_image(save_path)
        return fig

    def plot_importance(self, save_path: Optional[str] = None):
        """Plot parameter importance."""
        if self.study is None:
            raise ValueError("No study available")

        fig = plot_param_importances(self.study)
        if save_path:
            fig.write_image(save_path)
        return fig


class StrategyOptimizer:
    """
    Specialized optimizer for trading strategy parameters.

    Pre-built parameter spaces for common strategy types.
    """

    @staticmethod
    def create_momentum_space() -> ParamSpace:
        """Parameter space for momentum strategy."""
        space = ParamSpace()
        space.add_int("lookback", 5, 50)
        space.add_float("threshold", 0.01, 0.1, log=True)
        space.add_float("position_size", 0.05, 0.5)
        space.add_float("stop_loss", 0.01, 0.05)
        space.add_float("take_profit", 0.02, 0.1)
        return space

    @staticmethod
    def create_mean_reversion_space() -> ParamSpace:
        """Parameter space for mean reversion strategy."""
        space = ParamSpace()
        space.add_int("lookback", 10, 100)
        space.add_float("zscore_threshold", 1.0, 3.0)
        space.add_float("position_size", 0.05, 0.3)
        space.add_float("stop_loss", 0.01, 0.05)
        return space

    @staticmethod
    def create_rl_space() -> ParamSpace:
        """Parameter space for RL hyperparameters."""
        space = ParamSpace()
        space.add_float("learning_rate", 1e-5, 1e-3, log=True)
        space.add_int("n_steps", 512, 4096, step=512)
        space.add_int("batch_size", 32, 256, step=32)
        space.add_float("gamma", 0.9, 0.999)
        space.add_float("gae_lambda", 0.8, 0.99)
        space.add_float("ent_coef", 0.0, 0.1, log=True)
        space.add_float("clip_range", 0.1, 0.3)
        return space

    @staticmethod
    def create_ensemble_space() -> ParamSpace:
        """Parameter space for ensemble weights."""
        space = ParamSpace()
        space.add_float("momentum_weight", 0.0, 1.0)
        space.add_float("meanrev_weight", 0.0, 1.0)
        space.add_float("trend_weight", 0.0, 1.0)
        space.add_float("ml_weight", 0.0, 1.0)
        space.add_float("threshold", 0.3, 0.7)
        return space


class MultiObjectiveOptimizer:
    """
    Multi-objective optimization for trading (return vs risk vs trades).

    Uses NSGA-II algorithm to find Pareto-optimal solutions.
    """

    def __init__(
        self,
        objective_fns: List[Callable],  # List of functions returning (value, direction)
        param_space: ParamSpace,
        study_name: str = "brain_multiobj",
        results_dir: str = "hpo_results",
    ):
        self.objective_fns = objective_fns
        self.param_space = param_space
        self.study_name = study_name
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

        self.study: Optional[optuna.Study] = None

    def optimize(self, n_trials: int = 100) -> List[Dict[str, Any]]:
        """
        Run multi-objective optimization.

        Returns:
            List of Pareto-optimal solutions
        """
        self.study = optuna.create_study(
            study_name=self.study_name,
            directions=["maximize", "minimize", "maximize"],  # return, drawdown, sharpe
            sampler=TPESampler(),
        )

        def objective(trial: optuna.Trial):
            params = self.param_space.suggest(trial)

            # Evaluate all objectives
            values = []
            for fn in self.objective_fns:
                val = fn(params)
                values.append(val)

            return tuple(values)

        self.study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

        # Get Pareto front
        pareto_trials = self.study.best_trials

        solutions = []
        for trial in pareto_trials:
            solutions.append({
                "params": trial.params,
                "values": trial.values,
                "number": trial.number,
            })

        # Save
        results_path = self.results_dir / f"{self.study_name}_pareto.json"
        with open(results_path, "w") as f:
            json.dump(solutions, f, indent=2, default=str)

        logger.info(f"Found {len(solutions)} Pareto-optimal solutions")
        return solutions
