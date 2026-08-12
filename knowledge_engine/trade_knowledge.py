"""
knowledge_engine/trade_knowledge.py — V16 Phase 4C Step 8, spec §5
"Trade" entity + §12 integration priority 1/2.

Explicitly does NOT duplicate the trade database into Markdown (spec
§5: "Do NOT duplicate the entire trade database into Markdown"). This
module reads two already-existing journal_v2.py methods —
get_trades() for the raw row, get_trade_attribution(trade_id) for the
Step 7C-enabled agent join — and writes a small, FACT-labeled summary
page. journal_v2.py itself is never modified by this phase; every
value below is read, never written, back to the trade database.

Only CLOSED trades (result WIN/LOSS) get a page. An OPEN trade is
still changing — writing a "knowledge" page about it would misrepresent
an in-flight, unsettled position as recorded fact.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence, Provenance, utc_now_iso

_CLOSED_RESULTS = ("WIN", "LOSS")


def ingest_closed_trade(journal, trade_id: int, knowledge_root: Path = Path("knowledge")) -> WikiPage | None:
    """Reads trade_id via journal.get_trade_attribution() (reusing
    Step 7C's signal_id bridge for agent_participation — this module
    performs no attribution computation of its own) and, only if the
    trade is closed, writes/updates knowledge/trades/<id>.md.

    Returns None (writes nothing) if the trade doesn't exist or isn't
    closed yet.
    """
    attribution = journal.get_trade_attribution(trade_id)
    if attribution is None:
        return None
    if attribution["result"] not in _CLOSED_RESULTS:
        return None

    agents = attribution["agent_participation"]
    if agents:
        agent_lines = "\n".join(
            f"- **{a['agent']}**: voted {a['vote']} (confidence {a['confidence']}, "
            f"weight {a['weight']}, contribution {a['contribution']})"
            for a in agents
        )
        agent_section = (
            f"## Agent Participation (via signal_id, Phase 4C Step 7C)\n\n{agent_lines}\n"
        )
    else:
        agent_section = (
            "## Agent Participation (via signal_id, Phase 4C Step 7C)\n\n"
            "UNKNOWN — no agent_decisions rows share this trade's signal_id. "
            "Either this trade predates Step 7C, or it was opened through a "
            "path that doesn't run the CEO agent layer (see "
            "docs/architecture.md §29 \"Scope boundary\").\n"
        )

    body = (
        f"## Facts\n\n"
        f"- **Symbol:** {attribution['symbol']}\n"
        f"- **Direction:** {attribution['direction']}\n"
        f"- **Entry price:** {attribution['entry_price']}\n"
        f"- **Exit price:** {attribution['exit_price']}\n"
        f"- **Result:** {attribution['result']}\n"
        f"- **PnL:** {attribution['pnl']}\n"
        f"- **Quantity:** {attribution['quantity']}\n"
        f"- **Stop loss / take profit:** {attribution['stop_loss']} / {attribution['take_profit']}\n"
        f"- **R:R:** {attribution['rr']}\n"
        f"- **Regime at entry:** {attribution['regime']}\n"
        f"- **Close reason:** {attribution['reason']}\n"
        f"- **Duration (s):** {attribution['duration_seconds']}\n"
        f"- **Timestamp:** {attribution['timestamp']}\n\n"
        f"{agent_section}"
    )

    provenance = Provenance(
        source_type="journal_trade_attribution",
        source_id=str(trade_id),
        source_ref=f"journal_v2.get_trade_attribution(trade_id={trade_id})",
        confidence=Confidence.FACT,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    page = WikiPage(
        entity_type="trade",
        entity_id=str(trade_id),
        title=f"Trade #{trade_id} — {attribution['symbol']} {attribution['direction']} ({attribution['result']})",
        body=body,
        provenance=provenance,
        extra_frontmatter={
            "symbol": attribution["symbol"],
            "result": attribution["result"],
            "signal_id_backed": "yes" if agents else "unknown",
        },
    )
    page.write(knowledge_root)
    return page
