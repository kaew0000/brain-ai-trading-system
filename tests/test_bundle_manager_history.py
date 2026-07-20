"""tests/test_bundle_manager_history.py — Bundle Manager

Uses real file I/O against pytest's tmp_path — no git/network involved,
so nothing to mock here (unlike the other Bundle Manager test files).
"""
from __future__ import annotations

import json

import pytest

from tools.history import BundleHistory

pytestmark = pytest.mark.unit


class TestFreshHistory:

    def test_missing_file_starts_empty(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        assert h.all_records() == []
        assert h.has_sha("anything") is False

    def test_corrupt_existing_file_raises_rather_than_assuming_empty(self, tmp_path):
        p = tmp_path / "bundle_history.json"
        p.write_text("{ not valid json", encoding="utf-8")
        with pytest.raises(RuntimeError):
            BundleHistory(p)


class TestApplyAndDuplicateDetection:

    def test_applied_sha_is_a_duplicate(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        assert h.has_sha("sha1") is True

    def test_unknown_sha_is_not_a_duplicate(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        assert h.has_sha("sha2") is False

    def test_failed_sha_is_not_treated_as_a_duplicate(self, tmp_path):
        """A previously-failed import (e.g. transient push failure) must
        not permanently block retrying the same bundle once whatever
        broke it is fixed."""
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_failed("sha1", "feature/x", "x.bundle", reason="push timed out")
        assert h.has_sha("sha1") is False

    def test_retry_after_failure_upgrades_to_applied(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_failed("sha1", "feature/x", "x.bundle", reason="push timed out")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        assert h.has_sha("sha1") is True
        assert len(h.all_records()) == 1   # superseded, not appended as a second entry

    def test_get_returns_full_record(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        record = h.get("sha1")
        assert record.branch == "feature/x"
        assert record.pushed is True

    def test_get_missing_sha_returns_none(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        assert h.get("nope") is None


class TestPersistence:

    def test_save_and_reload_round_trips(self, tmp_path):
        p = tmp_path / "bundle_history.json"
        h1 = BundleHistory(p)
        h1.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        h1.record_failed("sha2", "feature/y", "y.bundle", reason="verify failed")
        h1.save()

        h2 = BundleHistory(p)
        assert h2.has_sha("sha1") is True
        assert h2.get("sha2").status == "failed"
        assert h2.get("sha2").reason == "verify failed"

    def test_save_writes_valid_json_with_expected_schema(self, tmp_path):
        p = tmp_path / "bundle_history.json"
        h = BundleHistory(p)
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=False)
        h.save()

        raw = json.loads(p.read_text(encoding="utf-8"))
        assert raw["schema_version"] == 1
        assert "updated_at" in raw
        assert raw["records"][0]["sha"] == "sha1"
        assert raw["records"][0]["pushed"] is False

    def test_save_creates_parent_directory(self, tmp_path):
        p = tmp_path / "nested" / "dir" / "bundle_history.json"
        h = BundleHistory(p)
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        h.save()
        assert p.exists()

    def test_no_leftover_temp_file_after_save(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        h.save()
        leftovers = list(tmp_path.glob(".bundle_history_*"))
        assert leftovers == []

    def test_unrelated_files_in_directory_are_not_disturbed(self, tmp_path):
        (tmp_path / "other_file.txt").write_text("keep me")
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        h.save()
        assert (tmp_path / "other_file.txt").read_text() == "keep me"


class TestAllRecordsIsolation:

    def test_all_records_returns_a_copy_not_the_live_list(self, tmp_path):
        h = BundleHistory(tmp_path / "bundle_history.json")
        h.record_applied("sha1", "feature/x", "x.bundle", pushed=True)
        records = h.all_records()
        records.clear()
        assert len(h.all_records()) == 1   # mutating the returned list must not affect internal state
