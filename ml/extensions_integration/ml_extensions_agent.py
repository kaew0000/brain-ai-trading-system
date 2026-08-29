"""
MLExtensionsAgent — BaseAgent-conformant, observe-only wrapper around
ml.extensions.orchestrator.ExtensionsOrchestrator (PR #82: RL/HPO/
Online-Learning).

V16 ML Extensions Integration Layer (this phase). Meant to be
registered into CEOAgent's `_agents` dict under the key "ml_extensions"
— a key that does NOT appear in CEOAgent.WEIGHTS (agents/ceo_agent.py).

Confirmed by reading CEOAgent.decide(): the weighted-vote loop only
ever iterates `weights.items()` (== CEOAgent.WEIGHTS, or its
dynamic-blend variant — which is itself only ever derived from
WEIGHTS' own keys via _effective_weights()). An agent registered under
a key that isn't in WEIGHTS still runs every cycle — telemetry, the
reasoning stream, and the dashboard's agent_reports all pick it up via
BaseAgent.run() — but its signal/confidence can never enter
long_score/short_score and can never change `action`. This codebase
already relies on exactly this pattern for "trader"
(agents/__init__.py's build_agent_layer() registers "trader" with
CEOAgent, and "trader" is likewise absent from WEIGHTS) — this is not a
new trick, it's the existing convention, reused here deliberately.

Wiring ml_extensions into the actual weighted vote (giving it real
influence over LONG/SHORT/WAIT) is intentionally NOT part of this
phase — see PATCH_NOTES.md. Doing so means editing CEOAgent.WEIGHTS (a
rebalance of production decision weights) and is scoped as separate,
explicitly human-approved future work, consistent with this project's
existing governance-gated pattern for anything that can move real
capital.

Safety note: CEOAgent.decide() already wraps every agent's run() call
in its own try/except, so a bug here cannot break the trading decision
even without this file's own defensiveness. This agent is still
internally defensive (analyse() never raises) as a second, independent
safety net — belt and suspenders, matching this codebase's own house
style (see e.g. portfolio/portfolio_manager.py's _persist()).
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np

from agents.base_agent import AgentReport, BaseAgent

_ACTION_TO_SIGNAL = {0: "NEUTRAL", 1: "LONG", 2: "SHORT"}


class MLExtensionsAgent(BaseAgent):
    """Observe-only AI employee reporting what RL/Online/HPO would have
    signalled, for dashboard visibility only — never wired into the
    weighted vote that actually decides LONG/SHORT/WAIT (see module
    docstring)."""

    AGENT_NAME = "ML_EXTENSIONS"

    def __init__(
        self,
        orchestrator: Optional[Any] = None,        # ml.extensions.orchestrator.ExtensionsOrchestrator
        data_adapter: Optional[Any] = None,         # RLDataPipelineAdapter
        portfolio_adapter: Optional[Any] = None,    # PortfolioStateAdapter
        lookback: int = 50,
    ) -> None:
        super().__init__()
        self.orchestrator = orchestrator
        self.data_adapter = data_adapter
        self.portfolio_adapter = portfolio_adapter
        self.lookback = lookback

    def analyse(self, market_context: dict) -> AgentReport:
        symbol = market_context.get("symbol") if market_context else None

        if self.orchestrator is None or self.data_adapter is None:
            return AgentReport(
                agent=self.AGENT_NAME,
                signal="NEUTRAL",
                confidence=0.0,
                summary="ML Extensions: not wired (observe-only, no live effect)",
                raw={"status": "not_ready"},
                symbol=symbol,
            )

        try:
            observation = {
                "market_features": self.data_adapter.get_features(self.lookback),
                "portfolio_state": np.zeros(6, dtype=np.float32),
                "recent_returns": np.zeros(20, dtype=np.float32),
            }
            portfolio_state = (
                self.portfolio_adapter.get_state_for_rl()
                if self.portfolio_adapter is not None else None
            )
            action = self.orchestrator.get_action(
                observation,
                portfolio_state=portfolio_state,
                symbol=symbol,
            )
            signal = _ACTION_TO_SIGNAL.get(int(action), "NEUTRAL")
            return AgentReport(
                agent=self.AGENT_NAME,
                signal=signal,
                # ExtensionsOrchestrator.get_action() returns a discrete
                # action, not a calibrated probability — 50.0 is a
                # deliberately neutral placeholder, not a real estimate.
                # Harmless: this key is not in CEOAgent.WEIGHTS, so it
                # cannot affect any real decision either way.
                confidence=50.0,
                summary=f"ML Extensions (observe-only): would signal {signal}",
                raw={"status": "ok", "action": int(action)},
                symbol=symbol,
            )
        except Exception as exc:
            self._logger.warning(f"MLExtensionsAgent.analyse failed (non-fatal): {exc}")
            return AgentReport(
                agent=self.AGENT_NAME,
                signal="NEUTRAL",
                confidence=0.0,
                summary=f"ML Extensions: signal unavailable ({exc})",
                raw={"status": "error", "error": str(exc)},
                symbol=symbol,
            )
