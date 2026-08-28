# Brain AI Extensions Bundle

Bundle สำหรับเพิ่มความสามารถให้ **Brain AI Trading System** เรียนรู้และปรับปรุงตัวเองได้อัตโนมัติ

## ส่วนประกอบหลัก

### 1. Stable-Baselines3 (RL Adapter)
- **ไฟล์:** `rl_adapter.py`
- **หน้าที่:** ให้ระบบเรียนรู้จาก PnL จริงผ่าน Reinforcement Learning
- **รองรับ:** PPO, SAC, A2C
- **Reward Shaping:** PnL + Sharpe + Drawdown penalty + Over-trading penalty

### 2. River (Online Learning)
- **ไฟล์:** `online_learning.py`
- **หน้าที่:** อัปเดตโมเดลแบบ real-time ทีละตัวอย่าง
- **รองรับ:** Classification/Regression, Concept Drift Detection (ADWIN), Experience Replay

### 3. Optuna (HPO Manager)
- **ไฟล์:** `hpo_manager.py`
- **หน้าที่:** ปรับ hyperparameters อัตโนมัติ
- **รองรับ:** Single-objective, Multi-objective (Pareto), Distributed optimization

## การติดตั้ง

```bash
cd brain_ai_extensions
pip install -r requirements.txt
```

## การใช้งานแบบ Step-by-Step

### ขั้นตอนที่ 1: สร้าง Bundle

```python
from brain_ai_extensions import BundleManager, BundleConfig

config = BundleConfig(
    symbols=["BTCUSDT", "ETHUSDT"],
    rl_algorithm="PPO",
    mode="paper",
)

bundle = BundleManager(
    config=config,
    data_pipeline=your_data_pipeline,  # Brain Bot data pipeline
    strategy_fn=your_strategy_factory,  # fn(params) -> strategy
    backtest_fn=your_backtest_function,  # fn(strategy) -> metrics
)
```

### ขั้นตอนที่ 2: Optimize Strategy Parameters

```python
# ใช้ Optuna หาค่าพารามิเตอร์ที่ดีที่สุด
results = bundle.optimize_strategy(
    n_trials=50,
    objective_metric="sharpe_ratio",
)

print(f"Best params: {results['best_params']}")
print(f"Best score: {results['best_score']}")
```

### ขั้นตอนที่ 3: Train RL Agent

```python
# สร้าง trading environment
env = bundle.setup_trading_env()

# Train RL agent
history = bundle.train_rl(total_timesteps=100000)

# หรือโหลด model ที่เคย train ไว้
bundle.load_rl_model("models/rl/best_model.zip")
```

### ขั้นตอนที่ 4: Start Online Learning

```python
# เริ่ม online learning สำหรับ adaptation แบบ real-time
bundle.setup_online_learning()

# หรือ start background thread
bundle.start_online_learning()
```

### ขั้นตอนที่ 5: Get Trading Decisions

```python
# รวมผลจากทุก component
action = bundle.get_action(
    observation=obs,
    portfolio_state={"equity": 10000, "position": 0},
    symbol="BTCUSDT",
    use_rl=True,
    use_online=True,
)
# action: 0=HOLD, 1=BUY, 2=SELL
```

### Online Update (สำหรับ Live Trading)

```python
# อัปเดต online learner ทีละตัวอย่าง
result = bundle.online_update(
    x={"rsi": 65, "macd": 0.5, "volume": 1000},
    y=1,  # 1 = ขึ้น (สำหรับ classification)
    symbol="BTCUSDT",
)

print(f"Prediction: {result['prediction']}")
print(f"Drift detected: {result['drift_detected']}")
```

## โครงสร้างไฟล์

```
brain_ai_extensions/
├── __init__.py           # Package initialization
├── trading_env.py        # Gymnasium Environment
├── rl_adapter.py         # Stable-Baselines3 integration
├── online_learning.py    # River integration
├── hpo_manager.py        # Optuna integration
├── bundle_manager.py     # Main orchestrator
├── requirements.txt      # Dependencies
└── README.md            # This file
```

## การ Integrate เข้า Brain Bot

### 1. วางไฟล์ในโครงสร้างเดิม

```
brain-ai-trading-system/
├── brain/
│   ├── agents/
│   │   └── rl_agent.py          # ใช้ RLAdapter
│   ├── learning/
│   │   └── online_learner.py    # ใช้ OnlineLearner
│   ├── config/
│   │   └── hpo_manager.py       # ใช้ HPOManager
│   └── extensions/              # สร้างใหม่
│       ├── __init__.py
│       ├── trading_env.py
│       ├── rl_adapter.py
│       ├── online_learning.py
│       ├── hpo_manager.py
│       └── bundle_manager.py
```

### 2. แก้ไข Pipeline หลัก

```python
# ใน main.py หรือ decision engine
from brain.extensions import BundleManager

class EnhancedDecisionEngine:
    def __init__(self):
        self.bundle = BundleManager(
            data_pipeline=self.data_pipeline,
            strategy_fn=self.create_strategy,
            backtest_fn=self.run_backtest,
        )

        # 1. Optimize
        self.bundle.optimize_strategy(n_trials=50)

        # 2. Train RL
        self.bundle.train_rl(total_timesteps=50000)

        # 3. Start online learning
        self.bundle.start_online_learning()

    def get_signal(self, market_data):
        obs = self.build_observation(market_data)
        portfolio = self.get_portfolio_state()

        return self.bundle.get_action(
            observation=obs,
            portfolio_state=portfolio,
        )
```

## ตัวอย่าง: Custom Strategy + Backtest

```python
from brain_ai_extensions import ParamSpace, StrategyOptimizer

# 1. สร้าง strategy
class MyStrategy:
    def __init__(self, lookback=20, threshold=0.05, position_size=0.1):
        self.lookback = lookback
        self.threshold = threshold
        self.position_size = position_size

    def generate_signal(self, data):
        returns = data["close"].pct_change(self.lookback)
        if returns.iloc[-1] > self.threshold:
            return 1  # BUY
        elif returns.iloc[-1] < -self.threshold:
            return 2  # SELL
        return 0  # HOLD

# 2. สร้าง factory function
def strategy_factory(lookback, threshold, position_size, **kwargs):
    return MyStrategy(lookback, threshold, position_size)

# 3. สร้าง backtest function
def backtest_strategy(strategy):
    data = load_historical_data()
    portfolio = backtest(data, strategy)
    return {
        "sharpe_ratio": portfolio.sharpe,
        "total_return": portfolio.total_return,
        "max_drawdown": portfolio.max_drawdown,
    }

# 4. ใช้กับ Bundle
bundle = BundleManager(
    strategy_fn=strategy_factory,
    backtest_fn=backtest_strategy,
)

results = bundle.optimize_strategy(
    param_space=StrategyOptimizer.create_momentum_space(),
    n_trials=100,
)
```

## การปรับแต่ง

### Custom Reward Function (RL)

แก้ไขใน `trading_env.py`:

```python
def _calculate_reward(self, action, old_equity):
    # เพิ่ม logic ของคุณเอง
    reward = custom_reward_logic()
    return reward
```

### Custom Online Model

```python
from river import neural_net

config = OnlineModelConfig(
    model_type="custom",
)

# หรือแก้ _build_model() ใน OnlineLearner
```

### Multi-Objective HPO

```python
from brain_ai_extensions import MultiObjectiveOptimizer

optimizer = MultiObjectiveOptimizer(
    objective_fns=[
        lambda p: backtest(p)["return"],      # maximize
        lambda p: -backtest(p)["drawdown"],   # minimize (negative)
        lambda p: backtest(p)["sharpe"],      # maximize
    ],
    param_space=space,
)

pareto_solutions = optimizer.optimize(n_trials=100)
```

## ข้อควรระวัง

1. **RL Training Time:** อาจใช้เวลานาน (หลายชั่วโมง) ขึ้นอยู่กับ `total_timesteps`
2. **Resource Usage:** Online learning ใช้ CPU ต่ำ แต่ RL training อาจใช้ GPU ได้
3. **Overfitting:** ควรมี eval_env แยกต่างหากสำหรับ validation
4. **Safety Guards:** อย่าลืมใช้ `TradingPolicy` ที่มี risk limits

## License

MIT License - ใช้กับ Brain AI Trading System ได้เลย
