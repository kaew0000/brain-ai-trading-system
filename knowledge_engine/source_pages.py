"""
knowledge_engine/source_pages.py — V16 Phase 4C Step 8.

Bridges Layer A (raw_store.py's immutable raw/ staging) to Layer B
(the knowledge/ wiki): every raw source that gets staged also gets a
one-page provenance record under knowledge/sources/, so the index
(spec §6) and any page that cites this source (spec §8) has something
concrete to link to. This is intentionally the ONLY page type in this
phase whose own confidence is FACT about itself (a source's existence
and hash are directly observed, not derived) while saying nothing
about whether the raw content's CLAIMS are true — that judgment
belongs to whatever page later cites this source.
"""
from __future__ import annotations

from pathlib import Path

from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence, Provenance, utc_now_iso
from knowledge_engine.raw_store import RawSourceRecord


def register_source_page(record: RawSourceRecord, knowledge_root: Path = Path("knowledge")) -> WikiPage:
    body = (
        f"## Facts\n\n"
        f"- **Category:** {record.category}\n"
        f"- **Raw path:** `{record.path.as_posix()}`\n"
        f"- **SHA-256:** `{record.sha256}`\n"
        f"- **Staged at:** {record.ingested_at}\n\n"
        "This page only records that this raw source exists and its "
        "content hash — it makes no claim about the truth of the raw "
        "content itself. Pages that cite this source as evidence carry "
        "their own confidence label independently.\n"
    )
    provenance = Provenance(
        source_type="raw_file",
        source_id=record.sha256[:12],
        source_ref=record.path.as_posix(),
        confidence=Confidence.FACT,
        created_at=record.ingested_at,
        updated_at=utc_now_iso(),
    )
    page = WikiPage(
        entity_type="source",
        entity_id=f"{record.category}-{record.name}-{record.sha256[:12]}",
        title=f"Source — {record.category}/{record.name}",
        body=body,
        provenance=provenance,
        extra_frontmatter={"category": record.category},
    )
    page.write(knowledge_root)
    return page
