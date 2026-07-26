"""
agents/decision_context.py — V16 Phase 4B Step 3B: CEO Decision Context
+ Multi-Symbol Signal Integration

CEODecisionContext (Part A) is a pure data container — the single
input Part D's adapter builds and hands to CEOAgent.decide_from_context()
(agents/ceo_agent.py). It does not change what CEOAgent.decide() does;
`decide_from_context()` is a thin compatibility wrapper that unpacks
`market_context`/`confidence_result` and calls the existing decide()
unchanged (see ceo_agent.py). `portfolio_state`, `existing_positions`,
and `risk_snapshot` are carried on this context for a FUTURE phase to
consume — this phase deliberately does not wire them into any scoring/
voting logic ("preserve existing vote logic... Only replace the input
interface" — this phase's own brief). Populating them here is
groundwork, not a behavior change.

Frozen (immutable) as Part A requires. `existing_positions` is stored
as a tuple rather than a list for the same reason: a frozen dataclass
can still hold a mutable list whose *contents* a caller mutates later,
which isn't real immutability — a tuple can't be appended/removed from
after construction.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CEODecisionContext:
    """
    symbol : which symbol this context is for. Should always agree with
        `market_context.get("symbol")` — the adapter that builds this
        (agents/multi_symbol_adapter.py) guarantees that; this class
        itself does not validate or reconcile the two (no new
        validation-failure behavior introduced by this phase). The
        actual CEODecision.symbol on the result still comes from
        `market_context["symbol"]` via the existing decide() logic,
        unchanged — this field is a convenience for the caller, not a
        second source of truth decide() reads from.
    market_context : the same dict execution/portfolio_signal_provider.py's
        PortfolioSignalProvider already built via MarketContextBuilder —
        passed through, never rebuilt (Part B).
    confidence_result : the same ConfidenceResult PortfolioSignalProvider
        already computed via ConfidenceEngine.score() — passed through,
        never rebuilt (Part B). None is valid (CEOAgent.decide() already
        treats a missing confidence_result as "no ConfidenceEngine
        opinion this cycle", same as every pre-existing single-symbol
        caller that doesn't have one yet).
    portfolio_state : execution.portfolio_state.PortfolioState instance
        (or compatible), if the caller has one. NOT consumed by
        decide_from_context() in this phase — see module docstring.
    existing_positions : this symbol's currently-open position(s), if
        any, as an immutable tuple. NOT consumed in this phase.
    risk_snapshot : whatever risk-level facts (e.g. risk.risk_engine
        output) the caller has for this cycle, if any. NOT consumed in
        this phase.
    """

    symbol:             str
    market_context:     dict
    confidence_result:  Any | None = None
    portfolio_state:    Any | None = None
    existing_positions: tuple = field(default_factory=tuple)
    risk_snapshot:       dict | None = None
