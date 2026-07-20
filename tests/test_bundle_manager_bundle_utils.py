"""tests/test_bundle_manager_bundle_utils.py — Bundle Manager"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from tools import bundle_utils

pytestmark = pytest.mark.unit


class TestFindIncomingBundles:

    def test_finds_bundle_and_bundle_txt(self, tmp_path):
        (tmp_path / "a.bundle").write_bytes(b"x")
        (tmp_path / "b.bundle.txt").write_bytes(b"x")
        (tmp_path / "readme.md").write_bytes(b"x")   # must be ignored
        found = bundle_utils.find_incoming_bundles(tmp_path)
        assert {p.name for p in found} == {"a.bundle", "b.bundle.txt"}

    def test_missing_dir_returns_empty_list(self, tmp_path):
        assert bundle_utils.find_incoming_bundles(tmp_path / "does_not_exist") == []

    def test_does_not_recurse_into_subdirectories(self, tmp_path):
        sub = tmp_path / "parked"
        sub.mkdir()
        (sub / "hidden.bundle").write_bytes(b"x")
        assert bundle_utils.find_incoming_bundles(tmp_path) == []

    def test_ordered_oldest_first(self, tmp_path):
        first = tmp_path / "first.bundle"
        second = tmp_path / "second.bundle"
        first.write_bytes(b"x")
        time.sleep(0.01)
        second.write_bytes(b"x")
        found = bundle_utils.find_incoming_bundles(tmp_path)
        assert [p.name for p in found] == ["first.bundle", "second.bundle"]

    def test_ignores_directories_matching_the_extension(self, tmp_path):
        (tmp_path / "not_really_a_file.bundle").mkdir()
        assert bundle_utils.find_incoming_bundles(tmp_path) == []


class TestExtractBranchAndSha:

    def test_single_branch_head_extracted(self, tmp_path):
        with patch("tools.bundle_utils.git_utils.list_bundle_heads",
                    return_value=[("sha123", "refs/heads/feature/x")]):
            info = bundle_utils.extract_branch_and_sha(tmp_path / "x.bundle", tmp_path)
        assert info.branch == "feature/x"
        assert info.sha == "sha123"

    def test_no_heads_raises_bundle_format_error(self, tmp_path):
        with patch("tools.bundle_utils.git_utils.list_bundle_heads", return_value=[]):
            with pytest.raises(bundle_utils.BundleFormatError):
                bundle_utils.extract_branch_and_sha(tmp_path / "x.bundle", tmp_path)

    def test_only_tag_refs_raises_bundle_format_error(self, tmp_path):
        """A bundle with only refs/tags/* (no refs/heads/*) has nothing
        this tool considers a feature branch."""
        with patch("tools.bundle_utils.git_utils.list_bundle_heads",
                    return_value=[("sha1", "refs/tags/v1.0")]):
            with pytest.raises(bundle_utils.BundleFormatError):
                bundle_utils.extract_branch_and_sha(tmp_path / "x.bundle", tmp_path)

    def test_multiple_branch_heads_raises_bundle_format_error(self, tmp_path):
        with patch("tools.bundle_utils.git_utils.list_bundle_heads",
                    return_value=[("sha1", "refs/heads/a"), ("sha2", "refs/heads/b")]):
            with pytest.raises(bundle_utils.BundleFormatError) as exc_info:
                bundle_utils.extract_branch_and_sha(tmp_path / "x.bundle", tmp_path)
        assert "2 branches" in str(exc_info.value)

    def test_tag_refs_alongside_one_branch_head_still_extracts_the_branch(self, tmp_path):
        with patch("tools.bundle_utils.git_utils.list_bundle_heads",
                    return_value=[("sha1", "refs/heads/feature/x"), ("sha2", "refs/tags/v1.0")]):
            info = bundle_utils.extract_branch_and_sha(tmp_path / "x.bundle", tmp_path)
        assert info.branch == "feature/x"


class TestEnsureBundleDirs:

    def test_creates_all_three(self, tmp_path):
        incoming, applied, failed = tmp_path / "in", tmp_path / "ok", tmp_path / "bad"
        bundle_utils.ensure_bundle_dirs(incoming, applied, failed)
        assert incoming.is_dir() and applied.is_dir() and failed.is_dir()

    def test_idempotent(self, tmp_path):
        incoming, applied, failed = tmp_path / "in", tmp_path / "ok", tmp_path / "bad"
        bundle_utils.ensure_bundle_dirs(incoming, applied, failed)
        bundle_utils.ensure_bundle_dirs(incoming, applied, failed)   # must not raise
        assert incoming.is_dir()


class TestMoveBundle:

    def test_moves_file_to_destination(self, tmp_path):
        src_dir = tmp_path / "incoming"; src_dir.mkdir()
        dst_dir = tmp_path / "applied"
        src = src_dir / "x.bundle"
        src.write_bytes(b"content")

        result = bundle_utils.move_bundle(src, dst_dir)
        assert result == dst_dir / "x.bundle"
        assert result.exists()
        assert not src.exists()

    def test_creates_destination_dir_if_missing(self, tmp_path):
        src_dir = tmp_path / "incoming"; src_dir.mkdir()
        src = src_dir / "x.bundle"
        src.write_bytes(b"content")
        dst_dir = tmp_path / "does" / "not" / "exist"

        bundle_utils.move_bundle(src, dst_dir)
        assert dst_dir.is_dir()

    def test_name_collision_gets_numeric_suffix_not_overwritten(self, tmp_path):
        src_dir = tmp_path / "incoming"; src_dir.mkdir()
        dst_dir = tmp_path / "applied"; dst_dir.mkdir()
        (dst_dir / "x.bundle").write_bytes(b"OLD CONTENT")
        src = src_dir / "x.bundle"
        src.write_bytes(b"NEW CONTENT")

        result = bundle_utils.move_bundle(src, dst_dir)
        assert result.name == "x.1.bundle"
        assert (dst_dir / "x.bundle").read_bytes() == b"OLD CONTENT"   # untouched
        assert result.read_bytes() == b"NEW CONTENT"

    def test_name_collision_preserves_bundle_txt_extension(self, tmp_path):
        src_dir = tmp_path / "incoming"; src_dir.mkdir()
        dst_dir = tmp_path / "applied"; dst_dir.mkdir()
        (dst_dir / "x.bundle.txt").write_bytes(b"OLD")
        src = src_dir / "x.bundle.txt"
        src.write_bytes(b"NEW")

        result = bundle_utils.move_bundle(src, dst_dir)
        assert result.name == "x.1.bundle.txt"

    def test_dotted_filename_stem_preserved_correctly(self, tmp_path):
        """Regression guard: a filename with dots in the meaningful part
        (not just the extension) must not have its stem mangled."""
        src_dir = tmp_path / "incoming"; src_dir.mkdir()
        dst_dir = tmp_path / "applied"; dst_dir.mkdir()
        (dst_dir / "brain_bot.v16.phase2a.bundle").write_bytes(b"OLD")
        src = src_dir / "brain_bot.v16.phase2a.bundle"
        src.write_bytes(b"NEW")

        result = bundle_utils.move_bundle(src, dst_dir)
        assert result.name == "brain_bot.v16.phase2a.1.bundle"
