"""
agents/ceo_symbol_cache.py — V16 Phase 4B Step 3C: Live CEO Agent
Integration into Multi-Symbol Decision Pipeline

Solves a risk agents/multi_symbol_adapter.py's own module docstring
explicitly flagged and deferred: "CEOAgent's six sub-agents ... hold
small amounts of per-INSTANCE state between calls" — RegimeAnalyst's
`_prev_regime` (regime-change-event detection) and every agent's
`_memory`/`_last` (BaseAgent.run()). Reading those classes confirms
this directly: sharing ONE CEOAgent (and therefore one set of
sub-agent instances) across BTCUSDT/ETHUSDT/SOLUSDT in a scheduler loop
would compare each symbol's regime against whichever OTHER symbol was
decided most recently, and mix every symbol's report history into the
same `_memory` deque — silently wrong regime-change detection and
signal continuity the moment a second symbol enters the loop.

The fix mirrors execution/execution_coordinator.py's ExecutionCoordinator
.get_manager() pattern exactly (same reason: TradeManager also holds
real per-symbol state) — NOT regime/regime_engine.py's Step 3A
alternative (internal per-symbol-keyed dicts inside one shared
instance). That alternative would require modifying BaseAgent and
RegimeAnalyst (used by every sub-agent) to accept and key on a symbol
parameter — exactly the "rewrite"/"behavioral refactoring" this phase's
brief rules out. A cache of fully-independent CEOAgent instances,
built via the EXISTING agents.build_agent_layer() factory, needs zero
changes to BaseAgent, RegimeAnalyst, or any of the six sub-agent
classes.

One CEOAgent per symbol means each symbol's sub-agents keep their own
`_prev_regime`/`_memory`/`_last` — genuinely isolated, not shared and
reset, and not fabricated per-symbol state where none was tracked
before.
"""
from __future__ import annotations

import threading

from agents import build_agent_layer
from agents.ceo_agent import CEOAgent
from agents.multi_symbol_adapter import MultiSymbolCEOAdapter
from utils.logger import get_logger

logger = get_logger(__name__)


class CEOAgentSymbolCache:
    """Lazily builds and caches one full agent layer (all six sub-agents
    + CEOAgent) per symbol, via the existing build_agent_layer() factory
    — no new agent-construction logic. O(1) dict lookup on the
    cache-hit path; construction only happens once per symbol for the
    life of this cache (singleton-per-symbol, no duplicates) — matching
    ExecutionCoordinator.get_manager()'s own complexity guarantee,
    which this phase's "linear scaling" / "no duplicate computation"
    requirement is the same shape of promise as.
    """

    def __init__(self, risk_engine=None, journal=None) -> None:
        # Passed straight through to build_agent_layer() for every
        # symbol's CEOAgent — risk_engine/journal are account-wide, not
        # per-symbol, so sharing them across every symbol's CEOAgent is
        # correct (unlike the sub-agents' _memory/_prev_regime, neither
        # of these holds per-symbol decision state).
        self._risk_engine = risk_engine
        self._journal = journal
        self._agents_by_symbol: dict[str, dict] = {}
        self._lock = threading.RLock()
        logger.info("CEOAgentSymbolCache ready")

    def get_ceo_agent(self, symbol: str) -> CEOAgent:
        """Return the CEOAgent for `symbol`, creating and caching its
        full agent layer on first use."""
        layer = self._agents_by_symbol.get(symbol)
        if layer is not None:
            return layer["ceo"]

        with self._lock:
            # re-check inside the lock in case another thread won the race
            layer = self._agents_by_symbol.get(symbol)
            if layer is None:
                layer = build_agent_layer(risk_engine=self._risk_engine, journal=self._journal)
                self._agents_by_symbol[symbol] = layer
                logger.info(f"CEOAgentSymbolCache: built new agent layer for {symbol}")
        return layer["ceo"]

    def get_agent_layer(self, symbol: str) -> dict:
        """Full dict (all six sub-agents + 'ceo') for `symbol` — mainly
        for tests/introspection; get_ceo_agent() is the normal call
        site."""
        self.get_ceo_agent(symbol)  # ensures it's built
        return self._agents_by_symbol[symbol]

    @property
    def cached_symbols(self) -> list[str]:
        return list(self._agents_by_symbol.keys())

    def __len__(self) -> int:
        return len(self._agents_by_symbol)


class MultiSymbolCEODispatcher:
    """Combines a CEOAgentSymbolCache with a shared signal_provider to
    expose agents/multi_symbol_adapter.py's MultiSymbolCEOAdapter exact
    decide()/decide_with_signal() duck-type — but routing each symbol
    to ITS OWN isolated CEOAgent (via the cache) instead of one shared
    instance. This is what execution/ceo_gated_signal_provider.py's
    CEOGatedSignalProvider actually holds as its `ceo_adapter` in
    production; that class needed zero changes to accept it, since it
    only ever calls `.decide_with_signal(symbol)`.

    Constructing a fresh MultiSymbolCEOAdapter per call is intentional,
    not a missed caching opportunity: that class is two attribute
    assignments with no setup (confirmed by reading its __init__) — the
    CEOAgent underneath (from CEOAgentSymbolCache, which IS cached and
    IS expensive to build) is the only thing worth caching.
    """

    def __init__(self, signal_provider, ceo_agent_cache: CEOAgentSymbolCache) -> None:
        self.signal_provider = signal_provider
        self.ceo_agent_cache = ceo_agent_cache

    def decide(self, symbol: str, **kwargs):
        decision, _signal = self.decide_with_signal(symbol, **kwargs)
        return decision

    def decide_with_signal(self, symbol: str, **kwargs):
        ceo_agent = self.ceo_agent_cache.get_ceo_agent(symbol)
        adapter = MultiSymbolCEOAdapter(signal_provider=self.signal_provider, ceo_agent=ceo_agent)
        return adapter.decide_with_signal(symbol, **kwargs)

    def __call__(self, symbol: str):
        return self.decide(symbol)
