"""world/chat/models.py — plain dataclasses, camelCase on the wire."""
from __future__ import annotations

from dataclasses import dataclass, field

CHANNEL_OFFICE = "office"
CHANNEL_MEETING = "meeting"
DM_PREFIX = "dm:"

KIND_USER = "user"
KIND_NPC = "npc"
KIND_SYSTEM = "system"

MODE_AUTO = "auto"
MODE_MANUAL = "manual"

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_PAUSED = "paused"
STATUS_FINISHED = "finished"
STATUS_STOPPED = "stopped"


@dataclass(frozen=True)
class ChatMessage:
    id: str
    channel: str
    sender_id: str
    sender_name: str
    sender_kind: str
    text: str
    ts: str
    mentions: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "channel": self.channel, "senderId": self.sender_id,
            "senderName": self.sender_name, "senderKind": self.sender_kind,
            "text": self.text, "ts": self.ts, "mentions": list(self.mentions),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChatMessage":
        return cls(
            id=d["id"], channel=d["channel"], sender_id=d["senderId"],
            sender_name=d["senderName"], sender_kind=d["senderKind"],
            text=d["text"], ts=d["ts"], mentions=tuple(d.get("mentions", ())),
        )


@dataclass
class Meeting:
    meeting_id: str = ""
    topic: str = ""
    participants: list[str] = field(default_factory=list)
    max_turns: int = 0
    mode: str = MODE_AUTO
    hybrid: bool = False
    status: str = STATUS_IDLE
    turn: int = 0
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict:
        return {
            "meetingId": self.meeting_id, "topic": self.topic,
            "participants": list(self.participants), "maxTurns": self.max_turns,
            "mode": self.mode, "hybrid": self.hybrid, "status": self.status,
            "turn": self.turn, "startedAt": self.started_at, "endedAt": self.ended_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Meeting":
        return cls(
            meeting_id=d.get("meetingId", ""), topic=d.get("topic", ""),
            participants=list(d.get("participants", [])), max_turns=int(d.get("maxTurns", 0)),
            mode=d.get("mode", MODE_AUTO), hybrid=bool(d.get("hybrid", False)),
            status=d.get("status", STATUS_IDLE), turn=int(d.get("turn", 0)),
            started_at=d.get("startedAt"), ended_at=d.get("endedAt"),
        )
