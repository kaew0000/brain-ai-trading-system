"""tests/test_knowledge_contradiction.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from knowledge_engine.contradiction import (
    append_revision_history,
    detect_contradiction,
    format_revision_entry,
)

pytestmark = pytest.mark.unit


class TestDetectContradiction:
    def test_supporting_evidence_not_a_contradiction(self):
        # small move, well within threshold
        assert detect_contradiction(0.60, 0.62) is False

    def test_contradictory_evidence_detected(self):
        # win rate swings from 30% to 65% — a real contradiction
        assert detect_contradiction(0.30, 0.65) is True

    def test_refinement_within_threshold_not_flagged(self):
        assert detect_contradiction(0.50, 0.55, threshold=0.15) is False

    def test_zero_to_nonzero_is_a_contradiction(self):
        assert detect_contradiction(0.0, 0.40) is True

    def test_zero_to_zero_is_not(self):
        assert detect_contradiction(0.0, 0.0) is False

    def test_custom_threshold_respected(self):
        assert detect_contradiction(0.50, 0.58, threshold=0.05) is True
        assert detect_contradiction(0.50, 0.58, threshold=0.20) is False


class TestFormatRevisionEntry:
    def test_contains_all_required_fields(self):
        entry = format_revision_entry(
            previous_claim="win_rate=0.30",
            new_evidence="win_rate=0.65 over 12 trades",
            synthesis="Win rate has improved substantially.",
            source_refs=["journal_v2.get_agent_performance()"],
        )
        assert "win_rate=0.30" in entry
        assert "win_rate=0.65 over 12 trades" in entry
        assert "improved substantially" in entry
        assert "journal_v2.get_agent_performance()" in entry

    def test_empty_source_refs_handled(self):
        entry = format_revision_entry("a", "b", "c", [])
        assert "(none recorded)" in entry


class TestAppendRevisionHistory:
    def test_creates_section_if_absent(self):
        body = "## Current Synthesis\n\nsomething"
        result = append_revision_history(body, "### entry one\n\ndetails\n")
        assert "## Revision History" in result
        assert "entry one" in result

    def test_prepends_new_entry_preserving_old_ones(self):
        body = "## Current Synthesis\n\nX\n\n## Revision History\n\n### old entry\n\nold details\n"
        result = append_revision_history(body, "### new entry\n\nnew details\n")
        assert result.index("new entry") < result.index("old entry")
        assert "old details" in result  # nothing lost

    def test_never_deletes_prior_entries_across_multiple_appends(self):
        body = "## Current Synthesis\n\nX\n"
        body = append_revision_history(body, "### entry 1\n\nfirst\n")
        body = append_revision_history(body, "### entry 2\n\nsecond\n")
        body = append_revision_history(body, "### entry 3\n\nthird\n")
        assert "entry 1" in body and "first" in body
        assert "entry 2" in body and "second" in body
        assert "entry 3" in body and "third" in body
        # newest first
        assert body.index("entry 3") < body.index("entry 2") < body.index("entry 1")
