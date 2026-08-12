"""tests/test_knowledge_pages.py — V16 Phase 4C Step 8."""
from __future__ import annotations

from pathlib import Path

import pytest

from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence, Provenance, utc_now_iso

pytestmark = pytest.mark.unit


def _page(entity_type="trade", entity_id="42", **extra):
    provenance = Provenance(
        source_type="journal_trade", source_id=entity_id, source_ref=f"journal_v2 trade_id={entity_id}",
        confidence=Confidence.FACT, created_at=utc_now_iso(), updated_at=utc_now_iso(),
    )
    return WikiPage(
        entity_type=entity_type, entity_id=entity_id, title=f"Trade #{entity_id}",
        body="## Facts\n\nsome body text", provenance=provenance, extra_frontmatter=extra,
    )


class TestRelativePath:
    def test_pluralizes_entity_type(self):
        assert _page(entity_type="trade").relative_path() == Path("trades/42.md")
        assert _page(entity_type="agent", entity_id="smc").relative_path() == Path("agents/smc.md")

    def test_sanitizes_unsafe_entity_id_characters(self):
        p = _page(entity_id="../../etc/passwd")
        rel = p.relative_path()
        assert ".." not in rel.as_posix()
        assert "/" not in rel.name


class TestMarkdownRoundTrip:
    def test_frontmatter_round_trips(self):
        page = _page(symbol="BTCUSDT", result="WIN")
        md = page.to_markdown()
        fm = WikiPage.parse_frontmatter(md)
        assert fm["entity_type"] == "trade"
        assert fm["entity_id"] == "42"
        assert fm["symbol"] == "BTCUSDT"
        assert fm["result"] == "WIN"
        assert fm["confidence"] == "FACT"

    def test_body_and_title_present_in_output(self):
        page = _page()
        md = page.to_markdown()
        assert "# Trade #42" in md
        assert "some body text" in md

    def test_missing_frontmatter_raises(self):
        with pytest.raises(ValueError):
            WikiPage.parse_frontmatter("# just a heading\n\nno frontmatter here")

    def test_unclosed_frontmatter_raises(self):
        with pytest.raises(ValueError):
            WikiPage.parse_frontmatter("---\nkey: value\n\nno closing delimiter")


class TestWrite:
    def test_write_creates_file_at_relative_path(self, tmp_path):
        page = _page()
        written = page.write(tmp_path)
        assert written == tmp_path / "trades" / "42.md"
        assert written.exists()

    def test_write_creates_parent_directories(self, tmp_path):
        page = _page(entity_type="agent", entity_id="futures")
        written = page.write(tmp_path / "nested" / "knowledge")
        assert written.exists()

    def test_write_overwrites_same_entity_page(self, tmp_path):
        page1 = _page()
        page1.body = "first version"
        page1.write(tmp_path)

        page2 = _page()
        page2.body = "second version"
        written = page2.write(tmp_path)

        text = written.read_text(encoding="utf-8")
        assert "second version" in text
        assert "first version" not in text
