"""
knowledge_engine/raw_store.py — V16 Phase 4C Step 8, Layer A (spec §3).

Raw sources are immutable once staged. Two safety properties this
module guarantees:

1. Re-ingesting byte-identical content under the same (category, name)
   is a no-op — returns the existing RawSourceRecord, writes nothing.
2. Re-ingesting DIFFERENT content under the same (category, name) never
   overwrites the earlier file — it's written to a new,
   content-hash-suffixed path. Mirrors learning/learning_snapshot.py's
   already-established "never overwrite, timestamp instead" convention
   in this codebase, extended with a content hash (spec §3 needs
   content-identity, not just time-identity, to detect true no-ops).

Spec §3 also says: "Do NOT automatically copy secrets, API keys,
credentials, .env contents, or private tokens into raw/." This module
runs a conservative pattern check before writing (see
_looks_like_a_secret()) and refuses to stage content that trips it —
callers get a SecretDetectedError, not a silent skip, so a real
ingestion attempt is never silently lost without the caller knowing
why.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from knowledge_engine.provenance import content_hash, utc_now_iso

VALID_CATEGORIES = (
    "research", "trade_reviews", "market_notes", "incidents",
    "architecture", "operator_notes", "external",
)

# Conservative, deliberately over-inclusive — false positives here just
# mean a legitimate note needs a manual override path (not built in
# this phase; spec explicitly only asks to not auto-copy secrets, not
# to build a bypass), false negatives mean a real secret gets staged
# into a git-versioned directory, which is the worse failure mode.
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id shape
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),                     # common API secret key shape
    re.compile(r"(?i)\bBINANCE_(API_KEY|API_SECRET)\s*[:=]\s*\S+"),
    re.compile(r"(?i)\b(api[_-]?key|api[_-]?secret|password|access[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9+/_\-]{12,}"),
)


class SecretDetectedError(ValueError):
    """Raised instead of staging content that matches a secret-like
    pattern. See module docstring."""


class InvalidSourceError(ValueError):
    """Raised for an empty source, an unknown category, or a name that
    would escape raw_root (path traversal)."""


@dataclass(frozen=True)
class RawSourceRecord:
    category: str
    name: str
    path: Path
    sha256: str
    ingested_at: str
    already_existed: bool  # True if this call was a no-op (byte-identical re-ingest)


def _looks_like_a_secret(text: str) -> bool:
    return any(p.search(text) for p in _SECRET_PATTERNS)


def ingest_raw_source(
    text: str,
    category: str,
    name: str,
    raw_root: Path = Path("raw"),
) -> RawSourceRecord:
    """Stage `text` under raw_root/<category>/. `name` should be a
    short, filesystem-safe slug (e.g. "2026-08-11-funding-observation")
    — the actual filename also carries a short content-hash suffix so
    two different ingests under the same name never collide (see
    module docstring, guarantee 2).
    """
    if category not in VALID_CATEGORIES:
        raise InvalidSourceError(f"unknown category {category!r} — must be one of {VALID_CATEGORIES}")
    if not text or not text.strip():
        raise InvalidSourceError("cannot ingest empty source content")
    safe_name = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name).strip("_")
    if not safe_name:
        raise InvalidSourceError(f"name {name!r} has no usable filesystem-safe characters")

    if _looks_like_a_secret(text):
        raise SecretDetectedError(
            f"refusing to stage {name!r} into raw/{category}/ — content matches a "
            "secret-like pattern (see knowledge_engine/raw_store.py _SECRET_PATTERNS). "
            "This directory is git-versioned; remove the credential and re-ingest."
        )

    sha = content_hash(text)
    category_dir = raw_root / category
    category_dir.mkdir(parents=True, exist_ok=True)

    # Guarantee 1: an identical (name, content) pair that was already
    # staged is a no-op — scan for any existing file for this name
    # whose hash matches.
    for existing in category_dir.glob(f"{safe_name}--*.md"):
        if existing.stem.endswith(sha[:12]):
            return RawSourceRecord(
                category=category, name=safe_name, path=existing,
                sha256=sha, ingested_at=utc_now_iso(), already_existed=True,
            )

    path = category_dir / f"{safe_name}--{sha[:12]}.md"
    path.write_text(text, encoding="utf-8")
    return RawSourceRecord(
        category=category, name=safe_name, path=path,
        sha256=sha, ingested_at=utc_now_iso(), already_existed=False,
    )
