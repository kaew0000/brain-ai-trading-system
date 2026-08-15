"""tests/test_bundle_manager_worktree_isolation.py — W14-2B

Bundle Manager Working-Tree Isolation Fix.

Unlike the rest of the Bundle Manager test suite (git_utils, github_actions,
cli — all fully mocked, see their docstrings), this file deliberately runs
against REAL local git repositories in tmp_path, with no mocking of git at
all. The property being verified — "does the working tree actually stay
clean" — is an emergent, observable filesystem/git-state property that a
mock of run_git() cannot demonstrate; asserting `mock.assert_not_called()`
would only prove our own code didn't call itself, not that `git status`
is actually clean afterward. See docs/architecture.md §21's own note that
a real bug in this package was previously caught by manual end-to-end
testing, not by the mocked unit suite — the precedent this file follows.

Everything here is fully local (git init in tmp_path, `git bundle create`
from a second local branch, --no-push throughout) — no network access,
consistent with pytest.ini's "unit: no external API calls" marker.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools import bundle_manager, git_utils
from tools.history import BundleHistory

pytestmark = pytest.mark.unit


# ── real-git fixtures (deliberately not going through tools.git_utils —
#    these set the stage the code under test then acts on) ────────────────

def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, (
        f"git {' '.join(args)} failed in {cwd}:\n{result.stdout}\n{result.stderr}"
    )
    return result


def _init_repo(repo_dir: Path) -> None:
    repo_dir.mkdir(parents=True, exist_ok=True)
    _git(["init", "--quiet"], repo_dir)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], repo_dir)
    _git(["config", "user.email", "w14-2b-test@example.com"], repo_dir)
    _git(["config", "user.name", "W14-2B Test"], repo_dir)
    (repo_dir / "README.md").write_text("initial\n")
    _git(["add", "README.md"], repo_dir)
    _git(["commit", "--quiet", "-m", "initial commit"], repo_dir)


def _make_feature_bundle(repo_dir: Path, bundle_path: Path, branch: str) -> str:
    """Branches off the repo's current `main`, commits one new file, bundles
    that branch as an incremental update against main, then removes the
    local branch again so the target repo doesn't already have it — mirrors
    a bundle arriving from a different machine. Returns the branch's head SHA."""
    _git(["checkout", "--quiet", "-b", branch], repo_dir)
    safe_name = branch.replace("/", "_")
    (repo_dir / f"{safe_name}.txt").write_text(f"payload for {branch}\n")
    _git(["add", "."], repo_dir)
    _git(["commit", "--quiet", "-m", f"add {branch}"], repo_dir)
    sha = _git(["rev-parse", "HEAD"], repo_dir).stdout.strip()
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    _git(["bundle", "create", str(bundle_path), f"main..{branch}"], repo_dir)
    _git(["checkout", "--quiet", "main"], repo_dir)
    _git(["branch", "--quiet", "-D", branch], repo_dir)
    return sha


def _dirty_files(repo_dir: Path) -> list[str]:
    """Tracked-file dirtiness only — the same definition
    tools.git_utils.get_dirty_files() (and therefore cmd_import's own
    preflight check) uses. Untracked files (e.g. update/applied/ picking
    up a newly-moved bundle) deliberately don't count: they never block
    `git checkout`, so they're not part of the property this file is
    verifying. Exercises the real production helper directly rather than
    re-deriving the same "what counts as dirty" logic a second time."""
    return git_utils.get_dirty_files(repo_dir)


def _import_args(repo_dir: Path, **overrides):
    parser = bundle_manager.build_parser()
    argv = ["import", "--repo", str(repo_dir), "--yes", "--no-push"]
    args = parser.parse_args(argv)
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


# ── Test A / Test G-equivalent: successful import, tree stays clean ───────

class TestSuccessfulImportStaysClean:

    def test_clean_tree_after_successful_import(self, tmp_path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        bundle_path = tmp_path / "bundles" / "feature_x.bundle"
        sha = _make_feature_bundle(repo, bundle_path, "feature/x")

        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_x.bundle").write_bytes(bundle_path.read_bytes())

        rc = bundle_manager.cmd_import(_import_args(repo))

        assert rc == 0
        assert _dirty_files(repo) == [], (
            "working tree must be clean immediately after a successful "
            "import — the explicit history.save() write must have been "
            "committed, not left dangling (W14-2B)"
        )

    def test_history_record_actually_persisted_and_committed(self, tmp_path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        bundle_path = tmp_path / "bundles" / "feature_y.bundle"
        sha = _make_feature_bundle(repo, bundle_path, "feature/y")
        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_y.bundle").write_bytes(bundle_path.read_bytes())

        rc = bundle_manager.cmd_import(_import_args(repo))
        assert rc == 0

        history_path = repo / "bundle_history.json"
        assert history_path.exists()
        on_disk = json.loads(history_path.read_text())
        shas_on_disk = [r["sha"] for r in on_disk["records"]]
        assert sha in shas_on_disk

        # Test D — explicit history persistence still works: not just
        # written to the working copy, but actually committed to git.
        committed = _git(["show", "HEAD:bundle_history.json"], repo).stdout
        committed_shas = [r["sha"] for r in json.loads(committed)["records"]]
        assert sha in committed_shas

        log = _git(["log", "-1", "--format=%s"], repo).stdout.strip()
        assert log == "sync bundle history"

    def test_reloading_history_from_disk_recognizes_the_import(self, tmp_path):
        """A fresh BundleHistory() load (simulating a new process / a
        different machine after a fresh clone) must see the same record —
        nothing was lost by committing it (Section 8's no-history-loss rule)."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        bundle_path = tmp_path / "bundles" / "feature_z.bundle"
        sha = _make_feature_bundle(repo, bundle_path, "feature/z")
        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_z.bundle").write_bytes(bundle_path.read_bytes())

        rc = bundle_manager.cmd_import(_import_args(repo))
        assert rc == 0

        reloaded = BundleHistory(repo / "bundle_history.json")
        assert reloaded.has_sha(sha)


# ── Test F: repeated invocation with nothing new never accumulates dirt ───

class TestRepeatedInvocation:

    def test_running_import_again_with_empty_incoming_stays_clean(self, tmp_path):
        repo = tmp_path / "repo"
        _init_repo(repo)
        bundle_path = tmp_path / "bundles" / "feature_a.bundle"
        _make_feature_bundle(repo, bundle_path, "feature/a")
        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_a.bundle").write_bytes(bundle_path.read_bytes())

        rc1 = bundle_manager.cmd_import(_import_args(repo))
        assert rc1 == 0
        assert _dirty_files(repo) == []

        # incoming/ is now empty (bundle moved to applied/) — run again,
        # three times, and confirm no dirt ever accumulates.
        for _ in range(3):
            rc = bundle_manager.cmd_import(_import_args(repo))
            assert rc == 0
            assert _dirty_files(repo) == []


# ── Test A/E/the actual reported bug: failure doesn't lock out the future ──

class TestFailureDoesNotBlockFutureRetries:
    """The exact scenario W14-2B fixes: before this fix, a failed real-pass
    attempt still called history.save() unconditionally, leaving
    bundle_history.json dirty and uncommitted — which then tripped
    get_dirty_files()'s preflight check on *every subsequent* cmd_import
    invocation, including ones for entirely unrelated bundles, until a
    human manually committed it by hand."""

    def _repo_with_conflicting_local_branch(self, tmp_path):
        """Builds a bundle for `feature/x`, then recreates a *different*,
        diverging local `feature/x` so the real pass's non-force fetch is
        rejected — a genuine git-mechanics failure, not a simulated one."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        bundle_path = tmp_path / "bundles" / "feature_x.bundle"
        _make_feature_bundle(repo, bundle_path, "feature/x")

        # Recreate a conflicting local feature/x with unrelated history.
        _git(["checkout", "--quiet", "-b", "feature/x"], repo)
        (repo / "conflicting.txt").write_text("unrelated local history\n")
        _git(["add", "."], repo)
        _git(["commit", "--quiet", "-m", "unrelated local feature/x"], repo)
        _git(["checkout", "--quiet", "main"], repo)

        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_x.bundle").write_bytes(bundle_path.read_bytes())
        return repo

    def test_failed_import_still_leaves_tree_clean(self, tmp_path):
        repo = self._repo_with_conflicting_local_branch(tmp_path)

        rc = bundle_manager.cmd_import(_import_args(repo))

        assert rc == 1, "the non-fast-forward fetch must have been reported as a failure"
        assert _dirty_files(repo) == [], (
            "a failed real pass still calls history.save() (the failure "
            "is legitimately recorded — Section 8 forbids losing that), "
            "but W14-2B requires it to end up committed, not dangling"
        )

    def test_unrelated_bundle_is_not_blocked_by_a_prior_failure(self, tmp_path):
        repo = self._repo_with_conflicting_local_branch(tmp_path)

        rc1 = bundle_manager.cmd_import(_import_args(repo))
        assert rc1 == 1   # the conflicting bundle failed, as expected

        # A second, entirely unrelated, perfectly valid bundle arrives.
        second_bundle = tmp_path / "bundles" / "feature_w.bundle"
        _make_feature_bundle(repo, second_bundle, "feature/w")
        incoming = repo / "update" / "incoming"
        (incoming / "feature_w.bundle").write_bytes(second_bundle.read_bytes())

        rc2 = bundle_manager.cmd_import(_import_args(repo))

        assert rc2 == 0, (
            "this is the literal bug W14-2B fixes: an unrelated, valid "
            "bundle must not be refused (rc == 2, 'uncommitted changes to "
            "tracked files') just because an earlier, unrelated import "
            "attempt failed and left its own history record dirty"
        )
        assert _dirty_files(repo) == []

    def test_failed_history_record_is_not_lost(self, tmp_path):
        """Section 8: must not trade tree cleanliness for losing history —
        the failed attempt must still show up in bundle_history.json."""
        repo = self._repo_with_conflicting_local_branch(tmp_path)
        rc = bundle_manager.cmd_import(_import_args(repo))
        assert rc == 1

        history_path = repo / "bundle_history.json"
        on_disk = json.loads(history_path.read_text())
        statuses = [r["status"] for r in on_disk["records"]]
        assert "failed" in statuses


# ── Test B: preflight/preview never mutates anything, dirty or not ────────

class TestPreflightIsReadOnly:

    def test_preview_of_a_repo_with_pre_existing_unrelated_dirt_does_not_crash_or_mutate(
        self, tmp_path,
    ):
        """A file unrelated to bundle_manager is already dirty when import
        runs. The preview pass (dry-run) must still complete and report
        results — it must never itself be the thing that fails — even
        though the real pass afterward correctly refuses to proceed."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        bundle_path = tmp_path / "bundles" / "feature_x.bundle"
        _make_feature_bundle(repo, bundle_path, "feature/x")
        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_x.bundle").write_bytes(bundle_path.read_bytes())

        # Unrelated pre-existing dirt, nothing to do with bundle_manager.
        (repo / "README.md").write_text("someone's unrelated unstaged edit\n")
        dirt_before = _dirty_files(repo)
        assert dirt_before  # sanity: the fixture really is dirty

        rc = bundle_manager.cmd_import(_import_args(repo))

        assert rc == 2   # existing, unrelated dirty-tree guard correctly refuses
        # The pre-existing dirt is untouched — same file, same modification,
        # nothing added or removed by the (correctly aborted) run.
        assert _dirty_files(repo) == dirt_before


# ── Git-safety end-to-end (Section 10): observable filesystem, not mocks ──

class TestGitSafetyObservableBehavior:

    def test_full_lifecycle_before_operation_after_stays_within_expected_state(self, tmp_path):
        """before -> operation -> after, comparing real `git status` output
        rather than asserting a mock wasn't called — proves the working
        tree mutation genuinely did not happen, not just that our code
        didn't attempt it."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        before_head = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        before_dirty = _dirty_files(repo)
        assert before_dirty == []

        bundle_path = tmp_path / "bundles" / "feature_x.bundle"
        _make_feature_bundle(repo, bundle_path, "feature/x")
        incoming = repo / "update" / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)
        (incoming / "feature_x.bundle").write_bytes(bundle_path.read_bytes())

        rc = bundle_manager.cmd_import(_import_args(repo))
        assert rc == 0

        after_head = _git(["rev-parse", "HEAD"], repo).stdout.strip()
        after_dirty = _dirty_files(repo)

        assert after_dirty == []
        # HEAD legitimately moved (checkout to feature/x, plus the
        # auto-commit of bundle_history.json back on main) — that's the
        # *intended* explicit mutation, not the bug. The property under
        # test is cleanliness, not immutability of HEAD.
        assert after_head != before_head
