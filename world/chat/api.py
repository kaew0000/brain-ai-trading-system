"""world/chat/api.py — public facade (same convention as world.workspace.api).

Module-level singletons built lazily from settings so importing this
module never touches disk.
"""
from __future__ import annotations

import threading

from config.settings import settings
from utils.logger import get_logger
from world.chat import responder
from world.chat.meeting import MeetingEngine, MeetingError
from world.chat.models import (
    CHANNEL_MEETING, CHANNEL_OFFICE, DM_PREFIX, KIND_NPC, KIND_USER,
    STATUS_RUNNING, ChatMessage, Meeting,
)
from world.chat.store import ChatStore
from world.workspace import api as workspace_api
from world.workspace.models import AgentPanelState

logger = get_logger("world.chat.api")

_lock = threading.Lock()
_store: ChatStore | None = None
_engine: MeetingEngine | None = None


def _panels() -> tuple[AgentPanelState, ...]:
    return workspace_api.get_agent_panels()


def _get() -> tuple[ChatStore, MeetingEngine]:
    global _store, _engine
    with _lock:
        if _store is None or _engine is None:
            _store = ChatStore(settings.WORLD_CHAT_STORE_PATH, settings.WORLD_CHAT_MAX_MESSAGES_PER_CHANNEL)
            _engine = MeetingEngine(
                _store, lambda: _panels(),
                settings.WORLD_MEETING_MIN_TURNS, settings.WORLD_MEETING_MAX_TURNS,
            )
        return _store, _engine


def reset_for_tests() -> None:
    global _store, _engine
    with _lock:
        _store = None
        _engine = None


class ChatError(ValueError):
    """Invalid chat request."""


def get_roster() -> list[dict]:
    return [p.to_dict() for p in _panels()]


def _validate_channel(channel: str, panels: tuple[AgentPanelState, ...]) -> str | None:
    """Returns the DM target agent id for dm channels, else None."""
    if channel in (CHANNEL_OFFICE, CHANNEL_MEETING):
        return None
    if channel.startswith(DM_PREFIX):
        agent_id = channel[len(DM_PREFIX):]
        if any(p.agent_id == agent_id for p in panels):
            return agent_id
    raise ChatError(f"unknown channel: {channel!r}")


def post_message(channel: str, text: str, sender_id: str, sender_name: str) -> dict:
    store, engine = _get()
    text = text.strip()
    if not text:
        raise ChatError("text is required")
    if len(text) > settings.WORLD_CHAT_MAX_TEXT_CHARS:
        raise ChatError(f"text exceeds {settings.WORLD_CHAT_MAX_TEXT_CHARS} characters")
    panels = _panels()
    dm_target = _validate_channel(channel, panels)
    mentions = responder.extract_mentions(text, panels)
    user_msg = store.add_message(channel, sender_id, sender_name, KIND_USER, text, mentions)

    replies: list[ChatMessage] = []
    recipients = [dm_target] if dm_target else (list(mentions) if channel == CHANNEL_OFFICE else [])
    by_id = {p.agent_id: p for p in panels}
    for agent_id in recipients:
        panel = by_id[agent_id]
        replies.append(store.add_message(
            channel, agent_id, panel.panel_label, KIND_NPC, responder.reply_to(panel, text),
        ))

    # Hybrid meetings: a human interjection pauses the auto driver.
    if channel == CHANNEL_MEETING:
        m = engine.get()
        if m.hybrid and m.status == STATUS_RUNNING:
            engine.pause()
    return {"message": user_msg.to_dict(), "replies": [r.to_dict() for r in replies]}


def list_messages(channel: str, limit: int = 100, after_id: str | None = None) -> list[dict]:
    store, _ = _get()
    _validate_channel(channel, _panels())
    limit = max(1, min(limit, settings.WORLD_CHAT_MAX_MESSAGES_PER_CHANNEL))
    return [m.to_dict() for m in store.list_messages(channel, limit, after_id)]


def get_meeting() -> Meeting:
    return _get()[1].get()


def start_meeting(topic: str, participants: list[str], max_turns: int | None,
                  mode: str, hybrid: bool) -> Meeting:
    turns = settings.WORLD_MEETING_DEFAULT_TURNS if max_turns is None else max_turns
    return _get()[1].start(topic, participants, turns, mode, hybrid)


def meeting_next() -> Meeting:
    return _get()[1].next_turn()


def meeting_pause() -> Meeting:
    return _get()[1].pause()


def meeting_resume() -> Meeting:
    return _get()[1].resume()


def meeting_stop() -> Meeting:
    return _get()[1].stop()


def health() -> dict:
    store, engine = _get()
    m = engine.get()
    return {
        "enabled": settings.WORLD_CHAT_ENABLED, "engine": "rule-based",
        "channels": store.counts(), "meetingStatus": m.status,
        "npcCount": len(_panels()),
    }


__all__ = ["ChatError", "MeetingError"]
