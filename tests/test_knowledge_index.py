"""tests/test_knowledge_index.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from knowledge_engine.index_builder import rebuild_index
from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence, Provenance, utc_now_iso

pytestmark = pytest.mark.unit


def _write_page(tmp_path, entity_type, entity_id, confidence=Confidence.FACT):
    p = WikiPage(
        entity_type=entity_type, entity_id=entity_id, title=f"{entity_type} {entity_id}",
        body="body", provenance=Provenance(
            source_type="test", source_id=entity_id, source_ref="ref",
            confidence=confidence, created_at=utc_now_iso(), updated_at=utc_now_iso(),
        ),
    )
    p.write(tmp_path)
    return p


class TestRebuildIndex:
    def test_empty_knowledge_root_produces_valid_index(self, tmp_path):
        path = rebuild_index(tmp_path)
        assert path == tmp_path / "index.md"
        assert "Knowledge Index" in path.read_text(encoding="utf-8")

    def test_indexes_every_written_page(self, tmp_path):
        _write_page(tmp_path, "trade", "1")
        _write_page(tmp_path, "trade", "2")
        _write_page(tmp_path, "agent", "smc")

        rebuild_index(tmp_path)
        text = (tmp_path / "index.md").read_text(encoding="utf-8")
        assert "## Trades (2)" in text
        assert "## Agents (1)" in text

    def test_skips_index_and_log_files_themselves(self, tmp_path):
        _write_page(tmp_path, "trade", "1")
        rebuild_index(tmp_path)  # writes index.md
        (tmp_path / "log.md").write_text("---\nnot: a page\n---\n", encoding="utf-8")

        rebuild_index(tmp_path)  # rebuild again — must not choke on its own prior output
        text = (tmp_path / "index.md").read_text(encoding="utf-8")
        assert "## Trades (1)" in text  # still exactly 1, not duplicated

    def test_skips_non_knowledge_markdown_without_crashing(self, tmp_path):
        stray = tmp_path / "trades"
        stray.mkdir(parents=True)
        (stray / "not_a_page.md").write_text("# just some notes, no frontmatter", encoding="utf-8")

        path = rebuild_index(tmp_path)
        assert path.exists()  # did not crash

    def test_deterministic_across_repeated_calls(self, tmp_path):
        _write_page(tmp_path, "trade", "1")
        _write_page(tmp_path, "agent", "smc")
        first = rebuild_index(tmp_path).read_text(encoding="utf-8")
        second = rebuild_index(tmp_path).read_text(encoding="utf-8")
        # updated_at timestamps inside pages are fixed at write time (not
        # touched by rebuild_index), so two rebuilds of the same pages
        # produce byte-identical index output.
        assert first == second

    def test_categories_sorted_alphabetically(self, tmp_path):
        _write_page(tmp_path, "trade", "1")
        _write_page(tmp_path, "agent", "smc")
        _write_page(tmp_path, "source", "raw-1")
        rebuild_index(tmp_path)
        text = (tmp_path / "index.md").read_text(encoding="utf-8")
        assert text.index("## Agents") < text.index("## Sources") < text.index("## Trades")
