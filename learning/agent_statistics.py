"""
learning/agent_statistics.py — V16 Phase 4C Step 1: per-agent
participation and vote-agreement quality, feeding pattern_miner.py's
"agent agreement quality" / "agent disagreement quality" patterns.

Design note: this computes something conceptually similar to
journal/journal_v2.py's get_agent_performance() (Phase 4B Step 1,
architecture.md §27), but is NOT a duplicate of it and does not call
it — get_agent_performance() is a live SQL join against
agent_decisions for a completely different purpose (feeding
CEOAgent's own dynamic-weight blend, §28). This module does a pure
in-memory aggregation over an already-built LearningDataset's
`agent_participation` field, for the Learning Pipeline's reporting
purpose. Flagging the naming/conceptual overlap explicitly rather than
letting it look accidental, same convention this project uses whenever
two mechanisms are related but distinct (see
journal/trade_attribution.py's own module docstring for a prior
example).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ._stats_utils import rows_of


@dataclass(frozen=True)
class AgentStatistics:
    agent:                str
    total_trades:          int
    wins:                 int
    win_rate:             float | None
    agreement_count:       int      # trades where this agent's vote matched the trade's own direction
    agreement_win_rate:    float | None
    disagreement_count:    int
    disagreement_win_rate: float | None
    avg_contribution:      float | None


def compute_agent_statistics(dataset_or_rows) -> list[AgentStatistics]:
    """Sorted by win_rate descending. Only rows with a resolved
    WIN/LOSS result and a recorded direction are counted — an open or
    unresolved trade can't yet tell us whether any agent's vote was
    "right"."""
    rows = rows_of(dataset_or_rows)
    by_agent: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.result not in ("WIN", "LOSS") or not r.direction:
            continue
        for entry in r.agent_participation:
            agent = entry.get("agent")
            if not agent:
                continue
            vote = entry.get("vote")
            by_agent[agent].append({
                "result": r.result,
                "agreed": (vote == r.direction) if vote else None,
                "contribution": entry.get("contribution"),
            })

    out = []
    for agent, records in by_agent.items():
        total = len(records)
        wins = sum(1 for x in records if x["result"] == "WIN")
        agreeing = [x for x in records if x["agreed"] is True]
        disagreeing = [x for x in records if x["agreed"] is False]
        agreeing_wins = sum(1 for x in agreeing if x["result"] == "WIN")
        disagreeing_wins = sum(1 for x in disagreeing if x["result"] == "WIN")
        contributions = [x["contribution"] for x in records if x["contribution"] is not None]

        out.append(AgentStatistics(
            agent=agent,
            total_trades=total,
            wins=wins,
            win_rate=round(wins / total, 4) if total else None,
            agreement_count=len(agreeing),
            agreement_win_rate=round(agreeing_wins / len(agreeing), 4) if agreeing else None,
            disagreement_count=len(disagreeing),
            disagreement_win_rate=round(disagreeing_wins / len(disagreeing), 4) if disagreeing else None,
            avg_contribution=round(sum(contributions) / len(contributions), 4) if contributions else None,
        ))

    return sorted(out, key=lambda a: a.win_rate if a.win_rate is not None else -1, reverse=True)
