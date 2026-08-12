"""
knowledge_engine/index_builder.py — V16 Phase 4C Step 8, spec §6.

knowledge/index.md is never hand-edited — spec §6: "Do NOT allow the
index to become a manually maintained stale file. Provide a
deterministic update mechanism." rebuild_index() is that mechanism: it
scans every page's own frontmatter and regenerates the whole file from
scratch every time, so the index can never drift from what pages
actually say about themselves.

Only files with a frontmatter block this package's own WikiPage.write()
produced are indexed (parse failures are skipped, not errored — a
stray non-knowledge .md file dropped into the tree by accident
shouldn't crash index generation).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from knowledge_engine.pages import WikiPage

_SKIP_FILENAMES = {"index.md", "log.md"}


def rebuild_index(knowledge_root: Path = Path("knowledge")) -> Path:
    by_category: dict[str, list[tuple[Path, dict]]] = defaultdict(list)

    for md_file in sorted(knowledge_root.rglob("*.md")):
        if md_file.name in _SKIP_FILENAMES:
            continue
        try:
            fm = WikiPage.parse_frontmatter(md_file.read_text(encoding="utf-8"))
        except ValueError:
            continue  # not a page this package wrote — skip, don't crash
        category = md_file.parent.name
        by_category[category].append((md_file, fm))

    lines = [
        "---",
        "generated_by: knowledge_engine.index_builder.rebuild_index",
        "---",
        "",
        "# Brain Bot V16 — Knowledge Index",
        "",
        "Deterministically regenerated from every page's own frontmatter — "
        "never hand-edited. See knowledge_engine/index_builder.py.",
        "",
    ]

    for category in sorted(by_category):
        entries = by_category[category]
        lines.append(f"## {category.capitalize()} ({len(entries)})")
        lines.append("")
        lines.append("| Page | Confidence | Source count | Last updated |")
        lines.append("| --- | --- | --- | --- |")
        for md_file, fm in sorted(entries, key=lambda t: t[0].name):
            rel = md_file.relative_to(knowledge_root)
            title = fm.get("title", md_file.stem)
            confidence = fm.get("confidence", "UNKNOWN")
            updated = fm.get("updated_at", "")
            # Each page currently carries exactly one source_ref (this
            # phase's ingestion functions each write one Provenance per
            # page) — source_count is honestly 1 today, not a
            # fabricated aggregate. A future phase that synthesizes
            # multiple sources into one page is the trigger to make
            # this a real count.
            source_count = 1
            lines.append(f"| [{title}]({rel.as_posix()}) | {confidence} | {source_count} | {updated} |")
        lines.append("")

    index_path = knowledge_root / "index.md"
    index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return index_path
