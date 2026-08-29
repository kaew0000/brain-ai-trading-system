"""
SystemIntegrator — single wiring point for the ML Extensions
Integration Layer (observe-only, this phase).

wire_all() is the one-call entry point the original task brief
(PROMPT_FOR_CLAUDE.md) asked for, adapted to this repo's real bootstrap
shape: main.py's main() is a procedural function that builds a
components dict (agent_layer = build_agent_layer(...), no BrainBot
class exists anywhere in this repo) — not the `class BrainBot:
__init__/start()` the original draft assumed. See main.py's own call
site (searched "# ── ML Extensions Integration" there) for how this is
actually invoked.

Every optional/heavy import (ExtensionsOrchestrator, and therefore
ml/extensions/'s gymnasium/stable-baselines3/torch/river/optuna stack)
is deferred inside wire_all()/​_build_data_adapter(), never at this
module's top level. This module also deliberately lives at
ml/extensions_integration/ — a sibling of ml/extensions/, not a child
of it — because ml/extensions/__init__.py itself eagerly imports that
whole optional stack; see this package's own __init__.py docstring for
the full reasoning. Between the two, `import ml.extensions_integration`
never requires those optional dependencies to be installed. Only
calling wire_all() does, and only when ML_EXTENSIONS_ENABLED=true.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .config_bridge import ConfigBridge
from .data_adapter import RLDataPipelineAdapter
from .ml_extensions_agent import MLExtensionsAgent
from .portfolio_adapter import PortfolioStateAdapter

logger = logging.getLogger(__name__)


class SystemIntegrator:
    """Builds and registers the ML Extensions observe-only agent.

    Never raises — wire_all() always returns a components dict (with
    "enabled": False on any failure or when the feature flag is off),
    matching the non-fatal best-effort pattern main.py already uses for
    every other optional subsystem (ExecutionScheduler,
    TrainingLaneRunner, ...).
    """

    def __init__(
        self,
        ceo_agent: Optional[Any] = None,           # agents.ceo_agent.CEOAgent
        data_provider: Optional[Any] = None,        # data.binance_provider.BinanceDataProvider
        portfolio_state: Optional[Any] = None,       # portfolio.portfolio_state.PortfolioState
        historical_ohlcv: Optional[Any] = None,      # pre-loaded pandas.DataFrame, optional
        timeframe: str = "15m",
        history_limit: int = 500,
    ) -> None:
        self.ceo_agent = ceo_agent
        self.data_provider = data_provider
        self.portfolio_state = portfolio_state
        self.historical_ohlcv = historical_ohlcv
        self.timeframe = timeframe
        self.history_limit = history_limit

    def wire_all(self) -> dict:
        if not ConfigBridge.is_enabled():
            logger.info("ML Extensions integration: ML_EXTENSIONS_ENABLED=false — not wired.")
            return {"enabled": False}

        try:
            from ml.extensions.orchestrator import ExtensionsOrchestrator

            data_adapter = self._build_data_adapter()
            portfolio_adapter = PortfolioStateAdapter(
                portfolio_state=self.portfolio_state,
                data_provider=self.data_provider,
            )
            extensions_config = ConfigBridge.build_extensions_config()
            orchestrator = ExtensionsOrchestrator(config=extensions_config)

            ml_agent = MLExtensionsAgent(
                orchestrator=orchestrator,
                data_adapter=data_adapter,
                portfolio_adapter=portfolio_adapter,
            )

            if self.ceo_agent is not None:
                # Safe: "ml_extensions" is not a CEOAgent.WEIGHTS key —
                # see ml_extensions_agent.py's module docstring for why
                # this cannot influence LONG/SHORT/WAIT.
                self.ceo_agent.register_agent("ml_extensions", ml_agent)
                logger.info("ML Extensions: MLExtensionsAgent registered with CEOAgent (observe-only).")
            else:
                logger.warning("ML Extensions: no ceo_agent provided — agent built but not registered.")

            return {
                "enabled": True,
                "orchestrator": orchestrator,
                "data_adapter": data_adapter,
                "portfolio_adapter": portfolio_adapter,
                "agent": ml_agent,
                "config": extensions_config,
            }
        except Exception as exc:
            logger.error(f"ML Extensions integration failed to wire (non-fatal): {exc}")
            return {"enabled": False, "error": str(exc)}

    def _build_data_adapter(self) -> Optional[RLDataPipelineAdapter]:
        if self.historical_ohlcv is not None:
            return RLDataPipelineAdapter(self.historical_ohlcv)
        if self.data_provider is not None:
            symbol = ConfigBridge.default_symbols()[0]
            return RLDataPipelineAdapter.from_provider(
                self.data_provider,
                timeframe=self.timeframe,
                limit=self.history_limit,
                symbol=symbol,
            )
        logger.warning("ML Extensions: no data source provided — data_adapter unavailable.")
        return None
