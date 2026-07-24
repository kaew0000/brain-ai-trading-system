"""
agents/ — AI Employee Layer
"""
from .base_agent      import BaseAgent, AgentReport
from .smc_analyst     import SMCAnalyst
from .futures_analyst import FuturesAnalyst
from .regime_analyst  import RegimeAnalyst
from .risk_manager    import RiskManagerAgent
from .trader_agent    import TraderAgent
from .journal_analyst import JournalAnalyst
from .ceo_agent       import CEOAgent, CEODecision


def build_agent_layer(risk_engine=None, journal=None) -> dict:
    smc     = SMCAnalyst()
    futures = FuturesAnalyst()
    regime  = RegimeAnalyst()
    risk    = RiskManagerAgent(risk_engine=risk_engine, journal=journal)
    trader  = TraderAgent()
    journal_agent = JournalAnalyst(journal=journal)
    ceo = CEOAgent(agents={
        "smc": smc, "futures": futures, "regime": regime,
        "risk": risk, "trader": trader, "journal": journal_agent,
    }, journal=journal)
    return {"smc": smc, "futures": futures, "regime": regime,
            "risk": risk, "trader": trader, "journal": journal_agent, "ceo": ceo}


__all__ = [
    "AgentReport",
    "BaseAgent",
    "CEOAgent",
    "CEODecision",
    "FuturesAnalyst",
    "JournalAnalyst",
    "RegimeAnalyst",
    "RiskManagerAgent",
    "SMCAnalyst",
    "TraderAgent",
    "build_agent_layer",
]
