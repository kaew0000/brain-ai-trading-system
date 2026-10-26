"""tests/test_world_chat.py — V16 §83 World chat & meetings."""
from __future__ import annotations

import ast
import json
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from world.workspace.models import AgentPanelState

pytestmark = pytest.mark.unit

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _panel(agent_id: str, label: str, **kw) -> AgentPanelState:
    base = dict(status="idle", heartbeat_age_s=None, latency_ms=None, last_decision=None,
                current_task=None, last_update="t", room_id="r")
    base.update(kw)
    return AgentPanelState(panel_label=label, agent_id=agent_id, **base)


FAKE = (
    _panel("primus", "CEO", status="analyzing", last_decision="HOLD BTCUSDT", current_task="Review"),
    _panel("bastion", "Risk", heartbeat_age_s=1.5),
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    from config.settings import settings
    from world.chat import api as chat_api
    monkeypatch.setattr(settings, "WORLD_CHAT_STORE_PATH", str(tmp_path / "chat.json"))
    monkeypatch.setattr(settings, "WORLD_MEETING_TURN_INTERVAL_SECONDS", 0.0)
    monkeypatch.setattr(chat_api, "_panels", lambda: FAKE)
    chat_api.reset_for_tests()
    yield
    chat_api.reset_for_tests()


@pytest.fixture()
def client():
    from api.app import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_roster(client):
    r = client.get("/api/world/chat/roster").json()["data"]
    assert r["engine"] == "rule-based"
    assert [a["agentId"] for a in r["agents"]] == ["primus", "bastion"]


def test_office_mention_gets_reply_from_real_state(client):
    r = client.post("/api/world/chat/messages", json={"channel": "office", "text": "@[CEO] status? last decision"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["message"]["mentions"] == ["primus"]
    assert len(d["replies"]) == 1
    text = d["replies"][0]["text"]
    assert "analyzing" in text and "HOLD BTCUSDT" in text


def test_missing_data_reported_unavailable_not_invented(client):
    d = client.post("/api/world/chat/messages", json={"channel": "dm:bastion", "text": "latency?"}).json()["data"]
    assert "unavailable" in d["replies"][0]["text"]


def test_office_without_mention_has_no_reply(client):
    d = client.post("/api/world/chat/messages", json={"channel": "office", "text": "hello all"}).json()["data"]
    assert d["replies"] == []


@pytest.mark.parametrize("channel,text", [("dm:ghost", "x"), ("nope", "x"), ("office", "   ")])
def test_validation(client, channel, text):
    assert client.post("/api/world/chat/messages", json={"channel": channel, "text": text}).status_code == 400


def test_text_cap(client, monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "WORLD_CHAT_MAX_TEXT_CHARS", 5)
    assert client.post("/api/world/chat/messages", json={"text": "123456"}).status_code == 400


def test_messages_listing_after_cursor(client):
    ids = [client.post("/api/world/chat/messages", json={"text": f"m{i}"}).json()["data"]["message"]["id"]
           for i in range(3)]
    got = client.get("/api/world/chat/messages", params={"channel": "office", "after": ids[0]}).json()["data"]
    assert [m["id"] for m in got] == ids[1:]


def test_store_bounded_and_persisted(tmp_path, monkeypatch):
    from config.settings import settings
    from world.chat import api as chat_api
    monkeypatch.setattr(settings, "WORLD_CHAT_MAX_MESSAGES_PER_CHANNEL", 10)
    chat_api.reset_for_tests()
    for i in range(25):
        chat_api.post_message("office", f"m{i}", "u", "You")
    assert len(chat_api.list_messages("office", 100)) == 10
    saved = json.loads((tmp_path / "chat.json").read_text())
    assert len(saved["channels"]["office"]) == 10
    chat_api.reset_for_tests()  # reload from disk
    assert chat_api.list_messages("office", 100)[-1]["text"] == "m24"


def test_corrupt_store_starts_empty(tmp_path):
    from world.chat import api as chat_api
    (tmp_path / "chat.json").write_text("{not json")
    chat_api.reset_for_tests()
    assert chat_api.list_messages("office", 10) == []


def _start(client, **over):
    body = {"topic": "priorities", "participants": ["primus", "bastion"], "maxTurns": 5, "mode": "manual"}
    body.update(over)
    return client.post("/api/world/chat/meeting/start", json=body)


def test_manual_meeting_round_robin_and_finish(client):
    assert _start(client).status_code == 200
    for _ in range(5):
        assert client.post("/api/world/chat/meeting/next").status_code == 200
    m = client.get("/api/world/chat/meeting").json()["data"]
    assert m["status"] == "finished" and m["turn"] == 5
    speakers = [x["senderId"] for x in client.get("/api/world/chat/messages", params={"channel": "meeting"}).json()["data"]
                if x["senderKind"] == "npc"]
    assert speakers == ["primus", "bastion", "primus", "bastion", "primus"]
    assert client.post("/api/world/chat/meeting/next").status_code == 409


@pytest.mark.parametrize("over", [{"maxTurns": 4}, {"maxTurns": 51}, {"participants": []},
                                  {"participants": ["ghost"]}, {"participants": ["primus", "ghost"]},
                                  {"topic": " "}, {"mode": "weird"}])
def test_meeting_validation(client, over):
    assert _start(client, **over).status_code == 400


def test_second_meeting_rejected_then_stop_allows_new(client):
    assert _start(client).status_code == 200
    assert _start(client).status_code == 409
    assert client.post("/api/world/chat/meeting/stop").status_code == 200
    assert _start(client).status_code == 200


def test_pause_resume(client):
    _start(client)
    assert client.post("/api/world/chat/meeting/pause").json()["data"]["status"] == "paused"
    assert client.post("/api/world/chat/meeting/next").status_code == 409
    assert client.post("/api/world/chat/meeting/resume").json()["data"]["status"] == "running"


def test_auto_meeting_completes_and_driver_exits(client):
    assert _start(client, mode="auto").status_code == 200
    deadline = time.time() + 5
    while time.time() < deadline:
        if client.get("/api/world/chat/meeting").json()["data"]["status"] == "finished":
            break
        time.sleep(0.05)
    assert client.get("/api/world/chat/meeting").json()["data"]["status"] == "finished"
    time.sleep(0.1)
    assert client.get("/api/world/chat/health").json()["data"]["driverActive"] is False


def test_hybrid_user_message_pauses_meeting(client, monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "WORLD_MEETING_TURN_INTERVAL_SECONDS", 30.0)
    _start(client, mode="auto", hybrid=True)
    client.post("/api/world/chat/messages", json={"channel": "meeting", "text": "wait"})
    assert client.get("/api/world/chat/meeting").json()["data"]["status"] == "paused"
    assert client.get("/api/world/chat/health").json()["data"]["driverActive"] is False


def test_live_meeting_restored_as_stopped_after_restart():
    from world.chat import api as chat_api
    chat_api.start_meeting("t", ["primus"], 5, "manual", False)
    chat_api.reset_for_tests()
    assert chat_api.get_meeting().status == "stopped"


def test_disabled_returns_503(client, monkeypatch):
    from config.settings import settings
    monkeypatch.setattr(settings, "WORLD_CHAT_ENABLED", False)
    assert client.get("/api/world/chat/roster").status_code == 503


def test_health(client):
    d = client.get("/api/world/chat/health").json()["data"]
    assert d["engine"] == "rule-based" and d["npcCount"] == 2


def test_boundary_no_trading_imports():
    forbidden = {"agents", "execution", "portfolio", "risk", "journal", "learning",
                 "strategy", "exchange", "futures", "decision", "governance"}
    files = list((ROOT / "world" / "chat").glob("*.py")) + [ROOT / "api" / "world_chat_api.py"]
    assert files
    for f in files:
        for node in ast.walk(ast.parse(f.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                assert n.split(".")[0] not in forbidden, f"{f.name} imports {n}"


def test_duplicate_participants_are_deduplicated(client):
    d = _start(client, participants=["primus", "primus", "bastion"]).json()["data"]
    assert d["participants"] == ["primus", "bastion"]
