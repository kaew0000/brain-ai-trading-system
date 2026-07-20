"""tests/test_bundle_manager_sync.py — Bundle Manager"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from tools import git_utils, sync
from tools.history import BundleHistory

pytestmark = pytest.mark.unit


def _history(tmp_path) -> BundleHistory:
    return BundleHistory(tmp_path / "bundle_history.json")


class TestBaseBranchMustExist:

    def test_missing_base_branch_raises(self, tmp_path):
        history = _history(tmp_path)
        with patch("tools.sync.git_utils.branch_exists", return_value=False):
            with pytest.raises(git_utils.GitCommandError):
                sync.sync_main(tmp_path, history, base_branch="main")


class TestFastForward:

    def test_reports_fast_forward_when_sha_changes(self, tmp_path):
        history = _history(tmp_path)
        shas = iter(["old_sha", "new_sha"])   # before, then after pull
        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", side_effect=lambda *a, **k: next(shas)), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune"), \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", return_value=False):
            result = sync.sync_main(tmp_path, history, base_branch="main")

        assert result.fast_forwarded is True
        assert result.before_sha == "old_sha"
        assert result.after_sha == "new_sha"

    def test_reports_not_fast_forwarded_when_already_up_to_date(self, tmp_path):
        history = _history(tmp_path)
        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="same_sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune"), \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", return_value=False):
            result = sync.sync_main(tmp_path, history, base_branch="main")
        assert result.fast_forwarded is False

    def test_checks_out_base_branch_if_not_already_on_it(self, tmp_path):
        history = _history(tmp_path)
        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="feature/x"), \
             patch("tools.sync.git_utils.checkout_branch") as checkout, \
             patch("tools.sync.git_utils.fetch_prune"), \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", return_value=False):
            sync.sync_main(tmp_path, history, base_branch="main")
        checkout.assert_called_once_with("main", tmp_path, timeout=120)

    def test_never_calls_merge_or_reset(self, tmp_path):
        """Structural guard: sync must only ever call pull_fast_forward,
        never a plain merge/reset — enforced by only stubbing the
        fast-forward path and asserting run_git wasn't used for anything
        merge/reset-shaped."""
        history = _history(tmp_path)
        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune"), \
             patch("tools.sync.git_utils.pull_fast_forward") as pull, \
             patch("tools.sync.git_utils.run_git") as run_git, \
             patch("tools.sync.git_utils.is_ancestor", return_value=False):
            sync.sync_main(tmp_path, history, base_branch="main")
        pull.assert_called_once()
        for call in run_git.call_args_list:
            args = call[0][0]
            assert args[0] not in ("merge", "reset")


class TestPrune:

    def test_prune_true_calls_fetch_prune(self, tmp_path):
        history = _history(tmp_path)
        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune") as fetch_prune, \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", return_value=False):
            result = sync.sync_main(tmp_path, history, base_branch="main", prune=True)
        fetch_prune.assert_called_once()
        assert result.pruned is True

    def test_prune_false_uses_plain_fetch(self, tmp_path):
        history = _history(tmp_path)
        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune") as fetch_prune, \
             patch("tools.sync.git_utils.run_git") as run_git, \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", return_value=False):
            result = sync.sync_main(tmp_path, history, base_branch="main", prune=False)
        fetch_prune.assert_not_called()
        run_git.assert_called_once()
        assert result.pruned is False


class TestNewlyMergedDetection:

    def test_identifies_applied_records_now_merged_into_base(self, tmp_path):
        history = _history(tmp_path)
        history.record_applied("sha_merged", "feature/a", "a.bundle", pushed=True)
        history.record_applied("sha_not_merged", "feature/b", "b.bundle", pushed=True)
        history.record_failed("sha_failed", "feature/c", "c.bundle", reason="x")

        def is_ancestor(ref, base, cwd):
            return ref == "sha_merged"

        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune"), \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", side_effect=is_ancestor):
            result = sync.sync_main(tmp_path, history, base_branch="main")

        assert result.newly_merged_shas == ["sha_merged"]

    def test_failed_records_never_checked_for_merge_status(self, tmp_path):
        history = _history(tmp_path)
        history.record_failed("sha_failed", "feature/c", "c.bundle", reason="x")
        checked_shas = []

        def is_ancestor(ref, base, cwd):
            checked_shas.append(ref)
            return False

        with patch("tools.sync.git_utils.branch_exists", return_value=True), \
             patch("tools.sync.git_utils.rev_parse", return_value="sha"), \
             patch("tools.sync.git_utils.get_current_branch", return_value="main"), \
             patch("tools.sync.git_utils.fetch_prune"), \
             patch("tools.sync.git_utils.pull_fast_forward"), \
             patch("tools.sync.git_utils.is_ancestor", side_effect=is_ancestor):
            sync.sync_main(tmp_path, history, base_branch="main")

        assert "sha_failed" not in checked_shas
