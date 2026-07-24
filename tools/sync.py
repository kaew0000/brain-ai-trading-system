"""
tools/sync.py — Bundle Manager: sync command

"Updates main after merge" — run this after a feature branch imported by
import_bundle() has actually been merged into main on GitHub (via PR or
otherwise). This tool never merges anything itself (see the module
docstring's reasoning below); sync's job is entirely about catching the
local clone up afterward and closing the loop in bundle_history.json.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from tools import git_utils
from tools.history import BundleHistory
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SyncResult:
    base_branch:        str
    before_sha:         str
    after_sha:           str
    fast_forwarded:      bool
    newly_merged_shas:   list[str] = field(default_factory=list)
    pruned:              bool = False


def sync_main(
    repo_dir: Path,
    history: BundleHistory,
    base_branch: str = "main",
    remote: str = "origin",
    prune: bool = True,
    git_timeout: int = 120,
) -> SyncResult:
    """
    1. Checkout base_branch (fails loudly if it doesn't exist locally —
       this tool never creates it from scratch).
    2. git fetch <remote> [--prune]
    3. git pull --ff-only <remote> <base_branch> — deliberately
       fast-forward-only. If the local base branch has diverged (local
       commits the remote doesn't have), this raises rather than
       creating a merge commit or silently rewriting history; that
       divergence needs a human decision, not an automated one.
    4. Cross-reference bundle_history.json: any "applied" record whose
       SHA is now an ancestor of base_branch is genuinely merged, not
       just pushed — logged, so it's visible which imported branches
       have actually landed vs. are still sitting in an open PR.

    This tool intentionally never performs the merge itself (no `git
    merge`, no GitHub PR API call) — merging is a decision (code review,
    CI status, approval) this tool has no visibility into. sync only
    ever fast-forwards onto what a human/CI already decided.
    """
    if not git_utils.branch_exists(base_branch, repo_dir):
        raise git_utils.GitCommandError(
            ["checkout", base_branch], 1, "",
            f"base branch '{base_branch}' does not exist locally — "
            f"sync does not create it.",
        )

    before_sha = git_utils.rev_parse(base_branch, repo_dir)

    current = git_utils.get_current_branch(repo_dir)
    if current != base_branch:
        git_utils.checkout_branch(base_branch, repo_dir, timeout=git_timeout)

    if prune:
        git_utils.fetch_prune(repo_dir, remote=remote, timeout=git_timeout)
        pruned = True
    else:
        git_utils.run_git(["fetch", remote], cwd=repo_dir, timeout=git_timeout)
        pruned = False

    git_utils.pull_fast_forward(base_branch, repo_dir, remote=remote, timeout=git_timeout)
    after_sha = git_utils.rev_parse(base_branch, repo_dir)
    fast_forwarded = before_sha != after_sha

    newly_merged: list[str] = []
    for record in history.all_records():
        if record.status != "applied":
            continue
        if git_utils.is_ancestor(record.sha, base_branch, repo_dir):
            newly_merged.append(record.sha)

    if fast_forwarded:
        logger.info(
            "sync: %s fast-forwarded %s -> %s", base_branch, before_sha[:12], after_sha[:12],
        )
    else:
        logger.info("sync: %s already up to date at %s", base_branch, after_sha[:12])

    if newly_merged:
        logger.info(
            "sync: %d previously-imported branch(es) confirmed merged into %s: %s",
            len(newly_merged), base_branch, ", ".join(s[:12] for s in newly_merged),
        )

    return SyncResult(
        base_branch=base_branch, before_sha=before_sha, after_sha=after_sha,
        fast_forwarded=fast_forwarded, newly_merged_shas=newly_merged, pruned=pruned,
    )
