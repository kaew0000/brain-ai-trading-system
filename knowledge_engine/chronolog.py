"""
knowledge_engine/chronolog.py — V16 Phase 4C Step 8, spec §7.

knowledge/log.md is append-only. This module is the ONLY writer to
that file in this package — every other module that wants an event
recorded calls append_log_entry() rather than touching the file
directly, so "never silently rewrite historical log entries" (spec
§7) has exactly one enforcement point to audit/test.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_engine.provenance import utc_now_iso

LOG_FILENAME = "log.md"

VALID_EVENTS = ("ingest", "update", "synthesis", "contradiction", "lint")


def append_log_entry(
    event: str,
    entity: str,
    knowledge_root: Path = Path("knowledge"),
    detail: str = "",
) -> Path:
    """Appends one line: `[YYYY-MM-DD] event | entity` (spec §7's
    exact format), optionally followed by ` | detail`. Creates the log
    file with a one-line header on first use; every subsequent call
    only ever opens in append mode.
    """
    if event not in VALID_EVENTS:
        raise ValueError(f"unknown event {event!r} — must be one of {VALID_EVENTS}")
    if not entity:
        raise ValueError("entity must be non-empty — every log line must name what it's about")

    knowledge_root.mkdir(parents=True, exist_ok=True)
    log_path = knowledge_root / LOG_FILENAME
    date = utc_now_iso()[:10]
    line = f"[{date}] {event} | {entity}"
    if detail:
        line += f" | {detail}"

    is_new = not log_path.exists()
    with log_path.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(
                "# Brain Bot V16 — Knowledge Log\n\n"
                "Append-only. Never edit or delete a prior line — if an earlier "
                "entry turns out to be wrong, record a correction as a new line, "
                "don't rewrite history. See knowledge_engine/chronolog.py.\n\n"
            )
        f.write(line + "\n")
    return log_path


def read_log(knowledge_root: Path = Path("knowledge")) -> list[str]:
    """Returns every log line (skipping the header), oldest first."""
    log_path = knowledge_root / LOG_FILENAME
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8").splitlines()
    return [ln for ln in lines if ln.startswith("[")]
