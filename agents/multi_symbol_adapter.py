"""
agents/multi_symbol_adapter.py — V16 Phase 4B Step 3B: CEO Decision
Context + Multi-Symbol Signal Integration

The lightweight bridge Part D asks for:

    PortfolioSignalProvider -> CEODecisionContext -> CEOAgent -> CEODecision

MultiSymbolCEOAdapter.decide(symbol) calls
execution.portfolio_signal_provider.PortfolioSignalProvider.get_signal_with_context()
(Part B) to get the already-computed market_context/confidence_result,
wraps them in a CEODecisionContext (Part A), and calls
agents.ceo_agent.CEOAgent.decide_from_context() (Part C) — never calling
MarketContextBuilder or ConfidenceEngine a second time.

decide_with_signal(symbol) (V16 Phase 4B Step 3C) is the same
computation, additionally returning the underlying priced
ExecutionSignal (SignalWithContext.signal) alongside the CEODecision —
for a caller (execution/ceo_gated_signal_provider.py) that needs to
confirm/veto against the already-computed signal rather than
re-fetching it, which would duplicate the same computation decide()
itself is careful not to duplicate. decide() now delegates to it
internally; behavior is unchanged.

Its responsibility ends the moment it returns a CEODecision. This
module does not execute trades, allocate capital, touch the journal, or
modify portfolio state — none of execution/execution_orchestrator.py,
execution/execution_coordinator.py, portfolio/portfolio_manager.py, or
journal/ are imported here (only execution/portfolio_signal_provider.py,
for its get_signal_with_context() method — a read, not an execution
call). Wiring this adapter into main.py's live ExecutionScheduler
bootstrap — i.e. making it the multi-symbol path's actual signal_provider
instead of a bare PortfolioSignalProvider — is explicitly deferred to a
future phase; this phase "prepares integration only," per its own brief.

Discovery worth flagging here (not fixed, not this phase's scope):
CEOAgent's six sub-agents (agents/regime_analyst.py etc.) hold small
amounts of per-INSTANCE state between calls — e.g. RegimeAnalyst's
`_prev_regime` (regime-change-event detection) and every agent's
`_memory`/`_last` (BaseAgent.run()). That's fine for today's single
CEOAgent servicing one symbol. If a FUTURE phase reuses ONE CEOAgent
(and therefore one set of sub-agent instances) across MULTIPLE symbols
in a scheduler loop — which this adapter's design doesn't itself do or
require, but a caller COULD construct it that way — that per-instance
state will reflect whichever symbol was decided most recently, not a
per-symbol history. Worth a decision (fresh CEOAgent per symbol? give
sub-agents per-symbol state, mirroring regime/regime_engine.py's own
Phase 4B Step 3A fix?) before any phase wires multi-symbol scheduling
through a SHARED CEOAgent — not addressed here.
"""
from __future__ import annotations

from agents.decision_context import CEODecisionContext
from utils.logger import get_logger

logger = get_logger(__name__)


class MultiSymbolCEOAdapter:
    """Construct once with the SAME PortfolioSignalProvider/CEOAgent
    instances a scheduler-style caller already has (same
    dependency-injection idiom as PortfolioSignalProvider(data_provider=...)
    / ExecutionOrchestrator(execution_engine=..., ...) elsewhere in this
    codebase) — call decide(symbol) once per symbol per cycle.

    O(1) work per symbol beyond what signal_provider.get_signal_with_context()
    already does (one dict construction, one decide_from_context() call)
    — calling this for N symbols is O(N), never worse, matching this
    phase's "linear complexity" requirement.
    """

    def __init__(self, signal_provider, ceo_agent) -> None:
        # Duck-typed on purpose (not type-hinted to the concrete classes):
        # signal_provider needs only get_signal_with_context(symbol);
        # ceo_agent needs only decide_from_context(context). Keeps this
        # adapter trivially testable with fakes, same convention as
        # execution/execution_orchestrator.py's tests.
        self.signal_provider = signal_provider
        self.ceo_agent = ceo_agent

    def decide(
        self,
        symbol: str,
        portfolio_state=None,
        existing_positions=None,
        risk_snapshot=None,
    ):
        """Returns a CEODecision, or None when signal_provider itself has
        nothing usable for `symbol` this cycle (e.g. incomplete OHLCV,
        no MTF consensus) — same "no signal" semantics
        PortfolioSignalProvider.get_signal_with_context() already has.
        Never raises: a single bad symbol must not be able to break a
        caller looping over many symbols in one cycle, matching this
        project's "safety wrapping at every touchpoint" rule (see e.g.
        PortfolioSignalProvider.get_signal()'s own docstring)."""
        decision, _signal = self.decide_with_signal(
            symbol, portfolio_state=portfolio_state,
            existing_positions=existing_positions, risk_snapshot=risk_snapshot,
        )
        return decision

    def decide_with_signal(
        self,
        symbol: str,
        portfolio_state=None,
        existing_positions=None,
        risk_snapshot=None,
    ):
        """V16 Phase 4B Step 3C: same computation as decide(), but also
        returns the already-priced ExecutionSignal
        (SignalWithContext.signal) the CEODecision was reasoned about —
        for a caller (execution/ceo_gated_signal_provider.py) that needs
        BOTH without calling signal_provider.get_signal_with_context()
        a second time, which would duplicate the MarketContextBuilder/
        ConfidenceEngine/RegimeEngine computation get_signal_with_context()
        already did once. Returns (None, None) under the same "nothing
        usable this cycle" conditions decide() returns None for. Never
        raises, same reasoning as decide()."""
        try:
            result = self.signal_provider.get_signal_with_context(symbol)
        except Exception as exc:
            logger.error(f"MultiSymbolCEOAdapter: signal computation failed for {symbol}: {exc}")
            return None, None
        if result is None:
            return None, None

        context = CEODecisionContext(
            symbol=symbol,
            market_context=result.market_context,
            confidence_result=result.confidence_result,
            portfolio_state=portfolio_state,
            existing_positions=tuple(existing_positions) if existing_positions else (),
            risk_snapshot=risk_snapshot,
        )

        try:
            decision = self.ceo_agent.decide_from_context(context)
        except Exception as exc:
            logger.error(f"MultiSymbolCEOAdapter: CEOAgent.decide_from_context failed for {symbol}: {exc}")
            return None, None

        return decision, result.signal

    def __call__(self, symbol: str, **kwargs):
        return self.decide(symbol, **kwargs)
