"""
ml.extensions_integration — observe-only bridge between ml.extensions/
(PR #82: RL/HPO/Online-Learning) and the rest of Brain Bot V16.

Lives BESIDE ml/extensions/, not inside it, deliberately: ml/extensions/
__init__.py itself eagerly imports .rl/.online/.hpo/.orchestrator at
module load — despite that module's own docstring claiming otherwise
("none of these optional dependencies are imported unless this
subpackage is explicitly used"), any `import ml.extensions.<anything>`
executes that __init__.py first and pulls in gymnasium/
stable-baselines3/torch/river/optuna immediately. A package living
*inside* ml/extensions/ inherits that eagerness for free, with no way
to opt out of it — confirmed the hard way: this layer originally lived
at ml/extensions/integration/, and CI (which correctly does not
install ml/extensions/'s optional dependencies, since they're not in
the base requirements.txt) failed to even collect any of this layer's
test files as a result. Moving it here, as a sibling package under ml/
instead of a child of ml.extensions, sidesteps that entirely: nothing
in this package imports anything from ml.extensions at its own top
level (see system_integrator.py's wire_all() / config_bridge.py's
build_extensions_config() for where that import is deferred to), so
`import ml.extensions_integration` always succeeds regardless of
whether those optional packages are installed, and only actually
requires them when wire_all() runs with ML_EXTENSIONS_ENABLED=true.

See system_integrator.py's SystemIntegrator.wire_all() for the one-call
entry point, and ml_extensions_agent.py's module docstring for why this
phase is observe-only: MLExtensionsAgent is registered with CEOAgent
for dashboard visibility, but under a key outside CEOAgent.WEIGHTS, so
it can never move a real trading decision.
"""
from .config_bridge import ConfigBridge
from .data_adapter import FEATURE_NAMES, RLDataPipelineAdapter, compute_feature_frame
from .ml_extensions_agent import MLExtensionsAgent
from .portfolio_adapter import PortfolioStateAdapter
from .system_integrator import SystemIntegrator

__all__ = [
    "ConfigBridge",
    "FEATURE_NAMES",
    "MLExtensionsAgent",
    "PortfolioStateAdapter",
    "RLDataPipelineAdapter",
    "SystemIntegrator",
    "compute_feature_frame",
]
