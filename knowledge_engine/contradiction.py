"""
knowledge_engine/contradiction.py — V16 Phase 4C Step 8, spec §9.

The Karpathy-pattern idea this implements: new evidence should UPDATE
existing synthesis rather than being appended as another isolated,
disconnected summary. When a re-computed DERIVED_OBSERVATION
meaningfully disagrees with what a page previously claimed, that
disagreement is recorded — previous claim, new evidence, and the
resulting synthesis — rather than the old claim being silently
overwritten and lost.

This module only detects numeric contradictions (spec's own worked
examples are all numeric — win rates, PnL) and formats a revision
entry. It does not decide what counts as "the truth" — the caller
(agent_knowledge.py etc.) always writes the newest computation as the
current synthesis; this module's job is only to make sure that when it
disagrees with the last one, that disagreement is visible in the page
body, not silently lost.
"""
from __future__ import annotations

from knowledge_engine.provenance import utc_now_iso

DEFAULT_THRESHOLD = 0.15  # a swing of >15 percentage points (or >15% relative
# on non-ratio metrics) is treated as worth recording explicitly, not
# just noise from one more data point. Deliberately simple and
# documented rather than a statistical significance test — spec §9
# asks for a support/contradict/refine mechanism, not a hypothesis
# test; a fixed, stated threshold is honest about being a heuristic.


def detect_contradiction(previous_value: float, new_value: float, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True if new_value moved far enough from previous_value to be
    worth recording as a contradiction rather than a routine update.
    """
    if previous_value == 0:
        return new_value != 0
    relative_change = abs(new_value - previous_value) / abs(previous_value)
    absolute_change = abs(new_value - previous_value)
    return relative_change > threshold or absolute_change > threshold


def format_revision_entry(
    previous_claim: str,
    new_evidence: str,
    synthesis: str,
    source_refs: list[str],
) -> str:
    """Returns a Markdown block for a page's "## Revision History"
    section. Callers PREPEND this (newest first) — never delete a
    prior entry, never edit one in place (spec §9: "Never silently
    overwrite a previous claim when the evidence conflicts").
    """
    refs = "\n".join(f"- {r}" for r in source_refs) if source_refs else "- (none recorded)"
    return (
        f"### {utc_now_iso()}\n\n"
        f"- **Previous claim:** {previous_claim}\n"
        f"- **New evidence:** {new_evidence}\n"
        f"- **Current synthesis:** {synthesis}\n"
        f"- **Sources:**\n{refs}\n"
    )


def append_revision_history(body: str, entry: str) -> str:
    """Inserts `entry` at the top of the page body's "## Revision
    History" section, creating that section if it doesn't exist yet.
    Every prior entry in the section is preserved untouched below it.
    """
    marker = "## Revision History"
    if marker not in body:
        return body.rstrip() + f"\n\n{marker}\n\n{entry}\n"

    head, _, tail = body.partition(marker)
    # tail starts right after the marker text; keep its existing
    # newline structure, just splice the new entry in first.
    return f"{head}{marker}\n\n{entry}\n{tail.lstrip(chr(10))}"
