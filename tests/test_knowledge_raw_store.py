"""tests/test_knowledge_raw_store.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from knowledge_engine.raw_store import (
    InvalidSourceError,
    SecretDetectedError,
    ingest_raw_source,
)

pytestmark = pytest.mark.unit


class TestValidIngestion:
    def test_stages_content_under_category(self, tmp_path):
        record = ingest_raw_source("Funding rate spiked on BTCUSDT.", "market_notes", "2026-08-11-funding", raw_root=tmp_path)
        assert record.category == "market_notes"
        assert record.already_existed is False
        assert record.path.exists()
        assert record.path.read_text(encoding="utf-8") == "Funding rate spiked on BTCUSDT."
        assert record.path.parent == tmp_path / "market_notes"

    def test_sha256_matches_content(self, tmp_path):
        import hashlib
        text = "some research note"
        record = ingest_raw_source(text, "research", "note", raw_root=tmp_path)
        assert record.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()


class TestInvalidIngestion:
    def test_unknown_category_rejected(self, tmp_path):
        with pytest.raises(InvalidSourceError):
            ingest_raw_source("text", "not_a_real_category", "name", raw_root=tmp_path)

    def test_empty_content_rejected(self, tmp_path):
        with pytest.raises(InvalidSourceError):
            ingest_raw_source("   ", "research", "name", raw_root=tmp_path)

    def test_name_with_no_safe_characters_rejected(self, tmp_path):
        with pytest.raises(InvalidSourceError):
            ingest_raw_source("text", "research", "!!!///", raw_root=tmp_path)


class TestDuplicateIngestion:
    def test_identical_content_same_name_is_noop(self, tmp_path):
        r1 = ingest_raw_source("identical content", "incidents", "incident-1", raw_root=tmp_path)
        r2 = ingest_raw_source("identical content", "incidents", "incident-1", raw_root=tmp_path)
        assert r2.already_existed is True
        assert r2.path == r1.path
        assert len(list((tmp_path / "incidents").glob("*.md"))) == 1

    def test_different_content_same_name_creates_new_file_not_overwrite(self, tmp_path):
        r1 = ingest_raw_source("version one", "incidents", "incident-1", raw_root=tmp_path)
        r2 = ingest_raw_source("version two", "incidents", "incident-1", raw_root=tmp_path)
        assert r1.path != r2.path
        assert r1.path.exists()  # original never overwritten
        assert r1.path.read_text(encoding="utf-8") == "version one"
        assert r2.path.read_text(encoding="utf-8") == "version two"


class TestSecretDetection:
    def test_refuses_private_key_block(self, tmp_path):
        with pytest.raises(SecretDetectedError):
            ingest_raw_source("-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQ...\n", "operator_notes", "oops", raw_root=tmp_path)

    def test_refuses_binance_api_secret_pattern(self, tmp_path):
        with pytest.raises(SecretDetectedError):
            ingest_raw_source("BINANCE_API_SECRET: abcdefghijklmnopqrstuvwxyz123456", "operator_notes", "oops", raw_root=tmp_path)

    def test_refuses_generic_api_key_assignment(self, tmp_path):
        with pytest.raises(SecretDetectedError):
            ingest_raw_source('api_key = "sk_live_abcdefghijklmnopqrstuvwx"', "operator_notes", "oops", raw_root=tmp_path)

    def test_ordinary_note_is_not_flagged(self, tmp_path):
        # sanity check the patterns aren't so broad they block real notes
        record = ingest_raw_source(
            "Today's market regime looks TRENDING on BTCUSDT with strong momentum.",
            "market_notes", "ordinary-note", raw_root=tmp_path,
        )
        assert record.already_existed is False

    def test_secret_content_is_never_written_to_disk(self, tmp_path):
        try:
            ingest_raw_source("BINANCE_API_SECRET: abcdefghijklmnopqrstuvwxyz123456", "operator_notes", "oops", raw_root=tmp_path)
        except SecretDetectedError:
            pass
        written_files = list((tmp_path / "operator_notes").glob("*.md")) if (tmp_path / "operator_notes").exists() else []
        assert written_files == []
