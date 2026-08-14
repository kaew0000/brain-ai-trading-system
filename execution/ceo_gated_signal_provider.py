"""
execution/ceo_gated_signal_provider.py — V16 Phase 4B Step 3C: Live CEO
Agent Integration into Multi-Symbol Decision Pipeline

Target pipeline (this phase's brief):
    PortfolioSignalProvider -> SignalWithContext -> MultiSymbolCEOAdapter
    -> CEOAgent -> CEODecision -> Execution Decision -> Trade Execution

This class IS that "Execution Decision" step, and is a drop-in
replacement for a bare PortfolioSignalProvider in
execution/execution_orchestrator.py's ExecutionOrchestrator.signal_provider
slot — it implements the exact same
SignalProvider = Callable[[str], ExecutionSignal | None] contract
(execution_orchestrator.py) unchanged. Zero changes to
ExecutionOrchestrator itself: "Execution order must remain unchanged"
(this phase's brief) is satisfied by construction, not by care taken
inside execute() — execute() has no idea this wrapper exists.

Part A — why CEO can only confirm or veto, never invent a trade
------------------------------------------------------------------------
agents/ceo_agent.py's CEODecision carries action/direction/confidence/
reasons — it does NOT carry entry_price/stop_loss/take_profit (reading
that dataclass confirms this, not assumed). Those prices only exist on
the ExecutionSignal PortfolioSignalProvider's existing ConfidenceEngine-
based pipeline already computed. So "CEOAgent becomes the final decision
authority before execution" (this phase's brief) can only mean: CEOAgent
confirms or vetoes the ALREADY-PRICED signal, never independently
manufactures a new one with prices it has no way to compute. Building
independent CEO-sourced price-level logic would be inventing decision
logic this phase's brief explicitly rules out ("No behavioral
refactoring. Only integrate the already-built CEO pipeline.").

Part B — centralized decision mapping
------------------------------------------------------------------------
The brief's own mapping table names a "REJECT" action. Reading
agents/ceo_agent.py's decide()/decide_from_context() confirms CEOAgent
can only ever produce exactly four actions: LONG, SHORT, WAIT, BLOCKED
— there is no REJECT anywhere in that class. map_ceo_decision_to_signal()
below uses the real fourth action, BLOCKED, for the "cancel candidate"
case the brief's REJECT was describing.

    CEODecision.action  | underlying_signal | -> ExecutionSignal
    --------------------|-------------------|-------------------
    BLOCKED             | (irrelevant)       | None  (hard veto)
    WAIT                | (irrelevant)       | None  (skip)
    LONG                | None               | None  (nothing to confirm)
    LONG                | direction=1        | underlying_signal (confirmed)
    LONG                | direction=-1       | None  (CEO disagrees -> veto)
    SHORT               | (mirror of LONG)   | (mirror of LONG)

This is the ONE place this mapping is computed — no duplicated decision
logic anywhere else in this module or its callers.

Part C — feature flag
------------------------------------------------------------------------
settings.CEO_MULTI_SYMBOL_ENABLED, default False. False:
get_signal(symbol) delegates straight to the wrapped
PortfolioSignalProvider.get_signal(symbol) — byte-identical to every
call site that existed before this phase (see this module's own tests
verifying byte-identical output against a pre-phase baseline). True:
routes through MultiSymbolCEOAdapter.decide_with_signal() and the
mapping above.

Part E — journal (optional, best-effort, non-fatal)
------------------------------------------------------------------------
"Do NOT redesign the journal. Simply include ceo_action, ceo_confidence,
ceo_reason when available." journal/journal_v2.py's TradeJournalV2
already has save_agent_decision(agent, decision, symbol, score, details,
signal_id) (Phase 4B Step 1's own per-agent attribution table,
agent_decisions) — a perfect, zero-schema-change fit: agent="CEO_AGENT"
(CEOAgent.AGENT_NAME), decision=ceo_decision.action, score=confidence,
details={"reasons": ..., "agreement_score": ...}. No new table, no
schema change. If CEO is disabled, or no journal was supplied, nothing
is stored — matches the brief exactly. A journal-write failure is
logged and never raised, matching TradeJournalV2/portfolio_history's
own "persistence failure must never take down the decision cycle"
convention.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from agents.multi_symbol_adapter import MultiSymbolCEOAdapter
from execution.execution_orchestrator import ExecutionSignal
from execution.portfolio_signal_provider import PortfolioSignalProvider
from journal.trade_attribution import agent_attribution_from_ceo_decision
from utils.logger import get_logger

logger = get_logger(__name__)


def map_ceo_decision_to_signal(
    ceo_decision,                              # agents.ceo_agent.CEODecision | None
    underlying_signal: Optional[ExecutionSignal],
) -> Optional[ExecutionSignal]:
    """Part B — the ONE centralized CEO-action -> execution-decision
    mapping. See module docstring's table. Pure function, no I/O, no
    side effects — safe to call from tests or a dashboard "what would
    this decision have done" preview without touching anything live."""
    if ceo_decision is None:
        return None
    if ceo_decision.action in ("BLOCKED", "WAIT"):
        return None
    if underlying_signal is None:
        return None  # nothing priced to confirm, regardless of CEO's own vote

    ceo_direction = 1 if ceo_decision.action == "LONG" else -1 if ceo_decision.action == "SHORT" else 0
    if ceo_direction == 0:
        # Not one of the four known actions — treat as a veto rather
        # than guessing; never execute on an action this mapping
        # doesn't recognize.
        logger.warning(f"map_ceo_decision_to_signal: unrecognized CEO action {ceo_decision.action!r} — treating as veto")
        return None

    if ceo_direction == underlying_signal.direction:
        return underlying_signal
    return None  # CEO disagrees with the already-priced direction -> veto


class CEOGatedSignalProvider:
    """Callable matching execution/execution_orchestrator.py's
    SignalProvider contract exactly — construct once, pass directly as
    ExecutionOrchestrator(signal_provider=...). See module docstring
    for the full design.
    """

    def __init__(
        self,
        signal_provider: PortfolioSignalProvider,
        ceo_adapter: MultiSymbolCEOAdapter,
        journal=None,
        enabled: Optional[bool] = None,
        recommendation_provider=None,
        dataset_row_count_provider=None,
    ) -> None:
        self.signal_provider = signal_provider
        self.ceo_adapter = ceo_adapter
        self.journal = journal
        # None (default) means "read settings.CEO_MULTI_SYMBOL_ENABLED
        # live on every call" — so flipping the setting at runtime takes
        # effect on the next cycle without reconstructing this object.
        # An explicit True/False (mainly for tests) pins the behavior
        # regardless of settings.
        self._enabled_override = enabled
        # V16 Phase 4C Step 4 (live scheduler wiring): optional zero-arg
        # callable returning the current `list[Recommendation]` — main.py
        # wires this to `lambda: api.app.get_state("learning_recommendations",
        # [])` in production. Kept as an injected callable (not a direct
        # api.app import here) so this module stays independently
        # testable with a fake, same idiom as every other dependency in
        # this constructor. None (default) means "never pass
        # recommendations to the CEO adapter" — byte-identical to this
        # class's pre-Step-4 behavior, regardless of
        # RECOMMENDATION_APPLICATION_ENABLED (that flag is checked one
        # layer further down, inside CEOAgent itself).
        self.recommendation_provider = recommendation_provider
        # V16 Phase 4C Step 5 (live recommendation scoring completeness):
        # same idiom as recommendation_provider just above, one call
        # later — optional zero-arg callable returning the current
        # dataset row count (`int | None`). main.py wires this to a
        # reader of `_state["learning_dataset_row_count"]`, the exact
        # value `run_learning_recommendation_refresh()` already writes
        # alongside `learning_recommendations` (Step 4) but that nothing
        # downstream ever read until now. Kept as a SEPARATE provider —
        # not folded into recommendation_provider's return value —
        # because that callable's `-> list[Recommendation]` contract is
        # already established and tested (Step 4); changing its return
        # shape would be a breaking change to an existing, working
        # interface for a value that has nothing to do with what
        # recommendations exist. None (default, byte-identical to
        # pre-Step-5 behavior): no `dataset_row_count` kwarg is ever
        # added, and `recommendation_scoring._coverage_subscore()`
        # keeps its existing, unchanged conservative fallback of 0.0.
        self.dataset_row_count_provider = dataset_row_count_provider
        logger.info(f"CEOGatedSignalProvider ready | enabled_override={enabled}")

    @property
    def enabled(self) -> bool:
        if self._enabled_override is not None:
            return self._enabled_override
        from config.settings import settings
        return settings.CEO_MULTI_SYMBOL_ENABLED

    def get_signal(self, symbol: str) -> Optional[ExecutionSignal]:
        """Part C: the feature flag gate. False -> byte-identical
        passthrough to the wrapped PortfolioSignalProvider.get_signal()
        (this phase's mandatory backward-compatibility requirement).
        True -> CEO-gated pipeline (see module docstring)."""
        if not self.enabled:
            return self.signal_provider.get_signal(symbol)
        return self._get_signal_ceo_enabled(symbol)

    def _get_signal_ceo_enabled(self, symbol: str) -> Optional[ExecutionSignal]:
        # V16 Phase 4C Step 4: only pass a `recommendations=` kwarg through
        # to ceo_adapter.decide_with_signal() when a recommendation_provider
        # was actually configured. Calling with recommendations=None
        # unconditionally would require every ceo_adapter duck-type
        # (including test fakes with the pre-Step-4 decide_with_signal(self,
        # symbol) signature) to accept an extra kwarg it has no reason to
        # know about — this keeps the pre-Step-4 call shape byte-identical
        # whenever recommendation wiring isn't configured, same
        # "byte-identical unless explicitly opted into" contract this
        # class's own module docstring already promises for
        # CEO_MULTI_SYMBOL_ENABLED.
        kwargs = {}
        if self.recommendation_provider is not None:
            try:
                kwargs["recommendations"] = self.recommendation_provider()
            except Exception as exc:
                logger.error(f"CEOGatedSignalProvider: recommendation_provider failed for "
                              f"{symbol}, proceeding without recommendations: {exc}")
        # V16 Phase 4C Step 5: same defensive, opt-in pattern as
        # recommendation_provider immediately above — only added to
        # kwargs when actually configured, so a fake/adapter that
        # doesn't accept a `dataset_row_count` kwarg (e.g. an existing
        # test double, or recommendation_provider configured without
        # this) is never handed one.
        if self.dataset_row_count_provider is not None:
            try:
                kwargs["dataset_row_count"] = self.dataset_row_count_provider()
            except Exception as exc:
                logger.error(f"CEOGatedSignalProvider: dataset_row_count_provider failed for "
                              f"{symbol}, proceeding without dataset_row_count: {exc}")
        try:
            ceo_decision, underlying_signal = self.ceo_adapter.decide_with_signal(symbol, **kwargs)
        except Exception as exc:
            logger.error(f"CEOGatedSignalProvider: CEO decision failed for {symbol}: {exc}")
            return None

        final_signal = map_ceo_decision_to_signal(ceo_decision, underlying_signal)
        # V16 Phase 4C Step 7C: _journal_ceo_decision() now returns the
        # ONE shared signal_id it created for this CEO decision cycle
        # (or None — no journal, no decision, or the write failed).
        # Thread it onto the outgoing ExecutionSignal so
        # execution_orchestrator.py's _record_trade_opened() reuses it
        # instead of minting an unrelated one — only when there IS a
        # final_signal (a vetoed/WAIT/BLOCKED cycle still gets journaled
        # above for audit purposes, but there's nothing to attach the id
        # to). ExecutionSignal is frozen -> replace(), not mutation.
        signal_id = self._journal_ceo_decision(symbol, ceo_decision)
        if final_signal is not None and signal_id is not None:
            final_signal = replace(final_signal, signal_id=signal_id)
        # V16 W14-2A: build per-agent attribution from the SAME
        # ceo_decision this whole cycle already produced (Step 7's
        # agent_reports/weights_used, Step 6's confidence/action —
        # nothing recalculated) and thread it onto the outgoing
        # ExecutionSignal, mirroring signal_id's own pattern just above.
        # Only when there's a final_signal to attach it to — a
        # vetoed/WAIT/BLOCKED cycle has nothing to open a trade for, so
        # there's nothing for execution_orchestrator.py's
        # _record_trade_opened() to record attribution against.
        # agent_attribution_from_ceo_decision() itself never raises and
        # returns [] for a malformed/None decision, so this can't turn a
        # real trade into a failure.
        if final_signal is not None and ceo_decision is not None:
            attribution = agent_attribution_from_ceo_decision(ceo_decision.to_dict())
            if attribution:
                final_signal = replace(final_signal, agent_attribution=attribution)
        return final_signal

    def _journal_ceo_decision(self, symbol: str, ceo_decision) -> int | None:
        """Part E — best-effort, non-fatal. Stores nothing if there's no
        journal, or no decision was produced this cycle.

        V16 Phase 4C Step 6: also carries `recommendation_explanations`
        (agents/ceo_agent.py's CEODecision field, populated only by
        decide_with_recommendations()/decide_from_context_with_recommendations()
        — empty list for every other call path, including this one when
        recommendations weren't applied) into the SAME `details` dict
        `reasons`/`agreement_score`/`direction` already go through — no
        new journal table, no new column, no new endpoint. Serialized via
        AppliedRecommendationExplanation.to_dict() (learning/application/
        recommendation_advisor.py), the existing method that object
        already has; nothing recalculated. Reachable afterward through
        the existing `/api/ceo-decisions` (journal_v2.get_agent_decisions())
        without any change to that endpoint.

        V16 Phase 4C Step 7: same pattern again, for
        `ceo_decision.agent_reports` (each sub-agent's AgentReport.to_dict()
        — already computed inside CEOAgent.decide(), see
        agents/ceo_agent.py; this is the SAME real 6-agent layer
        agents.ceo_symbol_cache.CEOAgentSymbolCache.get_ceo_agent()
        builds per symbol via build_agent_layer() — confirmed by this
        phase's own fresh-clone audit to be genuinely populated for
        this CEO-gated path, not the empty-by-construction case
        journal_v2.get_trade_attribution()'s docstring describes for
        the *plain* execution/portfolio_signal_provider.py path, which
        never runs CEOAgent at all) and `ceo_decision.weights_used`
        (the per-agent weighting actually applied this cycle).

        Scope note (read before Step 7C, kept for history): this made
        per-agent VOTES inspectable per DECISION cycle via
        `/api/ceo-decisions`, same as Step 6 did for recommendations.
        It did NOT yet make journal_v2.get_trade_attribution()'s
        `agent_participation` populate for these trades — that join is
        `trades.signal_id == agent_decisions.signal_id`
        (journal_v2.py's own comment, line ~292), and this method never
        recorded a `signal_id` (every save_agent_decision() call here,
        before this phase, omitted it — defaulted to None).

        V16 Phase 4C Step 7C closes exactly that gap, additively:
        1. One shared signal_id is created for this whole CEO decision
           cycle via journal.save_signal() (a lightweight `signals` row
           — the same table/method execution_orchestrator.py's
           _record_trade_opened() already writes to for the plain,
           non-CEO path). Best-effort: if this fails (including journal
           fakes/doubles that don't implement save_signal at all — see
           this file's own test suite), we log and continue with
           signal_id=None, which reduces to the exact pre-Step-7C
           behavior below (every row gets signal_id=None, nothing new
           breaks).
        2. That id is passed into the EXISTING CEO_AGENT
           save_agent_decision() call (previously always omitted it).
        3. NEW: every entry in ceo_decision.agent_reports (already
           computed by CEOAgent.decide() — see Step 7's own comment
           below; nothing recalculated here) gets its OWN
           save_agent_decision() row, sharing the SAME signal_id — H3/H4:
           each sub-agent stays independently inspectable, never
           collapsed into one JSON blob. `decision`/`score` come from
           that agent's own AgentReport.to_dict() shape (signal/
           confidence — see agents/base_agent.py::AgentReport); `weight`
           comes from ceo_decision.weights_used for that same agent key
           (CEOAgent.WEIGHTS' keys — smc/futures/regime/risk/journal/
           confidence_engine — already line up 1:1 with agent_reports'
           keys, both built from the same `reports` dict in
           agents/ceo_agent.py's decide()). A journal write failure for
           one agent is logged and skipped — it must never stop the
           remaining agents or the decision cycle (same non-fatal
           convention as every other journal write in this method).
        4. This method now returns the shared signal_id (or None) so
           get_signal()/_get_signal_ceo_enabled() can thread it onto the
           outgoing ExecutionSignal — see that method's own comment, and
           execution_orchestrator.py's _record_trade_opened(), which
           reuses it instead of minting a second, unrelated one at
           trade-open time. That's what makes
           trade.signal_id == agent_decision.signal_id hold end to end.

        Still additive, still single-layer in the sense that no schema
        changed and no existing call site's required arguments changed
        — only new, optional data now flows through columns/kwargs that
        already existed for exactly this purpose."""
        if self.journal is None or ceo_decision is None:
            return None

        signal_id: int | None = None
        try:
            signal_id = self.journal.save_signal(
                {
                    "timestamp":  ceo_decision.timestamp,
                    "action":     ceo_decision.action,
                    "direction":  ceo_decision.direction,
                    "confidence": ceo_decision.confidence,
                },
                symbol=symbol,
            )
        except Exception as exc:
            logger.error(f"CEOGatedSignalProvider: signal journal write failed for {symbol} (non-fatal): {exc}")

        try:
            self.journal.save_agent_decision(
                agent="CEO_AGENT",  # matches agents.ceo_agent.CEOAgent.AGENT_NAME
                decision=ceo_decision.action,
                symbol=symbol,
                score=ceo_decision.confidence,
                details={
                    "reasons": ceo_decision.reasons,
                    "agreement_score": ceo_decision.agreement_score,
                    "direction": ceo_decision.direction,
                    "recommendation_explanations": [
                        e.to_dict() for e in ceo_decision.recommendation_explanations
                    ],
                    # V16 Phase 4C Step 7 — already-computed by CEOAgent.decide()
                    # (agents/ceo_agent.py), nothing recalculated here.
                    # agent_reports values are already AgentReport.to_dict()-
                    # shaped dicts (see ceo_agent.py's own agent_reports =
                    # {k: v.to_dict() for k, v in reports.items()}), so no
                    # further serialization is needed.
                    "agent_reports": ceo_decision.agent_reports,
                    "weights_used": ceo_decision.weights_used,
                },
                signal_id=signal_id,
            )
        except Exception as exc:
            logger.error(f"CEOGatedSignalProvider: journal write failed for {symbol} (non-fatal): {exc}")

        # V16 Phase 4C Step 7C — H3/H4: one independently-inspectable
        # row per participating sub-agent, sharing signal_id with the
        # CEO_AGENT row above. Empty agent_reports (e.g. CEOAgent
        # constructed with agents={}) simply iterates zero times —
        # matches this file's own pre-existing
        # test_empty_agents_ceoagent_produces_no_error convention.
        weights_used = ceo_decision.weights_used or {}
        for agent_name, report in (ceo_decision.agent_reports or {}).items():
            try:
                self.journal.save_agent_decision(
                    agent=agent_name,
                    decision=report.get("signal", ""),
                    symbol=symbol,
                    score=report.get("confidence", 0.0),
                    weight=weights_used.get(agent_name, 0.0),
                    details=report,
                    signal_id=signal_id,
                )
            except Exception as exc:
                logger.error(
                    f"CEOGatedSignalProvider: per-agent journal write failed for "
                    f"agent={agent_name} {symbol} (non-fatal): {exc}"
                )

        return signal_id

    def __call__(self, symbol: str) -> Optional[ExecutionSignal]:
        return self.get_signal(symbol)
