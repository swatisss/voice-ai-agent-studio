"""Persona library, snapshot resolution, call overrides and live switching.

Covers: PER-01, PER-02, PER-03, PER-04, PER-05, PER-06, TD-06
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from voiceai.core.db import sessionmaker
from voiceai.live import LIVE, LiveControls
from voiceai.core.llm.gateway import FakeReply
from voiceai.core.tables import AgentVersion, CallEvent
from voiceai.voice.turn_detection import TurnSettings

M = {"X-Tenant-Id": "evergreen-care"}
P = {"X-Tenant-Id": "evergreen-sandbox"}
NEW = {
    "name": "Mira", "description": "Calm and clear", "voice": "aura-2-andromeda-en", "speed": 0.9,
    "greeting": "Hello, this is Mira at Evergreen.", "disclosure": "I'm a virtual assistant and calls may be recorded.",
    "opening": "Hi {first_name}, it's Mira.", "style": "Calm, clear and unhurried.",
}


async def _persona(client, headers=M, **over) -> dict[str, Any]:  # noqa: ANN001, ANN003
    r = await client.post("/api/personas", headers=headers, json={**NEW, **over})
    assert r.status_code == 200, r.text
    return r.json()


async def test_persona_crud_and_validation(client, seeded):
    """Covers: PER-01"""
    seeded_names = {p["name"] for p in (await client.get("/api/personas", headers=M)).json()["items"]}
    assert {"Ava", "Grace", "Leo"} <= seeded_names
    p = await _persona(client)
    assert p["speed"] == 0.9 and p["voice"] == "aura-2-andromeda-en" and p["used_by"] == []
    r = await client.put(f"/api/personas/{p['id']}", headers=M, json={**NEW, "name": "Mira B", "speed": 1.2})
    assert r.json()["name"] == "Mira B" and r.json()["speed"] == 1.2
    assert (await client.post("/api/personas", headers=M, json={**NEW, "speed": 2.0})).status_code == 422
    assert (await client.post("/api/personas", headers=M, json={**NEW, "voice": "robot-voice"})).status_code == 422
    assert p["id"] not in {x["id"] for x in (await client.get("/api/personas", headers=P)).json()["items"]}  # tenant scoped
    assert (await client.put(f"/api/personas/{p['id']}", headers=P, json=NEW)).status_code == 404


async def test_snapshot_resolves_persona_and_stays_immutable(client, seeded):
    """Covers: PER-02"""
    agent_id = seeded["care"]["agent_id"]
    p = await _persona(client)
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=M)).json()["draft_config"]
    await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": {**cfg, "persona_id": p["id"]}})
    version = (await client.post(f"/api/agents/{agent_id}/publish", headers=M, json={})).json()
    async with sessionmaker()() as s:
        snap = (await s.get(AgentVersion, version["id"])).config["persona"]
    assert snap["id"] == p["id"] and snap["name"] == "Mira" and snap["speed"] == 0.9
    await client.put(f"/api/personas/{p['id']}", headers=M, json={**NEW, "name": "Renamed"})
    async with sessionmaker()() as s:
        assert (await s.get(AgentVersion, version["id"])).config["persona"]["name"] == "Mira"


async def test_call_start_override_uses_persona_greeting(client, seeded):
    """Covers: PER-03"""
    p = await _persona(client)
    r = await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text", "persona_id": p["id"]})
    out = r.json()
    assert out["greeting"].startswith("Hello, this is Mira at Evergreen.")
    assert out["settings"]["persona"]["name"] == "Mira" and out["settings"]["persona"]["voice"] == "aura-2-andromeda-en"
    r = await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text", "turn_detection": {"mode": "semantic", "min_silence_ms": 900}})
    td = r.json()["settings"]["turn_detection"]
    assert td["mode"] == "semantic" and td["min_silence_ms"] == 900 and td["max_extra_wait_ms"] == 1500


async def test_live_persona_switch_changes_next_turn_only(client, seeded, fake_llm):
    """Covers: PER-04"""
    prompts: list[str] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        prompts.append(messages[0]["content"])
        return FakeReply(text="Sure thing.")

    fake_llm(responder)
    grace = next(p for p in (await client.get("/api/personas", headers=M)).json()["items"] if p["name"] == "Grace")
    call = (await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})).json()
    cid = call["call_id"]
    await client.post(f"/api/calls/{cid}/messages", headers=M, json={"text": "hello"})
    assert "You are Ava" in prompts[0]
    r = await client.patch(f"/api/calls/{cid}/live", headers=M, json={"persona_id": grace["id"]})
    assert r.status_code == 200 and r.json()["settings"]["persona"]["name"] == "Grace"
    await client.post(f"/api/calls/{cid}/messages", headers=M, json={"text": "and another thing"})
    assert "You are Grace" in prompts[1]
    async with sessionmaker()() as s:
        events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == cid).order_by(CallEvent.seq))).all()
    assert any(e.kind == "system" and e.text == "Persona switched to Grace" for e in events)
    assert sum(1 for e in events if e.data.get("greeting")) == 1  # no second greeting
    r = await client.patch(f"/api/calls/{cid}/live", headers=M, json={"persona_id": ""})  # back to the agent's persona
    assert r.json()["settings"]["persona"]["name"] == "Ava"
    detail = (await client.get(f"/api/calls/{cid}", headers=M)).json()
    assert detail["settings"]["persona"]["name"] == "Ava"


async def test_live_turn_detection_and_voice_callback(client, seeded):
    """Covers: TD-06, PER-04"""
    call = (await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})).json()
    cid = call["call_id"]
    heard: list[tuple[str, float]] = []

    async def on_voice(voice: str, speed: float) -> None:
        heard.append((voice, speed))

    LIVE[cid] = LiveControls(turn=TurnSettings(mode="vad"), on_voice=on_voice)  # as the voice pipeline registers it
    try:
        r = await client.patch(f"/api/calls/{cid}/live", headers=M, json={"turn_detection": {"mode": "vad", "min_silence_ms": 400, "allow_interruptions": False}})
        assert r.json()["settings"]["turn_detection"]["min_silence_ms"] == 400
        assert LIVE[cid].turn.min_silence_ms == 400 and LIVE[cid].turn.allow_interruptions is False and LIVE[cid].turn.mode == "vad"
        leo = next(p for p in (await client.get("/api/personas", headers=M)).json()["items"] if p["name"] == "Leo")
        await client.patch(f"/api/calls/{cid}/live", headers=M, json={"persona_id": leo["id"]})
        assert heard == [("aura-2-apollo-en", 1.05)]
    finally:
        LIVE.pop(cid, None)
    assert (await client.patch(f"/api/calls/{cid}/live", headers=M, json={"turn_detection": {"min_silence_ms": 50}})).status_code == 422
    await client.post(f"/api/calls/{cid}/end", headers=M)
    assert (await client.patch(f"/api/calls/{cid}/live", headers=M, json={"turn_detection": {"mode": "semantic"}})).status_code == 409
    assert (await client.patch("/api/calls/nope/live", headers=M, json={})).status_code == 404


async def test_delete_blocked_while_in_use(client, seeded):
    """Covers: PER-05"""
    agent_id = seeded["care"]["agent_id"]
    p = await _persona(client)
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=M)).json()["draft_config"]
    default_id = cfg["persona_id"]
    await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": {**cfg, "persona_id": p["id"]}})
    r = await client.delete(f"/api/personas/{p['id']}", headers=M)
    assert r.status_code == 409 and r.json()["error"] == "persona_in_use" and "Customer Care Agent" in r.json()["detail"]
    await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": {**cfg, "persona_id": default_id}})
    assert (await client.delete(f"/api/personas/{p['id']}", headers=M)).status_code == 204


async def test_other_tenants_persona_is_rejected(client, seeded):
    """Covers: PER-06"""
    foreign = await _persona(client, headers=P)
    agent_id = seeded["care"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=M)).json()["draft_config"]
    await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": {**cfg, "persona_id": foreign["id"]}})
    assert (await client.post(f"/api/agents/{agent_id}/publish", headers=M, json={})).status_code == 422
    r = await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "text", "persona_id": foreign["id"]})
    assert r.status_code == 404
