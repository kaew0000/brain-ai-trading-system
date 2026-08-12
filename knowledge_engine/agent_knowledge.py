"""
knowledge_engine/agent_knowledge.py — V16 Phase 4C Step 8, spec §5
"Agent" entity.

Reads journal.get_agent_performance() — an already-existing method
(Phase 4B Step 1, architecture.md §27) that joins agent_decisions to
trades via signal_id. Before Phase 4C Step 7C, agent_decisions.signal_id
was always NULL for the CEO-gated multi-symbol path, so this join
structurally returned nothing for it; Step 7C is what makes this
method's output meaningful for that path. This module performs no
attribution computation itself — it only summarizes what
get_agent_performance() already computed.

Every value here is DERIVED_OBSERVATION, never FACT — a win rate is a
computed aggregate, not a single recorded event. Below MIN_SAMPLE_SIZE,
spec §14's "NO_DATA / INSUFFICIENT_EVIDENCE must be represented
explicitly" applies: no win-rate number is written at all, so a future
agent reading the page can't mistake three trades for a real edge.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_engine.contradiction import append_revision_history, detect_contradiction, format_revision_entry
from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence, Provenance, utc_now_iso

MIN_SAMPLE_SIZE = 5  # below this, win_rate is not reported as a number —
# documented, fixed threshold (not a statistical test); see module docstring.


def _read_existing_win_rate(knowledge_root: Path, agent: str) -> float | None:
    path = knowledge_root / "agents" / f"{agent}.md"
    if not path.exists():
        return None
    fm = WikiPage.parse_frontmatter(path.read_text(encoding="utf-8"))
    raw = fm.get("win_rate")
    if raw is None or raw == "INSUFFICIENT_EVIDENCE":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _read_existing_body(knowledge_root: Path, agent: str) -> str:
    path = knowledge_root / "agents" / f"{agent}.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    # body is everything after the second '---' delimiter and the title line
    parts = text.split("---", 2)
    if len(parts) < 3:
        return ""
    after_fm = parts[2].lstrip("\n")
    lines = after_fm.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


def _build_agent_page(row: dict, knowledge_root: Path) -> WikiPage:
    agent = row["agent"]
    total = row["total_trades"]
    sufficient = total >= MIN_SAMPLE_SIZE

    if sufficient:
        win_rate_display = str(row["win_rate"])
        confidence = Confidence.DERIVED_OBSERVATION
        headline = (
            f"Win rate **{row['win_rate']:.1%}** over {total} attributed trades "
            f"(wins={row['wins']}, losses={row['losses']}, total PnL={row['total_pnl']})."
        )
    else:
        win_rate_display = "INSUFFICIENT_EVIDENCE"
        confidence = Confidence.UNKNOWN
        headline = (
            f"INSUFFICIENT_EVIDENCE — only {total} attributed trade(s) "
            f"(minimum {MIN_SAMPLE_SIZE} required before a win rate is reported). "
            "Not enough evidence to derive a reliable win rate yet."
        )

    previous = _read_existing_win_rate(knowledge_root, agent)
    body_summary = f"## Current Synthesis\n\n{headline}\n"
    existing_body = _read_existing_body(knowledge_root, agent)

    if previous is not None and sufficient and detect_contradiction(previous, row["win_rate"]):
        entry = format_revision_entry(
            previous_claim=f"win_rate={previous:.4f}",
            new_evidence=f"win_rate={row['win_rate']:.4f} over {total} trades (wins={row['wins']}, losses={row['losses']})",
            synthesis=headline,
            source_refs=["journal_v2.get_agent_performance()"],
        )
        existing_body = append_revision_history(existing_body, entry)

    # Preserve any prior Revision History section; current synthesis
    # always leads the body.
    if "## Revision History" in existing_body:
        _, _, revision_tail = existing_body.partition("## Revision History")
        body = body_summary + "\n## Revision History" + revision_tail
    else:
        body = body_summary

    provenance = Provenance(
        source_type="journal_agent_performance",
        source_id=agent,
        source_ref="journal_v2.get_agent_performance()",
        confidence=confidence,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    return WikiPage(
        entity_type="agent",
        entity_id=agent,
        title=f"Agent — {agent}",
        body=body,
        provenance=provenance,
        extra_frontmatter={
            "total_trades": total,
            "win_rate": win_rate_display,
        },
    )


def ingest_agent_performance(journal, knowledge_root: Path = Path("knowledge")) -> list[WikiPage]:
    """One page per agent that has ever had an attributed trade
    (journal.get_agent_performance()'s own row set — this function
    adds no filtering beyond what that method already applies)."""
    rows = journal.get_agent_performance()
    pages = []
    for row in rows:
        page = _build_agent_page(row, knowledge_root)
        page.write(knowledge_root)
        pages.append(page)
    return pages
