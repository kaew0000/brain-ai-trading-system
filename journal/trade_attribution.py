"""
journal/trade_attribution.py — V16 Phase 4B Step 2: Execution
Attribution + Portfolio Integration

The reusable API Task 5 asks for: record_trade_outcome() is the one
function execution/execution_orchestrator.py and portfolio/
portfolio_manager.py call to persist a trade's outcome. Neither needs
to know journal_v2.py stores this in SQLite, in trades.extra_data, or
anything else about the storage shape — that knowledge stays entirely
inside journal/journal_v2.py's save_trade()/update_trade_result()/
save_execution_attribution(), which this function wraps.

agent_attribution_from_ceo_decision() is the companion Task 4 helper:
given a CEODecision.to_dict()-shaped dict (agents/ceo_agent.py), it
extracts one clean {agent, vote, weight, confidence, contribution}
entry per agent CEOAgent.WEIGHTS actually weighs, plus a final entry
for the CEO's own aggregate decision. "CEO" is not itself a WEIGHTS
key (CEOAgent aggregates the six weighted agents; it isn't a seventh
weighted vote on itself), so its entry is shaped slightly differently:
vote is the CEO's chosen action, weight is fixed at 1.0 (its decision
fully determines the trade, by definition), and contribution is its
own confidence rather than confidence*weight. Documented rather than
silently forced into the same shape as the six real weighted agents.

Nothing here decides HOW to weigh agents differently based on
outcomes — that's explicitly out of scope (Task 7: "prepare data for
Phase 4C, do NOT implement Dynamic Weight Learning yet"). Phase 4B
proper (docs/architecture.md §28) already added a simple
static-to-win-rate blend (settings.DYNAMIC_AGENT_WEIGHTS_ENABLED) using
aggregate win/loss counts alone; this phase's richer per-trade dataset
(journal/journal_v2.py's get_ensemble_learning_dataset()) is additive
groundwork for a future, more sophisticated Phase 4C — not a
replacement for or duplicate of §28's existing mechanism. Flagging this
explicitly since the naming overlap ("dynamic weighting" already
shipped vs. "Dynamic Weight Learning" still planned) could otherwise
read as contradictory.
"""
from __future__ import annotations

from utils.logger import get_logger

logger = get_logger(__name__)

# Mirrors agents/ceo_agent.py's CEOAgent.WEIGHTS keys exactly — not
# re-derived from the CEODecision dict (agent_reports may legitimately
# be a subset if an agent didn't report this cycle), and not invented
# independently of the real agent identifiers.
CEO_WEIGHTED_AGENT_KEYS = ("smc", "futures", "regime", "risk", "journal", "confidence_engine")


def agent_attribution_from_ceo_decision(ceo_decision: dict | None) -> list[dict]:
    """Extract a clean per-agent participation list from a
    CEODecision.to_dict()-shaped dict (agents/ceo_agent.py). Returns []
    for None/malformed input — attribution extraction must never be
    able to break a caller's decision cycle. Omits any WEIGHTS key that
    didn't report this cycle rather than fabricating a zeroed entry for
    it."""
    if not ceo_decision:
        return []
    agent_reports = ceo_decision.get("agent_reports") or {}
    weights_used = ceo_decision.get("weights_used") or {}
    score_breakdown = ceo_decision.get("score_breakdown") or {}

    out: list[dict] = []
    for key in CEO_WEIGHTED_AGENT_KEYS:
        report = agent_reports.get(key)
        if report is None:
            continue
        out.append({
            "agent":        key,
            "vote":         report.get("signal"),
            "weight":       weights_used.get(key),
            "confidence":   report.get("confidence"),
            "contribution": score_breakdown.get(key),
        })

    if ceo_decision.get("action") is not None:
        out.append({
            "agent":        "ceo",
            "vote":         ceo_decision.get("action"),
            "weight":       1.0,
            "confidence":   ceo_decision.get("confidence"),
            "contribution": ceo_decision.get("confidence"),
        })
    return out


def record_trade_outcome(
    journal,
    trade_id: int,
    *,
    result: str | None = None,
    exit_price: float | None = None,
    pnl: float | None = None,
    execution_id: str | None = None,
    order_id: str | None = None,
    fees: float | None = None,
    slippage: float | None = None,
    latency_seconds: float | None = None,
    agent_attribution: list[dict] | None = None,
) -> bool:
    """
    Task 5's reusable attribution API. Callers supply whatever they
    actually have — every parameter is optional, so this same function
    covers both the open-side call (only execution_id/order_id/
    slippage/latency_seconds known) and the close-side call
    (result/exit_price/pnl now known too) — without the caller needing
    two different functions or any knowledge of storage internals.

    Never raises: any storage failure is logged and reflected in the
    return value, matching this project's established "diagnostic/
    attribution data must never break a live trade" rule (e.g.
    agents/ceo_agent.py's dynamic-weight fallback, main.py's per-agent
    try/except around save_agent_decision()).

    `journal` is any object exposing update_trade_result() and
    save_execution_attribution() — in production this is a
    journal.journal_v2.TradeJournalV2 instance, but this function only
    calls those two methods, so a test fake needs nothing else.
    """
    ok = True

    if result is not None and exit_price is not None and pnl is not None:
        try:
            ok = bool(journal.update_trade_result(trade_id, result, exit_price, pnl)) and ok
        except Exception as exc:
            logger.error(f"record_trade_outcome: update_trade_result failed (trade #{trade_id}): {exc}")
            ok = False

    attribution_fields = {
        "execution_id":      execution_id,
        "order_id":          order_id,
        "fees":              fees,
        "slippage":          slippage,
        "latency_seconds":   latency_seconds,
        "agent_attribution": agent_attribution,
    }
    try:
        ok = bool(journal.save_execution_attribution(trade_id, **attribution_fields)) and ok
    except Exception as exc:
        logger.error(f"record_trade_outcome: save_execution_attribution failed (trade #{trade_id}): {exc}")
        ok = False

    return ok
