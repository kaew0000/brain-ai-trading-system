"""world/chat/store.py — bounded, thread-safe, atomically persisted chat store.

The only thing in World that writes. Per-channel deque caps memory;
persistence is tmp-file + os.replace so a crash never leaves a torn file.
A meeting that was `running`/`paused` when the process died is restored
as `stopped` (no zombie meetings with no driver task).
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone

from utils.logger import get_logger
from world.chat.models import (
    STATUS_PAUSED, STATUS_RUNNING, STATUS_STOPPED, ChatMessage, Meeting,
)

logger = get_logger("world.chat.store")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ChatStore:
    def __init__(self, path: str, max_per_channel: int) -> None:
        self._path = path
        self._max = max_per_channel
        self._lock = threading.RLock()
        self._channels: dict[str, deque[ChatMessage]] = {}
        self._meeting = Meeting()
        self._load()

    # ── persistence ──────────────────────────────────────────────
    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = f.read().strip()
            if not raw:
                return
            data = json.loads(raw)
            for channel, items in data.get("channels", {}).items():
                dq: deque[ChatMessage] = deque(maxlen=self._max)
                for item in items[-self._max:]:
                    dq.append(ChatMessage.from_dict(item))
                self._channels[channel] = dq
            self._meeting = Meeting.from_dict(data.get("meeting", {}))
            if self._meeting.status in (STATUS_RUNNING, STATUS_PAUSED):
                self._meeting.status = STATUS_STOPPED
                self._meeting.ended_at = _now()
                logger.warning("world.chat: meeting %s was live at shutdown; marked stopped",
                               self._meeting.meeting_id)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("world.chat: store unreadable (%s) — starting empty", exc)
            self._channels = {}
            self._meeting = Meeting()

    def _save_locked(self) -> None:
        payload = {
            "channels": {c: [m.to_dict() for m in dq] for c, dq in self._channels.items()},
            "meeting": self._meeting.to_dict(),
        }
        tmp = f"{self._path}.tmp"
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, self._path)
        except OSError as exc:
            # Memory stays authoritative; chat keeps working without disk.
            logger.error("world.chat: persist failed (%s)", exc)

    # ── messages ─────────────────────────────────────────────────
    def add_message(self, channel: str, sender_id: str, sender_name: str,
                    sender_kind: str, text: str, mentions: tuple[str, ...] = ()) -> ChatMessage:
        msg = ChatMessage(
            id=uuid.uuid4().hex[:12], channel=channel, sender_id=sender_id,
            sender_name=sender_name, sender_kind=sender_kind, text=text,
            ts=_now(), mentions=mentions,
        )
        with self._lock:
            self._channels.setdefault(channel, deque(maxlen=self._max)).append(msg)
            self._save_locked()
        return msg

    def list_messages(self, channel: str, limit: int, after_id: str | None = None) -> list[ChatMessage]:
        with self._lock:
            items = list(self._channels.get(channel, ()))
        if after_id:
            for i, m in enumerate(items):
                if m.id == after_id:
                    items = items[i + 1:]
                    break
        return items[-limit:]

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {c: len(dq) for c, dq in self._channels.items()}

    # ── meeting ──────────────────────────────────────────────────
    def get_meeting(self) -> Meeting:
        with self._lock:
            return Meeting.from_dict(self._meeting.to_dict())

    def set_meeting(self, meeting: Meeting) -> None:
        with self._lock:
            self._meeting = meeting
            self._save_locked()

    def clear_channel(self, channel: str) -> None:
        with self._lock:
            self._channels.pop(channel, None)
            self._save_locked()
