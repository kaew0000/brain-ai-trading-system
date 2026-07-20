"""tests/test_bundle_manager_github_actions.py — Bundle Manager

import_bundle() ties bundle_utils + git_utils + history together — these
tests mock the first two and use a real (tmp_path-backed) BundleHistory,
so the orchestration logic itself (branching between success/duplicate/
failure/dry-run paths) is exercised directly without any real git call.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools import github_actions
from tools.bundle_utils import BundleFormatError, BundleInfo
from tools.git_utils import GitCommandError
from tools.history import BundleHistory

pytestmark = pytest.mark.unit


def _history(tmp_path) -> BundleHistory:
    return BundleHistory(tmp_path / "bundle_history.json")


def _ok_bundle_mocks(branch="feature/x", sha="sha123"):
    """Context managers patching verify_bundle (ok) and
    extract_branch_and_sha (returns a fixed BundleInfo)."""
    return (
        patch("tools.github_actions.git_utils.verify_bundle", return_value=(True, "ok")),
        patch("tools.github_actions.bundle_utils.extract_branch_and_sha",
              return_value=BundleInfo(path=Path("x.bundle"), branch=branch, sha=sha)),
    )


class TestVerifyFailure:

    def test_failed_verify_routes_to_failed_and_records_nothing(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        with patch("tools.github_actions.git_utils.verify_bundle",
                    return_value=(False, "not a bundle")):
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed,
            )

        assert result.status == "failed"
        assert "not a bundle" in result.reason
        assert (failed / "x.bundle").exists()
        assert not (tmp_path / "x.bundle").exists()
        # No SHA was ever extracted, so nothing meaningful to record —
        # history stays empty rather than recording a None-keyed entry.
        assert history.all_records() == []


class TestBundleFormatFailure:

    def test_multi_branch_bundle_routes_to_failed(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        with patch("tools.github_actions.git_utils.verify_bundle", return_value=(True, "ok")), \
             patch("tools.github_actions.bundle_utils.extract_branch_and_sha",
                   side_effect=BundleFormatError("2 branches found")):
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed,
            )

        assert result.status == "failed"
        assert "2 branches" in result.reason
        assert (failed / "x.bundle").exists()


class TestDuplicateDetection:

    def test_already_applied_sha_is_skipped_not_reimported(self, tmp_path):
        history = _history(tmp_path)
        history.record_applied("sha123", "feature/x", "old.bundle", pushed=True)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks(sha="sha123")
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle") as fetch, \
             patch("tools.github_actions.git_utils.push_branch") as push:
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed,
            )

        assert result.status == "skipped_duplicate"
        fetch.assert_not_called()
        push.assert_not_called()
        assert (applied / "x.bundle").exists()   # still filed away, just not re-fetched/pushed


class TestDryRun:

    def test_dry_run_never_touches_git_or_filesystem(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks()
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle") as fetch, \
             patch("tools.github_actions.git_utils.checkout_branch") as checkout, \
             patch("tools.github_actions.git_utils.push_branch") as push:
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed, dry_run=True,
            )

        assert result.status == "dry_run"
        fetch.assert_not_called()
        checkout.assert_not_called()
        push.assert_not_called()
        assert (tmp_path / "x.bundle").exists()   # not moved
        assert history.all_records() == []        # not recorded

    def test_dry_run_still_reports_duplicate(self, tmp_path):
        history = _history(tmp_path)
        history.record_applied("sha123", "feature/x", "old.bundle", pushed=True)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks(sha="sha123")
        with ok_mock, extract_mock:
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed, dry_run=True,
            )
        assert result.status == "dry_run"
        assert "duplicate" in result.reason


class TestSuccessfulImport:

    def test_full_success_path_checks_out_base_branch_first(self, tmp_path):
        """Regression guard for the real bug caught during manual
        end-to-end testing: git refuses to fetch into the branch that's
        currently checked out, so import_bundle must checkout the base
        branch BEFORE fetching the feature branch."""
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        call_order = []
        ok_mock, extract_mock = _ok_bundle_mocks(branch="feature/x", sha="sha123")
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.get_current_branch", return_value="feature/other"), \
             patch("tools.github_actions.git_utils.branch_exists", return_value=True), \
             patch("tools.github_actions.git_utils.checkout_branch",
                   side_effect=lambda b, *a, **k: call_order.append(("checkout", b))), \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle",
                   side_effect=lambda *a, **k: call_order.append(("fetch",))), \
             patch("tools.github_actions.git_utils.push_branch",
                   side_effect=lambda *a, **k: call_order.append(("push",))):
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed, base_branch="main",
            )

        assert result.status == "applied"
        assert call_order == [("checkout", "main"), ("fetch",), ("checkout", "feature/x"), ("push",)]
        assert history.has_sha("sha123") is True
        assert (applied / "x.bundle").exists()

    def test_skips_base_branch_checkout_if_already_on_it(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks()
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.get_current_branch", return_value="main"), \
             patch("tools.github_actions.git_utils.checkout_branch") as checkout, \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle"), \
             patch("tools.github_actions.git_utils.push_branch"):
            github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed, base_branch="main",
            )
        # checkout_branch is still called once — for the feature branch —
        # but not a second redundant time for "main" it was already on.
        assert checkout.call_count == 1
        assert checkout.call_args[0][0] == "feature/x"

    def test_no_push_flag_skips_push_but_still_applies(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks(sha="sha123")
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.get_current_branch", return_value="main"), \
             patch("tools.github_actions.git_utils.checkout_branch"), \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle"), \
             patch("tools.github_actions.git_utils.push_branch") as push:
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed, push=False,
            )

        assert result.status == "applied"
        push.assert_not_called()
        assert history.get("sha123").pushed is False

    def test_base_branch_missing_locally_fails_safely(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks()
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.get_current_branch", return_value="feature/other"), \
             patch("tools.github_actions.git_utils.branch_exists", return_value=False):
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed, base_branch="main",
            )

        assert result.status == "failed"
        assert "does not exist locally" in result.reason


class TestFetchOrPushFailure:

    def test_fetch_failure_routes_to_failed_and_records_history(self, tmp_path):
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks(sha="sha123")
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.get_current_branch", return_value="main"), \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle",
                   side_effect=GitCommandError(["fetch"], 128, "", "non-fast-forward")):
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed,
            )

        assert result.status == "failed"
        assert "non-fast-forward" in result.reason
        assert (failed / "x.bundle").exists()
        assert history.get("sha123").status == "failed"

    def test_push_failure_still_routes_to_failed_even_though_fetch_and_checkout_succeeded(self, tmp_path):
        """If push fails after a successful local fetch+checkout, the
        bundle must still be filed as failed (not applied) — a branch
        that only exists locally, never reaching origin, isn't done."""
        history = _history(tmp_path)
        applied, failed = tmp_path / "applied", tmp_path / "failed"
        (tmp_path / "x.bundle").write_bytes(b"junk")

        ok_mock, extract_mock = _ok_bundle_mocks(sha="sha123")
        with ok_mock, extract_mock, \
             patch("tools.github_actions.git_utils.get_current_branch", return_value="main"), \
             patch("tools.github_actions.git_utils.checkout_branch"), \
             patch("tools.github_actions.git_utils.fetch_branch_from_bundle"), \
             patch("tools.github_actions.git_utils.push_branch",
                   side_effect=GitCommandError(["push"], 1, "", "rejected")):
            result = github_actions.import_bundle(
                tmp_path / "x.bundle", tmp_path, history, applied, failed,
            )

        assert result.status == "failed"
        assert (failed / "x.bundle").exists()
        assert (applied / "x.bundle").exists() is False
