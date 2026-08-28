"""
Example: Brain AI Extensions Bundle Usage
=========================================

Complete example showing how to integrate the bundle with Brain Bot.
Run this after installing requirements.
"""

import numpy as np

# Import extensions components
from ml.extensions import (
    ExtensionsOrchestrator,
    ExtensionsConfig,
    OnlineModelConfig,
    StrategyOptimizer,
)


# ============================================================
# MOCK DATA PIPELINE (แทนที่ด้วย Brain Bot จริงของคุณ)
# ============================================================

class MockDataPipeline:
    """Mock data pipeline for demonstration. Replace with Brain Bot's real pipeline."""

    def __init__(self, n_steps=5000, n_features=20):
        self.n_steps = n_steps
        self.n_features = n_features
        self.current_step = 0
        self.price = 50000.0

        # Generate synthetic OHLCV data
        np.random.seed(42)
        self.data = self._generate_data()

    def _generate_data(self):
        """Generate synthetic market data with trend and noise."""
        data = []
        price = self.price

        for i in range(self.n_steps):
            # Random walk with slight trend
            change = np.random.normal(0.001, 0.02)
            price *= (1 + change)

            # Features: price, volume, RSI, MACD, etc. (mock)
            features = np.random.randn(self.n_features)
            features[0] = price / 50000.0  # normalized price
            features[1] = change * 100      # return
            features[2] = np.random.uniform(0, 100)  # mock RSI

            data.append(features)

        return np.array(data)

    def reset(self):
        self.current_step = 0
        self.price = 50000.0

    def step(self):
        self.current_step += 1

    def get_current_price(self):
        if self.current_step < len(self.data):
            return self.data[self.current_step][0] * 50000.0
        return self.price

    def get_features(self, window=50):
        start = max(0, self.current_step - window)
        end = min(len(self.data), self.current_step + 1)
        features = self.data[start:end]

        # Pad if needed
        if len(features) < window:
            pad = np.zeros((window - len(features), self.n_features))
            features = np.vstack([pad, features])

        return features

    def is_done(self):
        return self.current_step >= self.n_steps - 1


# ============================================================
# MOCK STRATEGY (แทนที่ด้วย strategy จริงของคุณ)
# ============================================================

class MockStrategy:
    """Mock strategy for HPO demonstration."""

    def __init__(self, lookback=20, threshold=0.05, position_size=0.1, **kwargs):
        self.lookback = lookback
        self.threshold = threshold
        self.position_size = position_size

    def generate_signal(self, data):
        returns = data["close"].pct_change(self.lookback)
        if returns.iloc[-1] > self.threshold:
            return 1
        elif returns.iloc[-1] < -self.threshold:
            return 2
        return 0


def mock_strategy_factory(lookback, threshold, position_size, **kwargs):
    return MockStrategy(lookback, threshold, position_size)


def mock_backtest(strategy):
    """Mock backtest that returns random metrics."""
    np.random.seed(hash(str(strategy.lookback)) % 1000)
    return {
        "sharpe_ratio": np.random.uniform(0.5, 2.5),
        "total_return": np.random.uniform(-0.2, 0.5),
        "max_drawdown": np.random.uniform(0.05, 0.3),
        "win_rate": np.random.uniform(0.4, 0.7),
    }


# ============================================================
# MAIN EXAMPLE
# ============================================================

def main():
    print("=" * 60)
    print("Brain AI Extensions Bundle - Example")
    print("=" * 60)

    # 1. Create mock data pipeline
    print("\n[1] Creating data pipeline...")
    data_pipeline = MockDataPipeline(n_steps=2000)

    # 2. Initialize Bundle
    print("\n[2] Initializing ExtensionsOrchestrator...")
    config = ExtensionsConfig(
        symbols=["BTCUSDT"],
        rl_algorithm="PPO",
        mode="paper",
        rl_total_timesteps=5000,  # น้อยๆ สำหรับ demo
    )

    bundle = ExtensionsOrchestrator(
        config=config,
        data_pipeline=data_pipeline,
        strategy_fn=mock_strategy_factory,
        backtest_fn=mock_backtest,
    )

    # 3. Phase 1: HPO (ลด n_trials สำหรับ demo)
    print("\n[3] Phase 1: Hyperparameter Optimization...")
    space = StrategyOptimizer.create_momentum_space()
    hpo_results = bundle.optimize_strategy(
        param_space=space,
        n_trials=10,  # น้อยๆ สำหรับ demo (ปกติ 50-100)
        objective_metric="sharpe_ratio",
    )
    print(f"    Best params: {hpo_results['best_params']}")
    print(f"    Best score: {hpo_results['best_score']:.4f}")

    # 4. Phase 2: RL Training
    print("\n[4] Phase 2: RL Training...")
    print("    (This may take a few minutes...)")

    env = bundle.setup_trading_env()
    rl_history = bundle.train_rl(
        total_timesteps=2000,  # น้อยๆ สำหรับ demo
        patience=3,
    )
    print("    Training complete. Model saved.")

    # 5. Phase 3: Online Learning Setup
    print("\n[5] Phase 3: Setting up Online Learning...")
    online_config = OnlineModelConfig(
        task="classification",
        model_type="logistic",
        drift_threshold=0.01,
    )
    bundle.setup_online_learning()
    print("    Online learner ready.")

    # 6. Simulate live trading loop
    print("\n[6] Simulating live trading loop...")

    n_simulation_steps = 100
    for i in range(n_simulation_steps):
        # Get observation from data pipeline
        obs = env._get_observation()

        # Get trading decision
        action = bundle.get_action(
            observation=obs,
            portfolio_state={
                "equity": env.equity,
                "position": env.position,
            },
            use_rl=True,
            use_online=False,  # ยังไม่มีข้อมูลพอสำหรับ online
        )

        # Simulate market step
        env.step(action)

        # Online update (with mock label)
        features = bundle._extract_features(obs)
        # Mock label: 1 if price went up, 0 if down
        price_change = 1 if np.random.random() > 0.5 else 0
        bundle.online_update(
            x=features,
            y=price_change,
            symbol="BTCUSDT",
        )

        if i % 20 == 0:
            metrics = env.get_metrics()
            print(f"    Step {i}: Equity={env.equity:.2f}, PnL={metrics.total_pnl:.2f}, "
                  f"Trades={metrics.num_trades}, Action={action}")

    # 7. Final report
    print("\n[7] Final Report...")
    report = bundle.get_report()

    print(f"\n    RL Algorithm: {report['components']['rl_ready']}")
    print(f"    Online Ready: {report['components']['online_ready']}")
    print(f"    HPO Ready: {report['components']['hpo_ready']}")

    if 'performance_summary' in report:
        summary = report['performance_summary']
        print(f"\n    Total Online Updates: {summary['total_updates']}")
        print(f"    Mean Error: {summary['mean_error']:.4f}")
        print(f"    Drift Events: {summary['drift_events']}")

    # 8. Save state
    print("\n[8] Saving bundle state...")
    save_path = bundle.save_state()
    print(f"    Saved to: {save_path}")

    print("\n" + "=" * 60)
    print("Example complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
