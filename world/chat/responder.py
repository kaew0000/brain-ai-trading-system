"""world/chat/responder.py — deterministic, rule-based NPC replies.

Every sentence is composed from real AgentPanelState fields; a missing
field (None) is stated as unavailable, never invented. No LLM, no I/O.
"""
from __future__ import annotations

import re

from world.workspace.models import AgentPanelState

_MENTION_RE = re.compile(r"@\[([^\]\n]{1,64})\]|@([A-Za-z0-9_\-]{1,64})")

_STATUS_WORDS = ("status", "state", "สถานะ", "เป็นไง", "ทำอะไร", "doing")
_DECISION_WORDS = ("decision", "ตัดสินใจ", "decide", "last")
_TASK_WORDS = ("task", "mission", "งาน", "ภารกิจ")
_HEALTH_WORDS = ("heartbeat", "latency", "health", "ช้า", "หน่วง")
_GREETING_WORDS = ("hello", "hi", "hey", "สวัสดี", "หวัดดี")


def extract_mentions(text: str, panels: tuple[AgentPanelState, ...]) -> tuple[str, ...]:
    """Agent ids mentioned via @[Label] or @label/@agent_id (case-insensitive)."""
    index: dict[str, str] = {}
    for p in panels:
        index[p.panel_label.lower()] = p.agent_id
        index[p.agent_id.lower()] = p.agent_id
    found: list[str] = []
    for m in _MENTION_RE.finditer(text):
        key = (m.group(1) or m.group(2) or "").strip().lower()
        agent_id = index.get(key)
        if agent_id and agent_id not in found:
            found.append(agent_id)
    return tuple(found)


def _fmt(value: object, unit: str = "") -> str:
    return "unavailable" if value is None else f"{value}{unit}"


def describe(p: AgentPanelState) -> str:
    return (
        f"status {p.status}; last decision: {_fmt(p.last_decision)}; "
        f"current task: {_fmt(p.current_task)}; heartbeat {_fmt(p.heartbeat_age_s, 's')}; "
        f"latency {_fmt(p.latency_ms, 'ms')}"
    )


def reply_to(p: AgentPanelState, text: str) -> str:
    low = text.lower()
    parts: list[str] = []
    if any(w in low for w in _GREETING_WORDS):
        parts.append(f"Hello, {p.panel_label} here.")
    if any(w in low for w in _STATUS_WORDS):
        parts.append(f"My status is {p.status}.")
    if any(w in low for w in _DECISION_WORDS):
        parts.append(f"Last decision: {_fmt(p.last_decision)}.")
    if any(w in low for w in _TASK_WORDS):
        parts.append(f"Current task: {_fmt(p.current_task)}.")
    if any(w in low for w in _HEALTH_WORDS):
        parts.append(f"Heartbeat {_fmt(p.heartbeat_age_s, 's')}, latency {_fmt(p.latency_ms, 'ms')}.")
    if not parts:
        parts.append(f"{p.panel_label} here — {describe(p)}.")
    return " ".join(parts)


def meeting_line(p: AgentPanelState, topic: str, turn: int) -> str:
    """One meeting contribution. Rotates the angle by turn so repeated
    rounds do not repeat the same sentence."""
    angle = turn % 3
    if angle == 0:
        body = f"Status {p.status}; current task: {_fmt(p.current_task)}."
    elif angle == 1:
        body = f"Last decision: {_fmt(p.last_decision)}."
    else:
        body = f"Heartbeat {_fmt(p.heartbeat_age_s, 's')}, latency {_fmt(p.latency_ms, 'ms')}."
    return f"On \"{topic}\" — {body}"
