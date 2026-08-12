"""tests/test_knowledge_chronolog.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from knowledge_engine.chronolog import append_log_entry, read_log

pytestmark = pytest.mark.unit


class TestAppendLogEntry:
    def test_creates_log_with_header_on_first_write(self, tmp_path):
        append_log_entry("ingest", "trade-42", knowledge_root=tmp_path)
        text = (tmp_path / "log.md").read_text(encoding="utf-8")
        assert "Knowledge Log" in text
        assert "ingest | trade-42" in text

    def test_format_matches_spec(self, tmp_path):
        append_log_entry("update", "agent-smc", knowledge_root=tmp_path)
        lines = read_log(tmp_path)
        assert len(lines) == 1
        assert lines[0].startswith("[")
        assert "] update | agent-smc" in lines[0]

    def test_includes_optional_detail(self, tmp_path):
        append_log_entry("contradiction", "agent-futures", knowledge_root=tmp_path, detail="win_rate 0.30 -> 0.65")
        lines = read_log(tmp_path)
        assert "win_rate 0.30 -> 0.65" in lines[0]

    def test_rejects_unknown_event(self, tmp_path):
        with pytest.raises(ValueError):
            append_log_entry("delete_everything", "trade-1", knowledge_root=tmp_path)

    def test_rejects_empty_entity(self, tmp_path):
        with pytest.raises(ValueError):
            append_log_entry("ingest", "", knowledge_root=tmp_path)

    def test_multiple_appends_never_lose_prior_lines(self, tmp_path):
        append_log_entry("ingest", "trade-1", knowledge_root=tmp_path)
        append_log_entry("ingest", "trade-2", knowledge_root=tmp_path)
        append_log_entry("update", "agent-smc", knowledge_root=tmp_path)
        lines = read_log(tmp_path)
        assert len(lines) == 3
        assert "trade-1" in lines[0]
        assert "trade-2" in lines[1]
        assert "agent-smc" in lines[2]

    def test_header_written_exactly_once(self, tmp_path):
        append_log_entry("ingest", "trade-1", knowledge_root=tmp_path)
        append_log_entry("ingest", "trade-2", knowledge_root=tmp_path)
        text = (tmp_path / "log.md").read_text(encoding="utf-8")
        assert text.count("Knowledge Log") == 1


class TestReadLog:
    def test_empty_when_no_log_file(self, tmp_path):
        assert read_log(tmp_path) == []
