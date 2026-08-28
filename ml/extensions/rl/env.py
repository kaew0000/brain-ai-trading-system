"""
BrainTradingEnv - Custom Gymnasium Environment for Brain AI Trading System
===========================================================================

Wraps the Brain Bot trading pipeline into a standard Gymnasium interface
so that Stable-Baselines3 (PPO/SAC) can learn optimal trading policies.

Reward Shaping:
    - PnL-based reward (primary)
    - Sharpe ratio bonus
    - Drawdown penalty
    - Over-trading penalty (transaction cost)
"""

import numpy as np
import gymnasium as gym
from gymnasium import spaces
from typing import Dict, Optional, Any
from dataclasses import dataclass
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class TradeMetrics:
    """Metrics for a single trading episode."""
    total_pnl: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    num_trades: int = 0
    win_rate: float = 0.0
    avg_profit_per_trade: float = 0.0


class BrainTradingEnv(gym.Env):
    """
    Custom Gymnasium environment that interfaces with Brain AI Trading System.

    Action Space:
        Discrete(3): 0=HOLD, 1=BUY, 2=SELL
        Or Continuous(1): position size [-1, 1] for SAC

    Observation Space:
        Dict with:
        - market_features: normalized price/indicator features
        - portfolio_state: [position, cash, equity, unrealized_pnl]
        - recent_trades: last N trade outcomes
    """

    metadata = {"render_modes": ["human", "rgb_array"], "render_fps": 30}

    def __init__(
        self,
        data_pipeline: Any,           # Brain Bot data pipeline
        initial_balance: float = 10000.0,
        lookback_window: int = 50,
        max_episode_steps: int = 1000,
        transaction_cost_pct: float = 0.001,
        slippage_pct: float = 0.0005,
        reward_sharpe_weight: float = 0.3,
        reward_drawdown_weight: float = 0.5,
        reward_overtrade_weight: float = 0.1,
        position_size: float = 0.1,   # 10% of equity per trade
        continuous: bool = False,     # False=Discrete(PPO), True=Continuous(SAC)
        render_mode: Optional[str] = None,
    ):
        super().__init__()

        self.data_pipeline = data_pipeline
        self.initial_balance = initial_balance
        self.lookback_window = lookback_window
        self.max_episode_steps = max_episode_steps
        self.transaction_cost_pct = transaction_cost_pct
        self.slippage_pct = slippage_pct
        self.reward_sharpe_weight = reward_sharpe_weight
        self.reward_drawdown_weight = reward_drawdown_weight
        self.reward_overtrade_weight = reward_overtrade_weight
        self.position_size = position_size
        self.continuous = continuous
        self.render_mode = render_mode

        # Portfolio state
        self.balance = initial_balance
        self.equity = initial_balance
        self.position = 0.0            # 0=no position, >0=long, <0=short
        self.entry_price = 0.0
        self.trades_history = deque(maxlen=100)
        self.equity_curve = deque(maxlen=max_episode_steps)
        self.returns_history = deque(maxlen=50)

        # Episode tracking
        self.current_step = 0
        self.current_price = 0.0
        self.prev_equity = initial_balance
        self.daily_trades = 0

        # Define spaces
        n_features = 20  # Adjust based on your feature engineering

        if continuous:
            self.action_space = spaces.Box(
                low=-1.0, high=1.0, shape=(1,), dtype=np.float32
            )
        else:
            self.action_space = spaces.Discrete(3)  # HOLD, BUY, SELL

        self.observation_space = spaces.Dict({
            "market_features": spaces.Box(
                low=-np.inf, high=np.inf, 
                shape=(lookback_window, n_features), 
                dtype=np.float32
            ),
            "portfolio_state": spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(6,), dtype=np.float32
            ),
            "recent_returns": spaces.Box(
                low=-np.inf, high=np.inf,
                shape=(20,), dtype=np.float32
            ),
        })

    def _get_observation(self) -> Dict[str, np.ndarray]:
        """Build observation from current state."""
        # Market features from data pipeline
        market_features = self.data_pipeline.get_features(
            window=self.lookback_window
        )
        if market_features.shape[0] < self.lookback_window:
            # Pad if needed
            pad = np.zeros((self.lookback_window - market_features.shape[0], 
                           market_features.shape[1]))
            market_features = np.vstack([pad, market_features])

        # Portfolio state
        unrealized_pnl = 0.0
        if self.position != 0:
            unrealized_pnl = (self.current_price - self.entry_price) * self.position

        portfolio_state = np.array([
            self.position / (self.equity / self.current_price) if self.current_price > 0 else 0,  # normalized position
            self.balance / self.initial_balance,      # normalized cash
            self.equity / self.initial_balance,       # normalized equity
            unrealized_pnl / self.initial_balance,     # normalized unrealized PnL
            self.daily_trades / 10.0,                   # normalized trade count
            len(self.trades_history) / 100.0,           # normalized total trades
        ], dtype=np.float32)

        # Recent returns (pad with zeros if not enough history)
        returns = list(self.returns_history)
        while len(returns) < 20:
            returns.insert(0, 0.0)
        recent_returns = np.array(returns[-20:], dtype=np.float32)

        return {
            "market_features": market_features.astype(np.float32),
            "portfolio_state": portfolio_state,
            "recent_returns": recent_returns,
        }

    def _calculate_reward(self, action: int, old_equity: float) -> float:
        """
        Multi-objective reward function.

        Components:
        1. PnL reward: equity change
        2. Sharpe bonus: reward smooth returns
        3. Drawdown penalty: punish large losses
        4. Over-trading penalty: punish excessive trading
        """
        # 1. PnL reward (primary)
        equity_change = (self.equity - old_equity) / self.initial_balance
        pnl_reward = equity_change * 100  # Scale up

        # 2. Sharpe ratio bonus
        sharpe_bonus = 0.0
        if len(self.returns_history) >= 10:
            returns = np.array(list(self.returns_history))
            if returns.std() > 0:
                sharpe = returns.mean() / (returns.std() + 1e-8)
                sharpe_bonus = sharpe * self.reward_sharpe_weight

        # 3. Drawdown penalty
        peak = max(self.equity_curve) if self.equity_curve else self.initial_balance
        drawdown = (peak - self.equity) / peak if peak > 0 else 0
        drawdown_penalty = -drawdown * self.reward_drawdown_weight

        # 4. Over-trading penalty
        overtrade_penalty = 0.0
        if self.daily_trades > 5:
            overtrade_penalty = -(self.daily_trades - 5) * self.reward_overtrade_weight

        total_reward = pnl_reward + sharpe_bonus + drawdown_penalty + overtrade_penalty

        return float(total_reward)

    def _execute_action(self, action):
        """Execute trading action and update portfolio."""
        price = self.current_price

        if self.continuous:
            # Continuous action: position size [-1, 1]
            target_position = action[0] * (self.equity / price) * self.position_size
            delta = target_position - self.position

            if delta > 0:
                action_type = 1  # BUY
            elif delta < 0:
                action_type = 2  # SELL
            else:
                action_type = 0  # HOLD
        else:
            action_type = action

        # Execute
        if action_type == 1 and self.position <= 0:  # BUY
            trade_size = (self.equity * self.position_size) / price
            cost = trade_size * price * (1 + self.transaction_cost_pct + self.slippage_pct)

            if self.balance >= cost:
                self.position += trade_size
                self.balance -= cost
                self.entry_price = price
                self.daily_trades += 1
                logger.debug(f"BUY {trade_size:.4f} @ {price:.2f}")

        elif action_type == 2 and self.position >= 0:  # SELL
            if self.position > 0:
                proceeds = self.position * price * (1 - self.transaction_cost_pct - self.slippage_pct)
                pnl = (price - self.entry_price) * self.position
                self.balance += proceeds
                self.trades_history.append(pnl)
                self.position = 0.0
                self.daily_trades += 1
                logger.debug(f"SELL @ {price:.2f}, PnL: {pnl:.2f}")

        # Update equity
        unrealized = 0.0
        if self.position != 0:
            unrealized = (price - self.entry_price) * self.position
        self.equity = self.balance + unrealized

    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None):
        """Reset environment for new episode."""
        super().reset(seed=seed)

        self.balance = self.initial_balance
        self.equity = self.initial_balance
        self.position = 0.0
        self.entry_price = 0.0
        self.trades_history.clear()
        self.equity_curve.clear()
        self.returns_history.clear()
        self.current_step = 0
        self.daily_trades = 0
        self.prev_equity = self.initial_balance

        # Reset data pipeline
        self.data_pipeline.reset()
        self.current_price = self.data_pipeline.get_current_price()

        observation = self._get_observation()
        info = {"episode_metrics": TradeMetrics()}

        return observation, info

    def step(self, action):
        """Execute one step in the environment."""
        old_equity = self.equity

        # Execute action
        self._execute_action(action)

        # Advance data pipeline
        self.data_pipeline.step()
        self.current_price = self.data_pipeline.get_current_price()
        self.current_step += 1

        # Update equity curve and returns
        self.equity_curve.append(self.equity)
        ret = (self.equity - old_equity) / old_equity if old_equity > 0 else 0
        self.returns_history.append(ret)

        # Calculate reward
        reward = self._calculate_reward(action, old_equity)

        # Check termination
        terminated = False
        truncated = False

        # Stop if bankrupt
        if self.equity < self.initial_balance * 0.1:
            terminated = True
            reward -= 10  # Bankruptcy penalty

        # Max steps reached
        if self.current_step >= self.max_episode_steps:
            truncated = True

        # Data exhausted
        if self.data_pipeline.is_done():
            truncated = True

        observation = self._get_observation()

        # Build info
        metrics = TradeMetrics(
            total_pnl=self.equity - self.initial_balance,
            num_trades=len(self.trades_history),
        )
        info = {"episode_metrics": metrics}

        return observation, reward, terminated, truncated, info

    def render(self):
        """Render current state (optional)."""
        if self.render_mode == "human":
            print(f"Step: {self.current_step} | Price: {self.current_price:.2f} | "
                  f"Equity: {self.equity:.2f} | Position: {self.position:.4f} | "
                  f"PnL: {self.equity - self.initial_balance:.2f}")

    def get_metrics(self) -> TradeMetrics:
        """Get comprehensive trading metrics."""
        pnl = self.equity - self.initial_balance
        trades = list(self.trades_history)

        if trades:
            wins = sum(1 for t in trades if t > 0)
            win_rate = wins / len(trades)
            avg_profit = np.mean(trades)
        else:
            win_rate = 0.0
            avg_profit = 0.0

        # Calculate Sharpe
        if len(self.returns_history) > 1:
            returns = np.array(list(self.returns_history))
            sharpe = returns.mean() / (returns.std() + 1e-8) * np.sqrt(252)
        else:
            sharpe = 0.0

        # Max drawdown
        if self.equity_curve:
            equity_arr = np.array(list(self.equity_curve))
            peak = np.maximum.accumulate(equity_arr)
            drawdown = np.max((peak - equity_arr) / peak)
        else:
            drawdown = 0.0

        return TradeMetrics(
            total_pnl=pnl,
            sharpe_ratio=sharpe,
            max_drawdown=drawdown,
            num_trades=len(trades),
            win_rate=win_rate,
            avg_profit_per_trade=avg_profit,
        )
