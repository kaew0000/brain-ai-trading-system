"""world/chat/meeting.py — turn-based meeting engine (rule-based).

Pure state machine over ChatStore: idle -> running <-> paused ->
finished | stopped. It never sleeps or spawns tasks; pacing (auto mode)
is the caller's job (api/world_chat_api.py), so this stays trivially
testable and cannot leak background work.
"""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from utils.logger import get_logger
from world.chat import responder
from world.chat.models import (
    CHANNEL_MEETING, KIND_NPC, KIND_SYSTEM, MODE_AUTO, MODE_MANUAL,
    STATUS_FINISHED, STATUS_IDLE, STATUS_PAUSED, STATUS_RUNNING, STATUS_STOPPED,
    Meeting,
)
from world.chat.store import ChatStore
from world.workspace.models import AgentPanelState

logger = get_logger("world.chat.meeting")

SYSTEM_ID = "system"
SYSTEM_NAME = "System"


class MeetingError(ValueError):
    """Invalid meeting request (maps to HTTP 400/409 in the router)."""


class MeetingEngine:
    def __init__(
        self,
        store: ChatStore,
        panels: Callable[[], tuple[AgentPanelState, ...]],
        min_turns: int,
        max_turns: int,
    ) -> None:
        self._store = store
        self._panels = panels
        self._min = min_turns
        self._max = max_turns
        self._lock = threading.Lock()

    def _sys(self, text: str) -> None:
        self._store.add_message(CHANNEL_MEETING, SYSTEM_ID, SYSTEM_NAME, KIND_SYSTEM, text)

    def get(self) -> Meeting:
        return self._store.get_meeting()

    def start(self, topic: str, participants: list[str], max_turns: int,
              mode: str, hybrid: bool) -> Meeting:
        topic = topic.strip()
        if not topic:
            raise MeetingError("topic is required")
        if mode not in (MODE_AUTO, MODE_MANUAL):
            raise MeetingError(f"mode must be '{MODE_AUTO}' or '{MODE_MANUAL}'")
        if not self._min <= max_turns <= self._max:
            raise MeetingError(f"maxTurns must be between {self._min} and {self._max}")
        known = {p.agent_id for p in self._panels()}
        clean = [a for a in dict.fromkeys(participants) if a in known]
        if not clean or len(clean) != len(set(participants)):
            raise MeetingError("participants must be a non-empty list of known agent ids")
        with self._lock:
            if self._store.get_meeting().status in (STATUS_RUNNING, STATUS_PAUSED):
                raise MeetingError("a meeting is already active")
            self._store.clear_channel(CHANNEL_MEETING)
            meeting = Meeting(
                meeting_id=uuid.uuid4().hex[:12], topic=topic, participants=clean,
                max_turns=max_turns, mode=mode, hybrid=hybrid, status=STATUS_RUNNING,
                turn=0, started_at=datetime.now(timezone.utc).isoformat(),
            )
            self._store.set_meeting(meeting)
            self._sys(f"Meeting started: {topic}")
            logger.info("world.chat: meeting %s started (%d participants, %d turns, %s)",
                        meeting.meeting_id, len(clean), max_turns, mode)
            return meeting

    def next_turn(self) -> Meeting:
        with self._lock:
            m = self._store.get_meeting()
            if m.status != STATUS_RUNNING:
                raise MeetingError(f"meeting is {m.status}, not running")
            panels = {p.agent_id: p for p in self._panels()}
            agent_id = m.participants[m.turn % len(m.participants)]
            panel = panels.get(agent_id)
            if panel is None:
                self._sys(f"{agent_id} is not available this turn.")
            else:
                self._store.add_message(
                    CHANNEL_MEETING, agent_id, panel.panel_label, KIND_NPC,
                    responder.meeting_line(panel, m.topic, m.turn),
                )
            m.turn += 1
            if m.turn >= m.max_turns:
                m.status = STATUS_FINISHED
                m.ended_at = datetime.now(timezone.utc).isoformat()
                self._store.set_meeting(m)
                self._sys("Meeting finished.")
                logger.info("world.chat: meeting %s finished", m.meeting_id)
            else:
                self._store.set_meeting(m)
            return m

    def _transition(self, allowed: tuple[str, ...], new: str, note: str) -> Meeting:
        with self._lock:
            m = self._store.get_meeting()
            if m.status not in allowed:
                raise MeetingError(f"cannot {note.lower()}: meeting is {m.status}")
            m.status = new
            if new == STATUS_STOPPED:
                m.ended_at = datetime.now(timezone.utc).isoformat()
            self._store.set_meeting(m)
            self._sys(note)
            return m

    def pause(self) -> Meeting:
        return self._transition((STATUS_RUNNING,), STATUS_PAUSED, "Meeting paused.")

    def resume(self) -> Meeting:
        return self._transition((STATUS_PAUSED,), STATUS_RUNNING, "Meeting resumed.")

    def stop(self) -> Meeting:
        return self._transition((STATUS_RUNNING, STATUS_PAUSED), STATUS_STOPPED, "Meeting stopped.")


__all__ = ["MeetingEngine", "MeetingError", "STATUS_IDLE"]
