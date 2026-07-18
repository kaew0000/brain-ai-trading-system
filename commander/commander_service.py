"""
commander/commander_service.py
=================================
Commander Interface Backend (v14 Phase 2.5)

Parses and executes the fixed command set from the spec:
  pause trader / resume trader / paper mode on / paper mode off /
  show positions / show pnl / show risk

Matching strategy
------------------
Token-based (split on whitespace, set membership), NOT raw substring
matching — avoids foot-guns like "noon" accidentally containing "on".
Each command is recognised by a required token SET being a subset of the
input's word set, so phrasing order/extra words don't matter (e.g. both
"pause trader" and "please pause the trader now" match the same command).

Read-only commands (show positions/pnl/risk) take a `context` dict built
fresh by the caller (api/app.py) from live `_state` on every call — this
keeps CommanderService fully decoupled from api.app (no circular import)
and trivially testable with a fake context.

Mutating commands (pause/resume/paper mode) act on the global
TradingControlState singleton from commander/control_state.py.

Usage
-----
from commander.commander_service import CommanderService

commander = CommanderService()
result = commander.execute("pause trader")
result = commander.execute("show positions", context={
    "paper_engine": paper_engine,        # or None
    "position_info": live_position_dict, # or None
    "journal_v2": journal,               # or None
    "risk_report": risk_engine.report(balance),  # or None
})
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional

from commander.control_state import get_control_state
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CommandResult:
    command:   str
    matched:   str    # canonical command name, "" if unrecognised
    success:   bool
    message:   str
    data:      dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class CommanderService:
    """Parses and executes natural-language trading commands."""

    def execute(self, command_text: str, context: Optional[dict] = None) -> CommandResult:
        """
        Parse command_text against the fixed command set and execute it.

        Returns a CommandResult; never raises — unrecognised commands
        return success=False with a helpful message rather than an
        exception, since this is meant to be safe to wire directly to a
        chat-style frontend.
        """
        raw = command_text or ""
        text = raw.strip().lower()
        words = set(text.replace(",", " ").replace(".", " ").split())
        context = context or {}

        try:
            if {"pause", "trader"} <= words:
                return self._cmd_pause(raw)
            if {"resume", "trader"} <= words:
                return self._cmd_resume(raw)
            if {"paper", "mode", "on"} <= words:
                return self._cmd_paper_mode(raw, True)
            if {"paper", "mode", "off"} <= words:
                return self._cmd_paper_mode(raw, False)
            if "position" in text or "positions" in words:
                return self._cmd_show_positions(raw, context)
            if "pnl" in words:
                return self._cmd_show_pnl(raw, context)
            if "risk" in words:
                return self._cmd_show_risk(raw, context)

            return CommandResult(
                command=raw, matched="", success=False,
                message=(
                    f"Unrecognized command: '{raw}'. Supported commands: "
                    "pause trader, resume trader, paper mode on, paper mode off, "
                    "show positions, show pnl, show risk."
                ),
            )
        except Exception as exc:
            logger.error(f"CommanderService error executing '{raw}': {exc}", exc_info=True)
            return CommandResult(
                command=raw, matched="", success=False,
                message=f"Command failed: {exc}",
            )

    # ── Mutating commands ────────────────────────────────────────────────────

    def _cmd_pause(self, raw: str) -> CommandResult:
        get_control_state().pause()
        return CommandResult(
            command=raw, matched="pause_trader", success=True,
            message="Trader paused. No new trades will be opened until resumed.",
            data={"paused": True},
        )

    def _cmd_resume(self, raw: str) -> CommandResult:
        get_control_state().resume()
        return CommandResult(
            command=raw, matched="resume_trader", success=True,
            message="Trader resumed. Trading will continue on the next cycle.",
            data={"paused": False},
        )

    def _cmd_paper_mode(self, raw: str, enable: bool) -> CommandResult:
        get_control_state().set_paper_mode_forced(enable)
        if enable:
            message = (
                "Paper mode safety override ENABLED — no real orders will be "
                "sent regardless of EXECUTION_MODE until disabled."
            )
        else:
            message = (
                "Paper mode safety override DISABLED — the EXECUTION_MODE "
                "setting now governs real order placement again."
            )
        return CommandResult(
            command=raw, matched="paper_mode_on" if enable else "paper_mode_off",
            success=True, message=message,
            data={"paper_mode_forced": enable},
        )

    # ── Read-only commands ────────────────────────────────────────────────────

    def _cmd_show_positions(self, raw: str, context: dict) -> CommandResult:
        paper_engine = context.get("paper_engine")
        position_info = context.get("position_info")

        if paper_engine is not None:
            positions = paper_engine.get_open_positions()
            if not positions:
                message = "No open positions (paper mode)."
            else:
                lines = [
                    f"{p.get('direction', '?')} {p.get('symbol', '')} "
                    f"qty={p.get('quantity', 0)} entry={p.get('entry_price', 0)}"
                    for p in positions
                ]
                message = "Open positions (paper): " + "; ".join(lines)
            return CommandResult(command=raw, matched="show_positions", success=True,
                                  message=message, data={"positions": positions})

        if position_info:
            message = (
                f"{position_info.get('side', '?')} qty={position_info.get('positionAmt', 0)} "
                f"entry={position_info.get('entryPrice', 0)} "
                f"uPnL={position_info.get('unrealizedProfit', 0)}"
            )
            return CommandResult(command=raw, matched="show_positions", success=True,
                                  message=message, data={"positions": [position_info]})

        return CommandResult(command=raw, matched="show_positions", success=True,
                              message="No open positions.", data={"positions": []})

    def _cmd_show_pnl(self, raw: str, context: dict) -> CommandResult:
        paper_engine = context.get("paper_engine")
        if paper_engine is not None:
            metrics = paper_engine.get_metrics()
            message = (
                f"Total PnL: {metrics.get('total_pnl', 0):.2f} | "
                f"Win rate: {metrics.get('win_rate', 0) * 100:.1f}% | "
                f"Trades: {metrics.get('total_trades', 0)}"
            )
            return CommandResult(command=raw, matched="show_pnl", success=True,
                                  message=message, data=metrics)

        journal = context.get("journal_v2")
        if journal is not None:
            try:
                summary = journal.get_performance_summary(limit=200)
            except Exception:
                summary = {}
            message = f"Performance summary: {summary}" if summary else "No trade history yet."
            return CommandResult(command=raw, matched="show_pnl", success=True,
                                  message=message, data=summary or {})

        return CommandResult(command=raw, matched="show_pnl", success=True,
                              message="No PnL data available yet.", data={})

    def _cmd_show_risk(self, raw: str, context: dict) -> CommandResult:
        risk_report = context.get("risk_report")
        if risk_report:
            status = "ALLOWED" if risk_report.get("can_trade") else "BLOCKED"
            message = (
                f"Risk status: {status} | "
                f"Today PnL: {risk_report.get('today_pnl', 0):.2f} | "
                f"Consecutive losses: {risk_report.get('consecutive_losses', 0)} | "
                f"Dynamic risk: {risk_report.get('dynamic_risk_pct', 0) * 100:.2f}%"
            )
            if risk_report.get("block_reason"):
                message += f" | Block reason: {risk_report['block_reason']}"
            return CommandResult(command=raw, matched="show_risk", success=True,
                                  message=message, data=risk_report)

        return CommandResult(command=raw, matched="show_risk", success=True,
                              message="No risk report available yet.", data={})
