"""
knowledge_engine/pages.py — V16 Phase 4C Step 8.

WikiPage: the on-disk unit of the knowledge/ layer. Markdown body with
a simple `key: value` frontmatter block (deliberately NOT full YAML —
this repository has no yaml/PyYAML dependency today
(`requirements.txt` checked, none present) and every frontmatter value
this package writes is a flat string/number, so a small hand-rolled
parser avoids adding a new dependency for a feature that doesn't need
one. If a future page genuinely needs nested/list frontmatter, that's
the trigger to add PyYAML for real, not before.

index_builder.py depends on being able to parse every page's
frontmatter back out losslessly — that round-trip is what this
module's tests verify.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from knowledge_engine.provenance import Provenance

_FRONTMATTER_DELIM = "---"


@dataclass
class WikiPage:
    """entity_type/entity_id together are the page's identity (spec
    §5's "core knowledge objects" — trade/agent/regime/strategy).
    `title` and `body` are free Markdown; `extra_frontmatter` holds
    any additional flat key:value pairs a specific page type wants
    surfaced to index_builder.py (e.g. `symbol`, `win_rate`) without
    this base class needing to know about every entity type's fields.
    """

    entity_type: str
    entity_id: str
    title: str
    body: str
    provenance: Provenance
    extra_frontmatter: dict = field(default_factory=dict)

    def relative_path(self) -> Path:
        """entity_type pluralizes to the existing knowledge/<type>s/
        subdirectories (trades/, agents/) created by this phase;
        anything else falls back to a lowercased entity_type directory
        so new entity types (regimes, strategies — spec §5, not yet
        implemented by this phase) slot in without code changes here."""
        subdir = f"{self.entity_type}s" if not self.entity_type.endswith("s") else self.entity_type
        safe_id = "".join(c if (c.isalnum() or c in "-_") else "_" for c in self.entity_id)
        return Path(subdir) / f"{safe_id}.md"

    def to_markdown(self) -> str:
        fm = {"entity_type": self.entity_type, "entity_id": self.entity_id, "title": self.title}
        fm.update(self.provenance.to_frontmatter_dict())
        fm.update(self.extra_frontmatter)
        lines = [_FRONTMATTER_DELIM]
        for k, v in fm.items():
            lines.append(f"{k}: {v}")
        lines.append(_FRONTMATTER_DELIM)
        lines.append("")
        lines.append(f"# {self.title}")
        lines.append("")
        lines.append(self.body)
        return "\n".join(lines) + "\n"

    @staticmethod
    def parse_frontmatter(markdown_text: str) -> dict:
        """Returns the flat frontmatter dict from a page written by
        to_markdown(). Raises ValueError if the file has no
        frontmatter block — every page this package writes has one;
        a missing block means the file wasn't produced by this
        package (or is corrupted) and callers should not guess."""
        lines = markdown_text.splitlines()
        if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
            raise ValueError("no frontmatter block found (expected file to start with '---')")
        out: dict = {}
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == _FRONTMATTER_DELIM:
                return out
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
        raise ValueError("frontmatter block never closed (missing second '---')")

    def write(self, knowledge_root: Path) -> Path:
        """Writes (or overwrites) this page's own file under
        knowledge_root. Overwriting the ENTITY's page is expected and
        correct (it's the same trade/agent being updated in place) —
        what must never be silently lost is the CLAIM history inside
        the body, which is contradiction.py's job, not this method's.
        """
        path = knowledge_root / self.relative_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_markdown(), encoding="utf-8")
        return path
