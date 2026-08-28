"""
RLAdapter - Stable-Baselines3 Integration for Brain AI Trading System
=====================================================================

Provides:
    - Training pipeline for PPO/SAC agents
    - Model persistence and loading
    - Real-time inference for live trading
    - Callbacks for monitoring and early stopping

Usage:
    adapter = RLAdapter(env, algorithm="PPO")
    adapter.train(total_timesteps=100000)
    adapter.save("models/ppo_brain_v1")

    # Live inference
    action = adapter.predict(observation)
"""

import os
import json
import logging
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
from datetime import datetime

import numpy as np
import gymnasium as gym

# Stable-Baselines3
from stable_baselines3 import PPO, SAC, A2C
from stable_baselines3.common.callbacks import (
    BaseCallback, EvalCallback, CheckpointCallback, 
    StopTrainingOnRewardThreshold, StopTrainingOnNoModelImprovement
)
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

import torch
import torch.nn as nn

logger = logging.getLogger(__name__)


class TradingFeaturesExtractor(BaseFeaturesExtractor):
    """
    Custom CNN+LSTM feature extractor for trading observations.

    Processes:
    - market_features: (seq_len, n_features) → LSTM
    - portfolio_state: (6,) → Linear
    - recent_returns: (20,) → Linear
    """

    def __init__(self, observation_space: gym.Space, features_dim: int = 256):
        super().__init__(observation_space, features_dim)

        n_features = observation_space["market_features"].shape[1]
        seq_len = observation_space["market_features"].shape[0]

        # LSTM for market features
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            dropout=0.2,
        )

        # Linear for portfolio state
        self.portfolio_net = nn.Sequential(
            nn.Linear(6, 32),
            nn.ReLU(),
        )

        # Linear for recent returns
        self.returns_net = nn.Sequential(
            nn.Linear(20, 32),
            nn.ReLU(),
        )

        # Fusion layer
        self.fusion = nn.Sequential(
            nn.Linear(128 + 32 + 32, features_dim),
            nn.ReLU(),
        )

    def forward(self, observations: Dict[str, torch.Tensor]) -> torch.Tensor:
        # Market features through LSTM
        market = observations["market_features"]  # (batch, seq, features)
        lstm_out, _ = self.lstm(market)
        market_emb = lstm_out[:, -1, :]  # Take last timestep

        # Portfolio state
        portfolio = self.portfolio_net(observations["portfolio_state"])

        # Recent returns
        returns = self.returns_net(observations["recent_returns"])

        # Concatenate and fuse
        combined = torch.cat([market_emb, portfolio, returns], dim=1)
        return self.fusion(combined)


class TensorboardCallback(BaseCallback):
    """Custom callback for logging trading-specific metrics."""

    def __init__(self, verbose: int = 0):
        super().__init__(verbose)
        self.episode_rewards = []
        self.episode_pnls = []
        self.episode_sharpes = []

    def _on_step(self) -> bool:
        # Log per-step metrics
        infos = self.locals.get("infos", [])
        for info in infos:
            if "episode_metrics" in info:
                metrics = info["episode_metrics"]
                self.logger.record("trading/pnl", metrics.total_pnl)
                self.logger.record("trading/sharpe", metrics.sharpe_ratio)
                self.logger.record("trading/drawdown", metrics.max_drawdown)
                self.logger.record("trading/win_rate", metrics.win_rate)
                self.logger.record("trading/num_trades", metrics.num_trades)
        return True


class TrainingCallback(BaseCallback):
    """Callback for saving best models and early stopping."""

    def __init__(
        self,
        save_dir: str,
        save_freq: int = 10000,
        eval_freq: int = 5000,
        min_reward: float = -float("inf"),
        patience: int = 10,
        verbose: int = 1,
    ):
        super().__init__(verbose)
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)
        self.save_freq = save_freq
        self.eval_freq = eval_freq
        self.min_reward = min_reward
        self.patience = patience
        self.best_mean_reward = -float("inf")
        self.no_improvement_count = 0

    def _on_step(self) -> bool:
        # Save checkpoint
        if self.n_calls % self.save_freq == 0:
            path = self.save_dir / f"checkpoint_{self.n_calls}_steps"
            self.model.save(path)
            logger.info(f"Saved checkpoint to {path}")

        # Check for improvement
        if self.n_calls % self.eval_freq == 0:
            # Simple evaluation: mean reward over last 100 episodes
            if len(self.model.ep_info_buffer) > 0:
                mean_reward = np.mean([ep["r"] for ep in self.model.ep_info_buffer])

                if mean_reward > self.best_mean_reward:
                    self.best_mean_reward = mean_reward
                    self.no_improvement_count = 0
                    # Save best model
                    best_path = self.save_dir / "best_model"
                    self.model.save(best_path)
                    logger.info(f"New best model! Mean reward: {mean_reward:.2f}")
                else:
                    self.no_improvement_count += 1

                # Early stopping
                if self.no_improvement_count >= self.patience:
                    logger.info(f"Early stopping after {self.patience} evaluations without improvement")
                    return False

                if mean_reward < self.min_reward:
                    logger.warning(f"Mean reward {mean_reward:.2f} below threshold {self.min_reward:.2f}")
                    return False

        return True


class RLAdapter:
    """
    Main adapter for Stable-Baselines3 RL algorithms.

    Supports:
    - PPO (Proximal Policy Optimization) - Recommended for discrete actions
    - SAC (Soft Actor-Critic) - Recommended for continuous actions
    - A2C (Advantage Actor-Critic) - Lightweight alternative
    """

    ALGORITHMS = {
        "PPO": PPO,
        "SAC": SAC,
        "A2C": A2C,
    }

    def __init__(
        self,
        env: gym.Env,
        algorithm: str = "PPO",
        policy: str = "MultiInputPolicy",
        model_dir: str = "models/rl",
        tensorboard_dir: str = "tensorboard/rl",
        device: str = "auto",
        **kwargs,
    ):
        """
        Initialize RL adapter.

        Args:
            env: Gymnasium environment (BrainTradingEnv)
            algorithm: "PPO", "SAC", or "A2C"
            policy: Policy type (default: MultiInputPolicy for Dict observations)
            model_dir: Directory to save/load models
            tensorboard_dir: Directory for TensorBoard logs
            device: "cuda", "cpu", or "auto"
            **kwargs: Additional algorithm-specific hyperparameters
        """
        self.env = env
        self.algorithm_name = algorithm
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.tensorboard_dir = Path(tensorboard_dir)

        if algorithm not in self.ALGORITHMS:
            raise ValueError(f"Unknown algorithm: {algorithm}. Choose from {list(self.ALGORITHMS.keys())}")

        algo_class = self.ALGORITHMS[algorithm]

        # Default hyperparameters optimized for trading
        default_params = self._get_default_params(algorithm)
        default_params.update(kwargs)

        # Custom policy kwargs for feature extractor
        policy_kwargs = dict(
            features_extractor_class=TradingFeaturesExtractor,
            features_extractor_kwargs=dict(features_dim=256),
            net_arch=dict(pi=[256, 128], vf=[256, 128]) if algorithm != "SAC" else [256, 256],
        )

        self.model = algo_class(
            policy,
            env,
            policy_kwargs=policy_kwargs,
            tensorboard_log=str(self.tensorboard_dir),
            device=device,
            verbose=1,
            **default_params,
        )

        self.training_history = []
        logger.info(f"Initialized {algorithm} adapter")

    def _get_default_params(self, algorithm: str) -> Dict[str, Any]:
        """Get default hyperparameters for each algorithm."""
        params = {
            "PPO": {
                "learning_rate": 3e-4,
                "n_steps": 2048,
                "batch_size": 64,
                "n_epochs": 10,
                "gamma": 0.99,
                "gae_lambda": 0.95,
                "clip_range": 0.2,
                "ent_coef": 0.01,  # Encourage exploration
                "vf_coef": 0.5,
                "max_grad_norm": 0.5,
            },
            "SAC": {
                "learning_rate": 3e-4,
                "buffer_size": 100000,
                "batch_size": 256,
                "gamma": 0.99,
                "tau": 0.005,
                "ent_coef": "auto",
                "target_update_interval": 1,
            },
            "A2C": {
                "learning_rate": 7e-4,
                "n_steps": 5,
                "gamma": 0.99,
                "gae_lambda": 1.0,
                "ent_coef": 0.01,
                "vf_coef": 0.25,
                "max_grad_norm": 0.5,
            },
        }
        return params.get(algorithm, {})

    def train(
        self,
        total_timesteps: int = 100000,
        eval_env: Optional[gym.Env] = None,
        save_freq: int = 10000,
        eval_freq: int = 5000,
        patience: int = 10,
        min_reward: float = -float("inf"),
    ) -> Dict[str, Any]:
        """
        Train the RL agent.

        Args:
            total_timesteps: Total training steps
            eval_env: Optional separate environment for evaluation
            save_freq: Save checkpoint every N steps
            eval_freq: Evaluate every N steps
            patience: Early stopping patience
            min_reward: Minimum reward threshold

        Returns:
            Training history dictionary
        """
        callbacks = [
            TensorboardCallback(),
            TrainingCallback(
                save_dir=self.model_dir,
                save_freq=save_freq,
                eval_freq=eval_freq,
                patience=patience,
                min_reward=min_reward,
            ),
        ]

        if eval_env is not None:
            eval_callback = EvalCallback(
                eval_env,
                best_model_save_path=str(self.model_dir / "eval_best"),
                log_path=str(self.model_dir / "eval_logs"),
                eval_freq=eval_freq,
                deterministic=True,
                render=False,
            )
            callbacks.append(eval_callback)

        logger.info(f"Starting training for {total_timesteps} steps...")
        self.model.learn(
            total_timesteps=total_timesteps,
            callback=callbacks,
            progress_bar=True,
        )

        # Save final model
        final_path = self.model_dir / "final_model"
        self.model.save(final_path)

        history = {
            "algorithm": self.algorithm_name,
            "total_timesteps": total_timesteps,
            "model_dir": str(self.model_dir),
            "completed_at": datetime.now().isoformat(),
        }

        # Save training metadata
        with open(self.model_dir / "training_metadata.json", "w") as f:
            json.dump(history, f, indent=2)

        self.training_history.append(history)
        logger.info(f"Training complete. Model saved to {final_path}")

        return history

    def predict(
        self,
        observation: Dict[str, np.ndarray],
        deterministic: bool = True,
    ) -> Tuple[np.ndarray, Optional[Dict]]:
        """
        Get action from trained model.

        Args:
            observation: Current observation from environment
            deterministic: If True, use greedy policy; if False, sample from policy

        Returns:
            (action, state) tuple
        """
        action, state = self.model.predict(observation, deterministic=deterministic)
        return action, state

    def save(self, path: str):
        """Save model to disk."""
        self.model.save(path)
        logger.info(f"Model saved to {path}")

    def load(self, path: str, env: Optional[gym.Env] = None):
        """Load model from disk."""
        algo_class = self.ALGORITHMS[self.algorithm_name]
        self.model = algo_class.load(path, env=env)
        logger.info(f"Model loaded from {path}")

    def evaluate(self, env: gym.Env, n_episodes: int = 10) -> Dict[str, float]:
        """
        Evaluate model performance.

        Returns:
            Dictionary with metrics: mean_reward, mean_pnl, sharpe, win_rate, etc.
        """
        episode_rewards = []
        episode_pnls = []
        episode_sharpes = []
        episode_drawdowns = []

        for ep in range(n_episodes):
            obs, _ = env.reset()
            done = False
            total_reward = 0

            while not done:
                action, _ = self.predict(obs, deterministic=True)
                obs, reward, terminated, truncated, info = env.step(action)
                total_reward += reward
                done = terminated or truncated

            metrics = info.get("episode_metrics", None)
            if metrics:
                episode_pnls.append(metrics.total_pnl)
                episode_sharpes.append(metrics.sharpe_ratio)
                episode_drawdowns.append(metrics.max_drawdown)

            episode_rewards.append(total_reward)

        results = {
            "mean_reward": np.mean(episode_rewards),
            "std_reward": np.std(episode_rewards),
            "mean_pnl": np.mean(episode_pnls) if episode_pnls else 0,
            "mean_sharpe": np.mean(episode_sharpes) if episode_sharpes else 0,
            "mean_drawdown": np.mean(episode_drawdowns) if episode_drawdowns else 0,
            "n_episodes": n_episodes,
        }

        logger.info(f"Evaluation results: {results}")
        return results


class TradingPolicy:
    """
    High-level policy wrapper that combines RL with rule-based safety guards.

    Usage in production:
        policy = TradingPolicy(rl_adapter, risk_limits={...})
        action = policy.get_action(observation, portfolio_state)
    """

    def __init__(
        self,
        rl_adapter: RLAdapter,
        max_position_size: float = 0.5,  # Max 50% of equity
        max_daily_trades: int = 20,
        max_drawdown_pct: float = 0.15,
        min_confidence: float = 0.6,
    ):
        self.rl_adapter = rl_adapter
        self.max_position_size = max_position_size
        self.max_daily_trades = max_daily_trades
        self.max_drawdown_pct = max_drawdown_pct
        self.min_confidence = min_confidence
        self.daily_trade_count = 0
        self.peak_equity = 0

    def get_action(
        self,
        observation: Dict[str, np.ndarray],
        portfolio_state: Dict[str, float],
    ) -> int:
        """
        Get action with safety guardrails.

        Args:
            observation: Environment observation
            portfolio_state: Current portfolio state

        Returns:
            Action (0=HOLD, 1=BUY, 2=SELL)
        """
        equity = portfolio_state.get("equity", 0)
        position = portfolio_state.get("position", 0)

        # Update peak equity
        self.peak_equity = max(self.peak_equity, equity)

        # Check drawdown limit
        drawdown = (self.peak_equity - equity) / self.peak_equity if self.peak_equity > 0 else 0
        if drawdown > self.max_drawdown_pct:
            logger.warning(f"Drawdown limit hit: {drawdown:.2%}. Forcing HOLD.")
            return 0  # HOLD

        # Check daily trade limit
        if self.daily_trade_count >= self.max_daily_trades:
            return 0  # HOLD

        # Get RL action
        action, _ = self.rl_adapter.predict(observation, deterministic=False)

        # Check position size limit
        if action == 1 and abs(position) >= self.max_position_size:
            return 0  # HOLD - max position reached

        # Check confidence (for continuous actions, use |action| as confidence proxy)
        if isinstance(action, np.ndarray):
            confidence = abs(action[0])
            if confidence < self.min_confidence:
                return 0  # HOLD - not confident enough

        if action != 0:
            self.daily_trade_count += 1

        return int(action) if np.isscalar(action) else int(action[0])

    def reset_daily(self):
        """Reset daily counters (call at market open)."""
        self.daily_trade_count = 0
