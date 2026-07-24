"""tests/test_bundle_manager_git_utils.py — Bundle Manager

Every test mocks subprocess.run (via tools.git_utils.subprocess.run) —
no real git process is ever spawned, matching this project's "mock
everything, no network" test convention.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools import git_utils

pytestmark = pytest.mark.unit


def _completed(returncode=0, stdout="", stderr=""):
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


class TestResolveGit:

    def test_raises_if_git_not_on_path(self):
        git_utils._GIT_EXE = None
        with patch("tools.git_utils.shutil.which", return_value=None):
            with pytest.raises(git_utils.GitNotFoundError):
                git_utils._resolve_git()
        git_utils._GIT_EXE = None  # reset for other tests

    def test_caches_resolved_path(self):
        git_utils._GIT_EXE = None
        with patch("tools.git_utils.shutil.which", return_value="/usr/bin/git") as which:
            first = git_utils._resolve_git()
            second = git_utils._resolve_git()
        assert first == second == "/usr/bin/git"
        which.assert_called_once()
        git_utils._GIT_EXE = None


class TestRunGit:

    def test_successful_call_returns_result(self):
        with patch("tools.git_utils.shutil.which", return_value="/usr/bin/git"), \
             patch("tools.git_utils.subprocess.run", return_value=_completed(0, "ok\n", "")):
            result = git_utils.run_git(["status"], cwd=Path("."))
        assert result.returncode == 0
        assert result.stdout == "ok\n"

    def test_nonzero_exit_raises_when_check_true(self):
        with patch("tools.git_utils.shutil.which", return_value="/usr/bin/git"), \
             patch("tools.git_utils.subprocess.run", return_value=_completed(1, "", "fatal: bad")):
            with pytest.raises(git_utils.GitCommandError) as exc_info:
                git_utils.run_git(["nope"], cwd=Path("."))
        assert exc_info.value.returncode == 1
        assert "fatal: bad" in exc_info.value.stderr

    def test_nonzero_exit_does_not_raise_when_check_false(self):
        with patch("tools.git_utils.shutil.which", return_value="/usr/bin/git"), \
             patch("tools.git_utils.subprocess.run", return_value=_completed(1, "", "err")):
            result = git_utils.run_git(["nope"], cwd=Path("."), check=False)
        assert result.returncode == 1

    def test_timeout_raises_git_command_error(self):
        import subprocess as sp
        with patch("tools.git_utils.shutil.which", return_value="/usr/bin/git"), \
             patch("tools.git_utils.subprocess.run",
                   side_effect=sp.TimeoutExpired(cmd="git", timeout=5)), pytest.raises(git_utils.GitCommandError):
            git_utils.run_git(["fetch"], cwd=Path("."), timeout=5)

    def test_uses_list_form_never_shell(self):
        """Structural guard against shell=True (injection surface) —
        confirms the call site never passes shell=True."""
        with patch("tools.git_utils.shutil.which", return_value="/usr/bin/git"), \
             patch("tools.git_utils.subprocess.run", return_value=_completed(0)) as run:
            git_utils.run_git(["status"], cwd=Path("."))
        _, kwargs = run.call_args
        assert kwargs.get("shell") is not True


class TestVerifyBundle:

    def test_valid_bundle_returns_true(self):
        with patch("tools.git_utils.run_git",
                    return_value=git_utils.GitResult([], 0, "bundle is okay", "")):
            ok, msg = git_utils.verify_bundle(Path("x.bundle"), Path("."))
        assert ok is True
        assert "okay" in msg

    def test_invalid_bundle_returns_false_not_raise(self):
        with patch("tools.git_utils.run_git",
                    return_value=git_utils.GitResult([], 1, "", "not a bundle")):
            ok, msg = git_utils.verify_bundle(Path("bad.bundle"), Path("."))
        assert ok is False
        assert "not a bundle" in msg


class TestListBundleHeads:

    def test_parses_single_head(self):
        stdout = "eaa51acdef6d1234567890 refs/heads/feature/x\n"
        with patch("tools.git_utils.run_git",
                    return_value=git_utils.GitResult([], 0, stdout, "")):
            heads = git_utils.list_bundle_heads(Path("x.bundle"), Path("."))
        assert heads == [("eaa51acdef6d1234567890", "refs/heads/feature/x")]

    def test_parses_multiple_heads(self):
        stdout = "sha1 refs/heads/feature/a\nsha2 refs/heads/feature/b\n"
        with patch("tools.git_utils.run_git",
                    return_value=git_utils.GitResult([], 0, stdout, "")):
            heads = git_utils.list_bundle_heads(Path("x.bundle"), Path("."))
        assert len(heads) == 2

    def test_empty_output_returns_empty_list(self):
        with patch("tools.git_utils.run_git",
                    return_value=git_utils.GitResult([], 0, "", "")):
            heads = git_utils.list_bundle_heads(Path("x.bundle"), Path("."))
        assert heads == []

    def test_ignores_blank_lines(self):
        stdout = "sha1 refs/heads/a\n\n\nsha2 refs/heads/b\n"
        with patch("tools.git_utils.run_git",
                    return_value=git_utils.GitResult([], 0, stdout, "")):
            heads = git_utils.list_bundle_heads(Path("x.bundle"), Path("."))
        assert len(heads) == 2


class TestFetchBranchFromBundle:

    def test_default_refspec_not_forced(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 0, "", "")) as run:
            git_utils.fetch_branch_from_bundle(Path("x.bundle"), "feature/x", Path("."))
        args = run.call_args[0][0]
        assert args[0] == "fetch"
        assert not args[-1].startswith("+")

    def test_force_prefixes_refspec_with_plus(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 0, "", "")) as run:
            git_utils.fetch_branch_from_bundle(Path("x.bundle"), "feature/x", Path("."), force=True)
        args = run.call_args[0][0]
        assert args[-1].startswith("+")


class TestBranchExists:

    def test_true_when_show_ref_succeeds(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 0, "", "")):
            assert git_utils.branch_exists("main", Path(".")) is True

    def test_false_when_show_ref_fails(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 1, "", "")):
            assert git_utils.branch_exists("nope", Path(".")) is False


class TestIsAncestor:

    def test_true_when_merge_base_succeeds(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 0, "", "")):
            assert git_utils.is_ancestor("abc", "main", Path(".")) is True

    def test_false_when_merge_base_fails(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 1, "", "")):
            assert git_utils.is_ancestor("abc", "main", Path(".")) is False


class TestPushBranch:

    def test_success_on_first_attempt_no_sleep(self):
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 0, "", "")), \
             patch("tools.git_utils.time.sleep") as sleep:
            git_utils.push_branch("feature/x", Path("."), retries=3)
        sleep.assert_not_called()

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def side_effect(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                raise git_utils.GitCommandError(["push"], 1, "", "transient network error")
            return git_utils.GitResult([], 0, "", "")

        with patch("tools.git_utils.run_git", side_effect=side_effect), \
             patch("tools.git_utils.time.sleep") as sleep:
            git_utils.push_branch("feature/x", Path("."), retries=3)
        assert calls["n"] == 3
        assert sleep.call_count == 2

    def test_exhausts_retries_and_raises(self):
        with patch("tools.git_utils.run_git",
                    side_effect=git_utils.GitCommandError(["push"], 1, "", "permanently rejected")), \
             patch("tools.git_utils.time.sleep"), pytest.raises(git_utils.GitCommandError):
            git_utils.push_branch("feature/x", Path("."), retries=2)

    def test_force_uses_force_with_lease_not_bare_force(self):
        """--force-with-lease, never a bare --force — safety: refuses to
        clobber a remote branch someone else has moved since we last saw it."""
        with patch("tools.git_utils.run_git", return_value=git_utils.GitResult([], 0, "", "")) as run:
            git_utils.push_branch("feature/x", Path("."), force=True, retries=1)
        args = run.call_args[0][0]
        assert "--force-with-lease" in args
        assert "--force" not in [a for a in args if a == "--force"]
