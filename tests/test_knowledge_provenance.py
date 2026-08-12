"""tests/test_knowledge_provenance.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from knowledge_engine.provenance import Confidence, Provenance, content_hash, utc_now_iso

pytestmark = pytest.mark.unit


class TestConfidence:
    def test_closed_set_of_four_labels(self):
        assert {c.value for c in Confidence} == {
            "FACT", "DERIVED_OBSERVATION", "HYPOTHESIS", "UNKNOWN",
        }


class TestProvenance:
    def test_valid_provenance_constructs(self):
        p = Provenance(
            source_type="journal_trade", source_id="42", source_ref="journal_v2 trade_id=42",
            confidence=Confidence.FACT, created_at=utc_now_iso(), updated_at=utc_now_iso(),
        )
        assert p.source_type == "journal_trade"
        assert p.confidence is Confidence.FACT

    @pytest.mark.parametrize("field", ["source_type", "source_id", "source_ref"])
    def test_empty_required_field_rejected(self, field):
        kwargs = dict(
            source_type="journal_trade", source_id="42", source_ref="ref",
            confidence=Confidence.FACT, created_at=utc_now_iso(), updated_at=utc_now_iso(),
        )
        kwargs[field] = ""
        with pytest.raises(ValueError):
            Provenance(**kwargs)

    def test_to_frontmatter_dict_has_all_fields(self):
        p = Provenance(
            source_type="raw_file", source_id="abc123", source_ref="raw/research/x.md",
            confidence=Confidence.UNKNOWN, created_at="2026-08-11T00:00:00+00:00",
            updated_at="2026-08-11T00:00:00+00:00",
        )
        fm = p.to_frontmatter_dict()
        assert fm == {
            "source_type": "raw_file", "source_id": "abc123", "source_ref": "raw/research/x.md",
            "confidence": "UNKNOWN", "created_at": "2026-08-11T00:00:00+00:00",
            "updated_at": "2026-08-11T00:00:00+00:00",
        }


class TestContentHash:
    def test_deterministic(self):
        assert content_hash("hello") == content_hash("hello")

    def test_different_content_different_hash(self):
        assert content_hash("hello") != content_hash("world")
