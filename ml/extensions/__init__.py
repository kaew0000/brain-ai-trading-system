"""
ml.extensions — Brain AI Extensions
====================================
Adds Stable-Baselines3 (RL), River (online/incremental learning), and Optuna
(hyperparameter optimization) on top of the existing ml/ and learning/
pipelines.

This subpackage is additive and isolated: nothing in ml/ or learning/ is
modified, and none of these optional dependencies are imported unless this
subpackage is explicitly used. See ml/extensions/requirements.txt for the
extra dependencies this subpackage requires (not part of the base
requirements.txt).

Usage:
    from ml.extensions import ExtensionsOrchestrator, ExtensionsConfig

Note: this was previously distributed as a standalone `bundle_manager.py`
with a `BundleManager` class. Both were renamed (-> orchestrator.py /
ExtensionsOrchestrator, ExtensionsConfig) to avoid confusion with
`tools/bundle_manager.py`, which is the unrelated git-bundle deployment
tool used by this project's update workflow.
"""

from .rl import BrainTradingEnv, RLAdapter, TradingPolicy
from .online import OnlineLearner, OnlineModelConfig, MultiSymbolOnlineLearner
from .hpo import HPOManager, HPOConfig, ParamSpace, StrategyOptimizer, MultiObjectiveOptimizer
from .orchestrator import ExtensionsOrchestrator, ExtensionsConfig

__version__ = "1.0.0"
__all__ = [
    "BrainTradingEnv",
    "RLAdapter",
    "TradingPolicy",
    "OnlineLearner",
    "OnlineModelConfig",
    "MultiSymbolOnlineLearner",
    "HPOManager",
    "HPOConfig",
    "ParamSpace",
    "StrategyOptimizer",
    "MultiObjectiveOptimizer",
    "ExtensionsOrchestrator",
    "ExtensionsConfig",
]
