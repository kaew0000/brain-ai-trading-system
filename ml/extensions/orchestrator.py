"""
ExtensionsOrchestrator - Main Orchestrator for Brain AI Extensions
==========================================================

Coordinates all three components:
    1. RLAdapter (Stable-Baselines3) - Policy learning
    2. OnlineLearner (River) - Real-time adaptation
    3. HPOManager (Optuna) - Hyperparameter optimization

Usage:
    bundle = ExtensionsOrchestrator(config)

    # 1. Optimize strategy parameters first
    best_params = bundle.optimize_strategy(n_trials=50)

    # 2. Train RL agent with optimized params
    bundle.train_rl(total_timesteps=100000)

    # 3. Start online learning for live adaptation
    bundle.start_online_learning()

    # 4. Get trading decision
    action = bundle.get_action(observation)
"""

import json
import logging
from typing import Dict, List, Optional, Callable, Any, Union
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from threading import Thread, Lock
import time

import numpy as np

from .rl.adapter import RLAdapter, TradingPolicy
from .online.learner import OnlineLearner, OnlineModelConfig, MultiSymbolOnlineLearner
from .hpo.manager import HPOManager, HPOConfig, ParamSpace, StrategyOptimizer
from .rl.env import BrainTradingEnv

logger = logging.getLogger(__name__)


@dataclass
class ExtensionsConfig:
    """Master configuration for the entire bundle."""
    # RL
    rl_algorithm: str = "PPO"
    rl_model_dir: str = "models/rl"
    rl_total_timesteps: int = 100000
    rl_eval_freq: int = 5000

    # Online Learning
    online_task: str = "classification"
    online_model_type: str = "logistic"
    online_model_dir: str = "models/online"
    online_drift_threshold: float = 0.002

    # HPO
    hpo_study_name: str = "brain_bundle"
    hpo_n_trials: int = 50
    hpo_results_dir: str = "hpo_results"

    # Integration
    mode: str = "paper"  # "paper", "backtest", "live"
    symbols: List[str] = None

    def __post_init__(self):
        if self.symbols is None:
            self.symbols = ["BTCUSDT"]


class ExtensionsOrchestrator:
    """
    Central manager that coordinates RL, Online Learning, and HPO.

    Architecture:
        Data Pipeline → BrainTradingEnv → RLAdapter (Policy)
                                ↓
                        OnlineLearner (Adaptation)
                                ↓
                        HPOManager (Optimization)
    """

    def __init__(
        self,
        config: Optional[ExtensionsConfig] = None,
        data_pipeline: Any = None,
        strategy_fn: Optional[Callable] = None,
        backtest_fn: Optional[Callable] = None,
    ):
        """
        Initialize bundle manager.

        Args:
            config: Bundle configuration
            data_pipeline: Brain Bot data pipeline instance
            strategy_fn: Strategy factory function(params) -> strategy
            backtest_fn: Backtest function(strategy) -> metrics dict
        """
        self.config = config or ExtensionsConfig()
        self.data_pipeline = data_pipeline
        self.strategy_fn = strategy_fn
        self.backtest_fn = backtest_fn

        # Components (initialized lazily)
        self.rl_adapter: Optional[RLAdapter] = None
        self.online_learner: Optional[Union[OnlineLearner, MultiSymbolOnlineLearner]] = None
        self.hpo_manager: Optional[HPOManager] = None
        self.trading_env: Optional[BrainTradingEnv] = None
        self.trading_policy: Optional[TradingPolicy] = None

        # State
        self.is_online_learning_active = False
        self.online_learning_thread: Optional[Thread] = None
        self._lock = Lock()
        self.current_params: Dict[str, Any] = {}
        self.performance_log: List[Dict[str, Any]] = []

        # Results directory
        self.results_dir = Path("bundle_results")
        self.results_dir.mkdir(parents=True, exist_ok=True)

        logger.info("ExtensionsOrchestrator initialized")

    # ============================================================
    # PHASE 1: Hyperparameter Optimization
    # ============================================================

    def optimize_strategy(
        self,
        param_space: Optional[ParamSpace] = None,
        n_trials: Optional[int] = None,
        objective_metric: str = "sharpe_ratio",
    ) -> Dict[str, Any]:
        """
        Phase 1: Optimize strategy parameters using Optuna.

        Args:
            param_space: Parameter search space (auto-generated if None)
            n_trials: Number of optimization trials
            objective_metric: Metric to optimize ("sharpe_ratio", "total_return", "win_rate")

        Returns:
            Dictionary with best parameters and optimization stats
        """
        if param_space is None:
            param_space = StrategyOptimizer.create_momentum_space()

        if self.strategy_fn is None or self.backtest_fn is None:
            raise ValueError("strategy_fn and backtest_fn must be provided for optimization")

        def objective(trial: Any, params: Dict[str, Any]) -> float:
            """Objective function for Optuna."""
            # Create strategy with suggested params
            strategy = self.strategy_fn(**params)

            # Run backtest
            metrics = self.backtest_fn(strategy)

            # Return objective metric
            score = metrics.get(objective_metric, 0)

            # Log for analysis
            logger.info(f"Trial {trial.number}: {objective_metric}={score:.4f}, params={params}")

            return score

        hpo_config = HPOConfig(
            study_name=self.config.hpo_study_name,
            direction="maximize",
            n_trials=n_trials or self.config.hpo_n_trials,
        )

        self.hpo_manager = HPOManager(
            objective_fn=objective,
            param_space=param_space,
            config=hpo_config,
            results_dir=self.config.hpo_results_dir,
        )

        results = self.hpo_manager.optimize()
        self.current_params = results["best_params"]

        logger.info(f"Strategy optimization complete. Best params: {self.current_params}")
        return results

    # ============================================================
    # PHASE 2: RL Training
    # ============================================================

    def setup_trading_env(self, **env_kwargs) -> BrainTradingEnv:
        """Create trading environment from data pipeline."""
        if self.data_pipeline is None:
            raise ValueError("data_pipeline required for RL training")

        # Merge optimized params with env config
        env_config = {
            "data_pipeline": self.data_pipeline,
            "lookback_window": self.current_params.get("lookback", 50),
            "position_size": self.current_params.get("position_size", 0.1),
            "continuous": self.config.rl_algorithm == "SAC",
        }
        env_config.update(env_kwargs)

        self.trading_env = BrainTradingEnv(**env_config)
        return self.trading_env

    def train_rl(
        self,
        total_timesteps: Optional[int] = None,
        eval_env: Optional[Any] = None,
        **train_kwargs,
    ) -> Dict[str, Any]:
        """
        Phase 2: Train RL agent.

        Args:
            total_timesteps: Training steps
            eval_env: Separate env for evaluation
            **train_kwargs: Additional training arguments

        Returns:
            Training history
        """
        if self.trading_env is None:
            self.setup_trading_env()

        self.rl_adapter = RLAdapter(
            env=self.trading_env,
            algorithm=self.config.rl_algorithm,
            model_dir=self.config.rl_model_dir,
            **train_kwargs,
        )

        history = self.rl_adapter.train(
            total_timesteps=total_timesteps or self.config.rl_total_timesteps,
            eval_env=eval_env,
        )

        # Create trading policy with safety guards
        self.trading_policy = TradingPolicy(
            rl_adapter=self.rl_adapter,
            max_position_size=self.current_params.get("position_size", 0.1) * 2,
        )

        logger.info("RL training complete")
        return history

    def load_rl_model(self, path: str):
        """Load pre-trained RL model."""
        if self.rl_adapter is None:
            self.rl_adapter = RLAdapter(
                env=self.trading_env or self.setup_trading_env(),
                algorithm=self.config.rl_algorithm,
                model_dir=self.config.rl_model_dir,
            )

        self.rl_adapter.load(path)
        self.trading_policy = TradingPolicy(rl_adapter=self.rl_adapter)
        logger.info(f"RL model loaded from {path}")

    # ============================================================
    # PHASE 3: Online Learning
    # ============================================================

    def setup_online_learning(self, symbols: Optional[List[str]] = None) -> Union[OnlineLearner, MultiSymbolOnlineLearner]:
        """Initialize online learning component."""
        config = OnlineModelConfig(
            task=self.config.online_task,
            model_type=self.config.online_model_type,
            drift_threshold=self.config.online_drift_threshold,
        )

        symbols = symbols or self.config.symbols

        if len(symbols) > 1:
            self.online_learner = MultiSymbolOnlineLearner(
                symbols=symbols,
                config=config,
                model_dir=self.config.online_model_dir,
            )
        else:
            self.online_learner = OnlineLearner(
                config=config,
                model_dir=self.config.online_model_dir,
            )

        return self.online_learner

    def start_online_learning(self, callback: Optional[Callable] = None):
        """
        Start online learning in background thread.

        Args:
            callback: Function(features, prediction, metrics) called after each update
        """
        if self.online_learner is None:
            self.setup_online_learning()

        self.is_online_learning_active = True

        def learning_loop():
            while self.is_online_learning_active:
                try:
                    # This would be connected to live data feed
                    # For now, placeholder structure
                    pass
                except Exception as e:
                    logger.error(f"Online learning error: {e}")
                time.sleep(1)

        self.online_learning_thread = Thread(target=learning_loop, daemon=True)
        self.online_learning_thread.start()
        logger.info("Online learning started")

    def stop_online_learning(self):
        """Stop online learning thread."""
        self.is_online_learning_active = False
        if self.online_learning_thread:
            self.online_learning_thread.join(timeout=5)
        logger.info("Online learning stopped")

    def online_update(
        self,
        x: Dict[str, float],
        y: Union[int, float],
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Manual online update (for integration with live data pipeline).

        Args:
            x: Feature dictionary
            y: True label/value
            symbol: Symbol (for multi-symbol mode)

        Returns:
            Update results including prediction and drift status
        """
        if self.online_learner is None:
            self.setup_online_learning()

        with self._lock:
            if isinstance(self.online_learner, MultiSymbolOnlineLearner) and symbol:
                result = self.online_learner.learn(symbol, x, y)
            else:
                result = self.online_learner.learn(x, y)

            # Log performance
            self.performance_log.append({
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "features": x,
                "true": y,
                "pred": result["prediction"],
                "error": result["error"],
                "drift": result["drift_detected"],
            })

            return result

    # ============================================================
    # DECISION ENGINE
    # ============================================================

    def get_action(
        self,
        observation: Dict[str, np.ndarray],
        portfolio_state: Optional[Dict[str, float]] = None,
        symbol: Optional[str] = None,
        use_rl: bool = True,
        use_online: bool = True,
        ensemble_weights: Optional[Dict[str, float]] = None,
    ) -> int:
        """
        Get final trading decision combining all components.

        Args:
            observation: Environment observation
            portfolio_state: Current portfolio state
            symbol: Trading symbol
            use_rl: Whether to use RL policy
            use_online: Whether to use online learner
            ensemble_weights: Custom weights for ensemble

        Returns:
            Action (0=HOLD, 1=BUY, 2=SELL)
        """
        votes = []
        weights = ensemble_weights or {"rl": 0.5, "online": 0.3, "default": 0.2}

        # RL vote
        if use_rl and self.trading_policy is not None:
            if portfolio_state:
                rl_action = self.trading_policy.get_action(observation, portfolio_state)
            else:
                rl_action, _ = self.rl_adapter.predict(observation, deterministic=True)
                rl_action = int(rl_action) if np.isscalar(rl_action) else int(rl_action[0])
            votes.append((rl_action, weights["rl"]))

        # Online learning vote
        if use_online and self.online_learner is not None:
            # Extract features from observation for online learner
            # This is a simplified version - adjust based on your feature format
            features = self._extract_features(observation)
            online_pred = self.online_learner.predict(features)
            votes.append((int(online_pred), weights["online"]))

        # Default hold
        votes.append((0, weights["default"]))

        # Weighted voting
        action_scores = {0: 0.0, 1: 0.0, 2: 0.0}
        for action, weight in votes:
            action_scores[action] += weight

        final_action = max(action_scores, key=action_scores.get)

        logger.debug(f"Decision: {final_action} (scores: {action_scores})")
        return final_action

    def _extract_features(self, observation: Dict[str, np.ndarray]) -> Dict[str, float]:
        """Extract flat features from observation for online learner."""
        features = {}

        # Portfolio state features
        if "portfolio_state" in observation:
            portfolio = observation["portfolio_state"]
            features["position"] = float(portfolio[0])
            features["balance"] = float(portfolio[1])
            features["equity"] = float(portfolio[2])
            features["unrealized_pnl"] = float(portfolio[3])

        # Recent returns statistics
        if "recent_returns" in observation:
            returns = observation["recent_returns"]
            features["return_mean"] = float(np.mean(returns))
            features["return_std"] = float(np.std(returns))
            features["return_max"] = float(np.max(returns))
            features["return_min"] = float(np.min(returns))

        # Market features summary
        if "market_features" in observation:
            market = observation["market_features"]
            features["price"] = float(market[-1, 0]) if market.shape[0] > 0 else 0
            features["price_change"] = float(market[-1, 0] - market[0, 0]) if market.shape[0] > 1 else 0

        return features

    # ============================================================
    # PERSISTENCE & REPORTING
    # ============================================================

    def save_state(self, path: Optional[str] = None):
        """Save complete bundle state."""
        if path is None:
            path = self.results_dir / f"bundle_state_{datetime.now():%Y%m%d_%H%M%S}"

        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        # Save config
        with open(path / "config.json", "w") as f:
            json.dump(asdict(self.config), f, indent=2, default=str)

        # Save current params
        with open(path / "params.json", "w") as f:
            json.dump(self.current_params, f, indent=2)

        # Save RL model
        if self.rl_adapter:
            self.rl_adapter.save(str(path / "rl_model"))

        # Save online learner
        if self.online_learner:
            self.online_learner.save(str(path / "online_model.pkl"))

        # Save performance log
        with open(path / "performance_log.json", "w") as f:
            json.dump(self.performance_log, f, indent=2, default=str)

        logger.info(f"Bundle state saved to {path}")
        return path

    def load_state(self, path: str):
        """Load complete bundle state."""
        path = Path(path)

        # Load config
        with open(path / "config.json", "r") as f:
            config_dict = json.load(f)
            self.config = ExtensionsConfig(**config_dict)

        # Load params
        with open(path / "params.json", "r") as f:
            self.current_params = json.load(f)

        # Load RL model
        rl_model_path = path / "rl_model.zip"
        if rl_model_path.exists():
            self.load_rl_model(str(rl_model_path))

        # Load online learner
        online_model_path = path / "online_model.pkl"
        if online_model_path.exists():
            if self.online_learner is None:
                self.setup_online_learning()
            self.online_learner.load(str(online_model_path))

        logger.info(f"Bundle state loaded from {path}")

    def get_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "config": asdict(self.config),
            "current_params": self.current_params,
            "components": {
                "rl_ready": self.rl_adapter is not None,
                "online_ready": self.online_learner is not None,
                "hpo_ready": self.hpo_manager is not None,
            },
        }

        # RL metrics
        if self.rl_adapter:
            report["rl"] = {
                "algorithm": self.rl_adapter.algorithm_name,
                "training_history": self.rl_adapter.training_history,
            }

        # Online metrics
        if self.online_learner:
            if isinstance(self.online_learner, MultiSymbolOnlineLearner):
                report["online"] = self.online_learner.get_all_metrics()
            else:
                report["online"] = self.online_learner.get_metrics()

        # HPO results
        if self.hpo_manager and self.hpo_manager.study:
            report["hpo"] = {
                "best_params": self.hpo_manager.best_params,
                "best_score": self.hpo_manager.study.best_value,
                "n_trials": len(self.hpo_manager.study.trials),
                "param_importance": self.hpo_manager.get_param_importance(),
            }

        # Performance log summary
        if self.performance_log:
            errors = [p["error"] for p in self.performance_log if "error" in p]
            drifts = sum(1 for p in self.performance_log if p.get("drift", False))
            report["performance_summary"] = {
                "total_updates": len(self.performance_log),
                "mean_error": np.mean(errors) if errors else 0,
                "drift_events": drifts,
            }

        return report
