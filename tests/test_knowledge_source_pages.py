"""tests/test_knowledge_source_pages.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence
from knowledge_engine.raw_store import ingest_raw_source
from knowledge_engine.source_pages import register_source_page

pytestmark = pytest.mark.unit


class TestRegisterSourcePage:
    def test_creates_a_source_page_for_a_raw_ingest(self, tmp_path):
        raw_root = tmp_path / "raw"
        knowledge_root = tmp_path / "knowledge"
        record = ingest_raw_source("A real operator note about funding spikes.", "operator_notes", "note-1", raw_root=raw_root)

        page = register_source_page(record, knowledge_root=knowledge_root)

        assert page.provenance.confidence is Confidence.FACT
        written = knowledge_root / page.relative_path()
        assert written.exists()
        assert record.sha256 in written.read_text(encoding="utf-8")

    def test_source_page_links_back_to_raw_path(self, tmp_path):
        raw_root = tmp_path / "raw"
        knowledge_root = tmp_path / "knowledge"
        record = ingest_raw_source("content", "research", "r1", raw_root=raw_root)
        page = register_source_page(record, knowledge_root=knowledge_root)
        assert record.path.as_posix() in page.body

    def test_frontmatter_has_correct_source_type(self, tmp_path):
        raw_root = tmp_path / "raw"
        knowledge_root = tmp_path / "knowledge"
        record = ingest_raw_source("content", "incidents", "inc1", raw_root=raw_root)
        page = register_source_page(record, knowledge_root=knowledge_root)
        fm = WikiPage.parse_frontmatter((knowledge_root / page.relative_path()).read_text(encoding="utf-8"))
        assert fm["source_type"] == "raw_file"
        assert fm["category"] == "incidents"
