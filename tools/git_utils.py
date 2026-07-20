"""
tools/git_utils.py — Bundle Manager: git subprocess plumbing

The ONLY module in tools/ that invokes `git` directly. Every other module
in this package (bundle_utils.py, github_actions.py, sync.py) calls
through here rather than shelling out itself — one place to get
cross-platform subprocess handling right (Windows/Linux/Termux), one
place to fix if git's CLI output format ever changes.

Cross-platform notes
---------------------
- Every call uses list-form subprocess args (never shell=True) — avoids
  Windows-vs-POSIX shell-quoting differences entirely, and is the safer
  default regardless (no shell injection surface from a branch/file name).
- The git executable is resolved once via shutil.which("git") rather than
  assumed to be at a fixed path — works whether git is a Windows .exe, a
  Linux binary, or Termux's own git package.
- All paths passed to git are absolute POSIX-style strings
  (Path.as_posix()) — git itself accepts forward slashes on Windows too,
  so this avoids ever needing OS-conditional path logic.
- subprocess.run(..., text=True) uses the platform default encoding;
  explicitly set to UTF-8 (encoding="utf-8", errors="replace") since
  Windows' default (cp1252/mbcs) can otherwise mangle non-ASCII commit
  messages/branch names, and Termux's default is already UTF-8 (no-op
  there, harmless).

Why retries live here, not in utils/retry.py
----------------------------------------------
utils/retry.py's @retry_api_call decorator catches
requests.exceptions.ConnectionError/Timeout and binance.error.ClientError
specifically — it's built for the Binance HTTP client, not subprocess
calls. Reusing it here would silently catch nothing (git failures raise
subprocess.CalledProcessError, not those types) — worse than not using
it. push() below has its own small, explicitly-scoped retry loop instead.
"""
from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from utils.logger import get_logger

logger = get_logger(__name__)


class GitCommandError(RuntimeError):
    """Raised for any non-zero-exit git invocation. Always carries the
    full command, return code, and captured stdout/stderr — "always
    provide context" per the coding standard's error-handling rule."""

    def __init__(self, cmd: Sequence[str], returncode: int, stdout: str, stderr: str):
        self.cmd = list(cmd)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"git command failed ({returncode}): {' '.join(self.cmd)}\n"
            f"--- stdout ---\n{stdout.strip()}\n"
            f"--- stderr ---\n{stderr.strip()}"
        )


class GitNotFoundError(RuntimeError):
    """Raised once, at first use, if no `git` executable is on PATH."""


_GIT_EXE: Optional[str] = None


def _resolve_git() -> str:
    global _GIT_EXE
    if _GIT_EXE is None:
        found = shutil.which("git")
        if not found:
            raise GitNotFoundError(
                "No `git` executable found on PATH. Install Git for "
                "Windows / your Linux package manager's git / Termux's "
                "`pkg install git`, then retry."
            )
        _GIT_EXE = found
    return _GIT_EXE


@dataclass(frozen=True)
class GitResult:
    cmd: List[str]
    returncode: int
    stdout: str
    stderr: str


def run_git(
    args: Sequence[str],
    cwd: Path,
    timeout: int = 120,
    check: bool = True,
) -> GitResult:
    """
    Run `git <args>` in `cwd`. Raises GitCommandError if check=True and
    the process exits non-zero; otherwise returns the result regardless
    of exit code (caller inspects .returncode) — used by callers that
    treat a particular non-zero exit as a meaningful, expected outcome
    rather than a failure (e.g. `git bundle verify` on a bad bundle).
    """
    exe = _resolve_git()
    cmd = [exe, *args]
    logger.debug("git_utils: running %s (cwd=%s)", " ".join(args), cwd)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        logger.error("git_utils: command timed out after %ss: %s", timeout, " ".join(args))
        raise GitCommandError(cmd, -1, exc.stdout or "", f"TIMEOUT after {timeout}s") from exc

    result = GitResult(cmd=cmd, returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    if check and proc.returncode != 0:
        raise GitCommandError(cmd, proc.returncode, proc.stdout, proc.stderr)
    return result


# ── Bundle-specific plumbing ─────────────────────────────────────────────

def verify_bundle(bundle_path: Path, cwd: Path, timeout: int = 120) -> Tuple[bool, str]:
    """`git bundle verify` — checks the bundle is well-formed AND that
    this repo already has every prerequisite commit it needs (a bundle
    can be a valid file but still unusable here if it was built as an
    incremental update against history we don't have). Returns
    (ok, message) rather than raising — an invalid bundle is an expected,
    routine outcome (routes to update/failed), not an exceptional one."""
    result = run_git(
        ["bundle", "verify", str(bundle_path.resolve())], cwd=cwd, timeout=timeout, check=False,
    )
    ok = result.returncode == 0
    message = (result.stdout + result.stderr).strip()
    return ok, message


def list_bundle_heads(bundle_path: Path, cwd: Path, timeout: int = 60) -> List[Tuple[str, str]]:
    """`git bundle list-heads` — returns [(sha, full_ref_name), ...].
    Structured plumbing output (stable across git versions), deliberately
    used instead of parsing `git bundle verify`'s prose summary."""
    result = run_git(
        ["bundle", "list-heads", str(bundle_path.resolve())], cwd=cwd, timeout=timeout,
    )
    heads: List[Tuple[str, str]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        sha, _, ref = line.partition(" ")
        if sha and ref:
            heads.append((sha, ref))
    return heads


def fetch_branch_from_bundle(
    bundle_path: Path, branch: str, cwd: Path, force: bool = False, timeout: int = 300,
) -> GitResult:
    """
    Fetches `refs/heads/<branch>` out of the bundle file directly into
    the local branch of the same name — git treats a bundle path exactly
    like a remote URL for this purpose, no temporary remote needed.

    force=False (default) refuses to move an existing local branch
    unless the fetch is a fast-forward — a naming collision with
    unrelated local history fails loudly here rather than silently
    overwriting it. Callers wanting to force an update must opt in
    explicitly.
    """
    refspec = f"refs/heads/{branch}:refs/heads/{branch}"
    if force:
        refspec = "+" + refspec
    return run_git(["fetch", str(bundle_path.resolve()), refspec], cwd=cwd, timeout=timeout)


def checkout_branch(branch: str, cwd: Path, timeout: int = 60) -> GitResult:
    return run_git(["checkout", branch], cwd=cwd, timeout=timeout)


def branch_exists(branch: str, cwd: Path) -> bool:
    result = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=cwd, check=False,
    )
    return result.returncode == 0


def get_current_branch(cwd: Path) -> str:
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)
    return result.stdout.strip()


def rev_parse(ref: str, cwd: Path) -> str:
    result = run_git(["rev-parse", ref], cwd=cwd)
    return result.stdout.strip()


def is_ancestor(ancestor_ref: str, descendant_ref: str, cwd: Path) -> bool:
    """True if `ancestor_ref` is an ancestor of (already merged into)
    `descendant_ref` — used by sync.py to tell whether a bundle's commit
    has actually landed on the base branch yet, not just been pushed."""
    result = run_git(
        ["merge-base", "--is-ancestor", ancestor_ref, descendant_ref], cwd=cwd, check=False,
    )
    return result.returncode == 0


def push_branch(
    branch: str,
    cwd: Path,
    remote: str = "origin",
    force: bool = False,
    retries: int = 3,
    timeout: int = 300,
) -> GitResult:
    """Push with a small, explicitly-scoped retry loop for transient
    network failures (this is the one step in the whole workflow that
    leaves the local sandbox). force=False by default — never
    force-pushes unless a caller explicitly opts in."""
    args = ["push", remote, branch]
    if force:
        args.insert(1, "--force-with-lease")

    last_error: Optional[GitCommandError] = None
    for attempt in range(1, max(1, retries) + 1):
        try:
            return run_git(args, cwd=cwd, timeout=timeout)
        except GitCommandError as exc:
            last_error = exc
            if attempt < retries:
                delay = min(30, 2 ** attempt)
                logger.warning(
                    "git_utils: push attempt %d/%d failed, retrying in %ss: %s",
                    attempt, retries, delay, exc.stderr.strip()[:200],
                )
                time.sleep(delay)
    assert last_error is not None
    raise last_error


def fetch_prune(cwd: Path, remote: str = "origin", timeout: int = 120) -> GitResult:
    """`git fetch <remote> --prune` — used by sync.py to drop stale
    remote-tracking refs for branches deleted on GitHub after merge."""
    return run_git(["fetch", remote, "--prune"], cwd=cwd, timeout=timeout)


def pull_fast_forward(branch: str, cwd: Path, remote: str = "origin", timeout: int = 120) -> GitResult:
    """Fast-forward-only pull — refuses (raises) rather than creating a
    merge commit or silently diverging if the local branch has commits
    the remote doesn't. sync.py's job is to catch main up to origin/main,
    never to rewrite it."""
    return run_git(["pull", "--ff-only", remote, branch], cwd=cwd, timeout=timeout)
