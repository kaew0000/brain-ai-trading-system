"""
knowledge_engine/provenance.py — V16 Phase 4C Step 8: Persistent Trading
Knowledge Layer.

Every generated knowledge page MUST carry a Provenance record. This
module defines the closed set of confidence levels every page's claims
are labeled with (spec §13/§14 — "never present an inferred claim as
an observed fact") and the Provenance record itself (spec §8).

This module has ZERO dependencies on execution/, risk/, decision/,
agents/, or any exchange client — it only knows how to describe WHERE
a piece of knowledge came from, never how to act on it. See
knowledge_engine/__init__.py's module docstring for the full safety
boundary this package operates under.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class Confidence(str, Enum):
    """The four labels spec §13 requires every claim to be tagged
    with, so a future agent reading a page can tell what kind of
    knowledge it's looking at. Closed set — do not add ad-hoc strings
    elsewhere; import this enum.

    FACT               — a direct field from an authoritative source
                          (e.g. journal_v2's own trade row), not
                          computed or inferred.
    DERIVED_OBSERVATION — computed from FACTs (e.g. an aggregate win
                          rate over N trades) — real math, real data,
                          but a summary, not a single recorded event.
    HYPOTHESIS          — a pattern or claim proposed for future
                          verification, not yet confirmed by enough
                          evidence.
    UNKNOWN             — explicitly marks a gap. Spec §14: "If
                          insufficient evidence exists: NO_DATA /
                          INSUFFICIENT_EVIDENCE must be represented
                          explicitly" — this is that marker.
    """

    FACT = "FACT"
    DERIVED_OBSERVATION = "DERIVED_OBSERVATION"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


def utc_now_iso() -> str:
    """Single source of timestamp formatting for this package — every
    module below imports this rather than calling datetime directly,
    so every page/log/provenance record is formatted identically."""
    return datetime.now(timezone.utc).isoformat()


def content_hash(text: str) -> str:
    """SHA-256 of raw source content, used by raw_store.py to detect
    whether a re-ingested source is byte-identical to something
    already staged (no-op) or genuinely new content under the same
    name (never overwritten — see raw_store.py's own docstring)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Provenance:
    """Attached to every generated knowledge page (spec §8 — minimum
    fields: source, source_type, source_id, created_at, updated_at).
    `source_ref` is this package's own addition: a human-followable
    pointer (e.g. "journal_v2.get_trades() trade_id=42",
    "raw/research/2026-08-11-funding-note.md#a1b2c3d4") — spec §8
    says provenance must be traceable, a bare source_id alone isn't
    always enough to know how to go re-derive it.
    """

    source_type: str        # e.g. "journal_trade", "journal_agent_performance", "raw_file"
    source_id: str          # e.g. trade_id, agent name, content hash
    source_ref: str         # human-followable pointer back to the source
    confidence: Confidence
    created_at: str
    updated_at: str

    def __post_init__(self) -> None:
        if not self.source_type or not self.source_id or not self.source_ref:
            raise ValueError(
                "Provenance requires non-empty source_type/source_id/source_ref — "
                "spec §8: 'If provenance is unavailable, explicitly mark it as "
                "unknown' means using Confidence.UNKNOWN, not an empty pointer."
            )

    def to_frontmatter_dict(self) -> dict:
        return {
            "source_type": self.source_type,
            "source_id": self.source_id,
            "source_ref": self.source_ref,
            "confidence": self.confidence.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
