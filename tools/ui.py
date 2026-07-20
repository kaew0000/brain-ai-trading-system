"""
tools/ui.py — Bundle Manager: CLI presentation

Uses `rich` (already a project dependency — requirements.txt) for
readable console output: tables, colored status, a confirmation prompt
before push. This is presentation only, not application logging — every
function here that reports an outcome also writes through
utils.logger.get_logger(), so "never use print(), always use logger"
(docs/CODING_STANDARD.md) still holds for the actual audit trail (the
rotating file handler utils/logger.py sets up) regardless of how it's
displayed on screen. rich.console.Console().print() is used deliberately
instead of the builtin print() for the same reason %-style logger calls
aren't used for tabular display — it's a distinct concern (interactive
formatting) from structured logging, not a bypass of it.
"""
from __future__ import annotations

from typing import List, Optional

from rich.console import Console
from rich.table import Table

from utils.logger import get_logger

logger = get_logger(__name__)
console = Console()


def banner(title: str) -> None:
    console.rule(f"[bold cyan]{title}[/bold cyan]")
    logger.info("ui: === %s ===", title)


def info(message: str) -> None:
    console.print(f"[cyan]•[/cyan] {message}")
    logger.info("ui: %s", message)


def success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")
    logger.info("ui: %s", message)


def warn(message: str) -> None:
    console.print(f"[bold yellow]![/bold yellow] {message}")
    logger.warning("ui: %s", message)


def error(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}")
    logger.error("ui: %s", message)


def confirm(prompt: str, default: bool = False) -> bool:
    """Interactive yes/no. Callers running non-interactively (CI, the
    --yes CLI flag) should skip calling this entirely rather than rely
    on a default — see bundle_manager.py's --yes handling."""
    from rich.prompt import Confirm
    answer = Confirm.ask(prompt, default=default, console=console)
    logger.info("ui: confirm(%r) -> %s", prompt, answer)
    return answer


_STATUS_STYLE = {
    "applied":           "bold green",
    "failed":             "bold red",
    "skipped_duplicate":  "yellow",
    "dry_run":            "cyan",
}


def results_table(results: List) -> None:
    """Renders a list of tools.github_actions.ImportResult as a table.
    Accepts any object with .bundle_path/.branch/.sha/.status/.reason
    attributes (duck-typed rather than importing ImportResult directly,
    to avoid a ui.py -> github_actions.py import for what's purely a
    display concern)."""
    table = Table(title="Bundle Import Results", show_lines=False)
    table.add_column("Bundle", overflow="fold")
    table.add_column("Branch", overflow="fold")
    table.add_column("SHA")
    table.add_column("Status")
    table.add_column("Reason", overflow="fold")

    for r in results:
        style = _STATUS_STYLE.get(r.status, "")
        sha_short = (r.sha or "")[:12]
        table.add_row(
            r.bundle_path.name,
            r.branch or "-",
            sha_short or "-",
            f"[{style}]{r.status}[/{style}]" if style else r.status,
            (r.reason or "")[:80],
        )
    console.print(table)

    counts: dict = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    summary = ", ".join(f"{v} {k}" for k, v in counts.items())
    logger.info("ui: import summary — %s", summary or "no bundles processed")


def history_table(records: List, limit: Optional[int] = 20) -> None:
    """Renders tools.history.BundleRecord entries, most recent first."""
    table = Table(title="Bundle History", show_lines=False)
    table.add_column("Imported At")
    table.add_column("Branch", overflow="fold")
    table.add_column("SHA")
    table.add_column("Status")
    table.add_column("Bundle File", overflow="fold")

    shown = sorted(records, key=lambda r: r.imported_at, reverse=True)
    if limit is not None:
        shown = shown[:limit]

    for r in shown:
        style = _STATUS_STYLE.get(r.status, "")
        table.add_row(
            r.imported_at,
            r.branch,
            r.sha[:12],
            f"[{style}]{r.status}[/{style}]" if style else r.status,
            r.bundle_filename,
        )
    console.print(table)
