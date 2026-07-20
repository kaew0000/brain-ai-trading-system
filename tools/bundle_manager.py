#!/usr/bin/env python3
"""
tools/bundle_manager.py — Bundle Manager CLI

    python -m tools.bundle_manager import  [options]
    python -m tools.bundle_manager sync    [options]
    python -m tools.bundle_manager history [options]

Workflow implemented by `import`:
  1. Scan update/incoming/ for *.bundle / *.bundle.txt files.
  2. For each: verify -> extract branch+SHA -> skip if already imported
     (bundle_history.json) -> fetch -> checkout -> push -> move to
     update/applied/ (or update/failed/ on any failure at any step).
  3. Print a results table; persist bundle_history.json once at the end.

`sync` fast-forwards the local base branch (default: main) onto origin
after a feature branch has actually been merged there — see
tools/sync.py's docstring for exactly what it does and does not do
(never merges anything itself).

Safety defaults
-----------------
- Runs a dry-run preview (verify + extract + duplicate-check only, no
  fetch/checkout/push) before ever touching the repository, and asks for
  confirmation before proceeding — unless --yes is passed (for CI/
  non-interactive use).
- Never force-pushes or force-fetches unless --force is passed explicitly.
- --no-push does everything except the final `git push`, useful for
  testing the import flow against a repo with no configured remote.

Cross-platform: pure stdlib argparse + pathlib; no shell=True anywhere
in this package (see tools/git_utils.py). Works identically invoked as
`python -m tools.bundle_manager ...` on Windows, Linux, or Termux.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from config.settings import settings
from tools import bundle_utils, github_actions, sync as sync_module, ui
from tools.history import BundleHistory
from utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_dirs(repo_dir: Path, args: argparse.Namespace) -> dict:
    def _p(cli_value: Optional[str], setting_value: str) -> Path:
        raw = cli_value if cli_value is not None else setting_value
        p = Path(raw)
        return p if p.is_absolute() else (repo_dir / p)

    return {
        "incoming": _p(args.incoming, settings.BUNDLE_INCOMING_DIR),
        "applied":  _p(args.applied,  settings.BUNDLE_APPLIED_DIR),
        "failed":   _p(args.failed,   settings.BUNDLE_FAILED_DIR),
        "history":  _p(args.history_file, settings.BUNDLE_HISTORY_FILE),
    }


def cmd_import(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo).resolve()
    dirs = _resolve_dirs(repo_dir, args)
    bundle_utils.ensure_bundle_dirs(dirs["incoming"], dirs["applied"], dirs["failed"])

    base_branch = args.base_branch or settings.BUNDLE_BASE_BRANCH
    remote = args.remote or settings.BUNDLE_REMOTE
    push = not args.no_push
    push_retries = args.push_retries if args.push_retries is not None else settings.BUNDLE_PUSH_RETRIES
    git_timeout = args.git_timeout if args.git_timeout is not None else settings.BUNDLE_GIT_TIMEOUT_SECONDS

    ui.banner("Bundle Manager — import")

    try:
        history = BundleHistory(dirs["history"])
    except RuntimeError as exc:
        ui.error(str(exc))
        return 2

    bundles = bundle_utils.find_incoming_bundles(dirs["incoming"])
    if not bundles:
        ui.info(f"No bundle files found in {dirs['incoming']}")
        return 0
    ui.info(f"Found {len(bundles)} bundle file(s) in {dirs['incoming']}")

    # ── Preview pass (always dry-run first, never touches the repo) ────────
    preview: List = []
    for b in bundles:
        preview.append(
            github_actions.import_bundle(
                b, repo_dir, history, dirs["applied"], dirs["failed"],
                base_branch=base_branch, remote=remote, push=push, dry_run=True,
                force=args.force, push_retries=push_retries, git_timeout=git_timeout,
            )
        )
    ui.results_table(preview)

    actionable = [r for r in preview if r.status == "dry_run" and r.reason is None]
    if not actionable:
        ui.warn("Nothing to import (all bundles invalid, duplicate, or already handled).")
        return 0

    if not args.yes:
        proceed = ui.confirm(
            f"Proceed with importing {len(actionable)} bundle(s) "
            f"onto '{base_branch}'{' and pushing to ' + remote if push else ' (no push)'}?",
            default=False,
        )
        if not proceed:
            ui.warn("Aborted by user — no changes made.")
            return 1

    # ── Real pass ────────────────────────────────────────────────────────
    results: List = []
    for b in bundles:
        result = github_actions.import_bundle(
            b, repo_dir, history, dirs["applied"], dirs["failed"],
            base_branch=base_branch, remote=remote, push=push, dry_run=False,
            force=args.force, push_retries=push_retries, git_timeout=git_timeout,
        )
        results.append(result)

    history.save()
    ui.results_table(results)

    failed_count = sum(1 for r in results if r.status == "failed")
    applied_count = sum(1 for r in results if r.status == "applied")
    ui.success(f"{applied_count} imported, {failed_count} failed.") if failed_count == 0 \
        else ui.warn(f"{applied_count} imported, {failed_count} failed — see update/failed/.")
    return 1 if failed_count else 0


def cmd_sync(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo).resolve()
    dirs = _resolve_dirs(repo_dir, args)
    base_branch = args.base_branch or settings.BUNDLE_BASE_BRANCH
    remote = args.remote or settings.BUNDLE_REMOTE

    ui.banner("Bundle Manager — sync")
    try:
        history = BundleHistory(dirs["history"])
        result = sync_module.sync_main(
            repo_dir, history, base_branch=base_branch, remote=remote, prune=not args.no_prune,
        )
    except Exception as exc:  # noqa: BLE001 — CLI boundary: report, don't crash with a traceback
        ui.error(f"sync failed: {exc}")
        return 2

    if result.fast_forwarded:
        ui.success(f"{base_branch}: {result.before_sha[:12]} -> {result.after_sha[:12]}")
    else:
        ui.info(f"{base_branch} already up to date at {result.after_sha[:12]}")
    if result.newly_merged_shas:
        ui.info(f"{len(result.newly_merged_shas)} previously-imported branch(es) now confirmed merged.")
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    repo_dir = Path(args.repo).resolve()
    dirs = _resolve_dirs(repo_dir, args)
    ui.banner("Bundle Manager — history")
    try:
        history = BundleHistory(dirs["history"])
    except RuntimeError as exc:
        ui.error(str(exc))
        return 2
    records = history.all_records()
    if not records:
        ui.info("No bundle history yet.")
        return 0
    ui.history_table(records, limit=args.limit)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bundle_manager", description="Brain Bot V16 — Git Bundle Manager",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="Path to the git repository (default: cwd)")
    common.add_argument("--incoming", default=None, help="Override BUNDLE_INCOMING_DIR")
    common.add_argument("--applied", default=None, help="Override BUNDLE_APPLIED_DIR")
    common.add_argument("--failed", default=None, help="Override BUNDLE_FAILED_DIR")
    common.add_argument("--history-file", default=None, help="Override BUNDLE_HISTORY_FILE")
    common.add_argument("--base-branch", default=None, help="Override BUNDLE_BASE_BRANCH")
    common.add_argument("--remote", default=None, help="Override BUNDLE_REMOTE")

    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import", parents=[common], help="Import bundles from update/incoming/")
    p_import.add_argument("--yes", action="store_true", help="Skip the confirmation prompt (for CI)")
    p_import.add_argument("--no-push", action="store_true", help="Fetch/checkout only, skip git push")
    p_import.add_argument("--force", action="store_true",
                           help="Allow non-fast-forward fetch/push (default: refuse)")
    p_import.add_argument("--push-retries", type=int, default=None)
    p_import.add_argument("--git-timeout", type=int, default=None)
    p_import.set_defaults(func=cmd_import)

    p_sync = sub.add_parser("sync", parents=[common], help="Fast-forward base branch after a merge")
    p_sync.add_argument("--no-prune", action="store_true", help="Skip pruning stale remote-tracking refs")
    p_sync.set_defaults(func=cmd_sync)

    p_history = sub.add_parser("history", parents=[common], help="Show bundle_history.json")
    p_history.add_argument("--limit", type=int, default=20)
    p_history.set_defaults(func=cmd_history)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        ui.warn("Interrupted.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
