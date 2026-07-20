"""
tools/bundle_utils.py — Bundle Manager: bundle discovery and metadata

Handles everything about a bundle *file* that isn't a raw git subprocess
call: finding candidate files in update/incoming, and extracting exactly
one feature branch + head SHA from a verified bundle.

Why .bundle and .bundle.txt are treated identically
------------------------------------------------------
Both are git's ordinary bundle format (an ASCII header followed by a
git pack). `.bundle.txt` exists purely for transport paths that block or
mangle `.bundle` attachments (some email/chat filters) — same bytes,
different extension. No special decoding is applied to either; if a
`.bundle.txt` file *was* corrupted in transit (e.g. by a lossy
text-mode transfer), git_utils.verify_bundle() will simply reject it
like any other malformed bundle, which is the correct, safe outcome —
no special-casing needed here.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List

from tools import git_utils
from utils.logger import get_logger

logger = get_logger(__name__)

BUNDLE_EXTENSIONS: tuple = (".bundle", ".bundle.txt")


class BundleFormatError(ValueError):
    """Raised when a bundle is structurally valid to git but doesn't
    match this tool's "exactly one feature branch" contract — e.g. zero
    or multiple refs/heads/* refs. Never guessed past; the bundle is
    routed to update/failed with this as the reason."""


@dataclass(frozen=True)
class BundleInfo:
    path: Path
    branch: str
    sha: str


def find_incoming_bundles(incoming_dir: Path) -> List[Path]:
    """Every *.bundle / *.bundle.txt file directly in incoming_dir,
    oldest-modified first (processed in arrival order). Does not
    recurse — subdirectories under update/incoming/ are not scanned, so
    a partially-written or intentionally-parked file can be kept in a
    subfolder without being picked up."""
    if not incoming_dir.exists():
        return []
    candidates = [
        p for p in incoming_dir.iterdir()
        if p.is_file() and p.name.lower().endswith(BUNDLE_EXTENSIONS)
    ]
    return sorted(candidates, key=lambda p: p.stat().st_mtime)


def extract_branch_and_sha(bundle_path: Path, cwd: Path) -> BundleInfo:
    """
    Runs `git bundle list-heads` and requires EXACTLY one refs/heads/*
    entry — the "automatically extract the feature branch" feature, with
    a fail-closed contract: a bundle built with multiple branches, only
    tags, or nothing at all raises BundleFormatError rather than
    guessing which ref is "the" feature branch. Caller routes that to
    update/failed for a human to look at.
    """
    heads = git_utils.list_bundle_heads(bundle_path, cwd)
    branch_heads = [(sha, ref) for sha, ref in heads if ref.startswith("refs/heads/")]

    if not branch_heads:
        raise BundleFormatError(
            f"{bundle_path.name}: bundle contains no refs/heads/* ref "
            f"(found: {[ref for _, ref in heads] or 'nothing'}) — nothing to import."
        )
    if len(branch_heads) > 1:
        names = [ref.removeprefix("refs/heads/") for _, ref in branch_heads]
        raise BundleFormatError(
            f"{bundle_path.name}: bundle contains {len(branch_heads)} branches "
            f"({', '.join(names)}) — this tool imports exactly one feature "
            f"branch per bundle. Re-create the bundle with a single branch range."
        )

    sha, ref = branch_heads[0]
    branch = ref.removeprefix("refs/heads/")
    return BundleInfo(path=bundle_path, branch=branch, sha=sha)


def ensure_bundle_dirs(incoming: Path, applied: Path, failed: Path) -> None:
    """Creates update/incoming, update/applied, update/failed if missing.
    Idempotent — safe to call on every run."""
    for d in (incoming, applied, failed):
        d.mkdir(parents=True, exist_ok=True)


def move_bundle(bundle_path: Path, destination_dir: Path) -> Path:
    """Moves a processed bundle out of update/incoming/. If a file with
    the same name already exists at the destination (a bundle re-dropped
    with an identical filename after a previous run), the moved file
    gets a numeric suffix rather than silently overwriting history of a
    prior attempt."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / bundle_path.name
    if target.exists():
        name_lower = bundle_path.name.lower()
        matched_ext = next((ext for ext in BUNDLE_EXTENSIONS if name_lower.endswith(ext)), "")
        stem = bundle_path.name[: len(bundle_path.name) - len(matched_ext)] if matched_ext else bundle_path.stem
        n = 1
        while target.exists():
            target = destination_dir / f"{stem}.{n}{matched_ext}"
            n += 1
        logger.warning(
            "bundle_utils: %s already exists in %s, moving as %s instead",
            bundle_path.name, destination_dir, target.name,
        )
    shutil.move(str(bundle_path), str(target))
    return target
