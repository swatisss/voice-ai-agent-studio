"""Effective call settings resolved once; live changes reach the pipeline only through the session.

Covers: PER-07, TD-09
"""
from __future__ import annotations

from voiceai.db import sessionmaker
from voiceai.live import LiveControls, SettingsChange, follow
from voiceai.models import Persona
from voiceai.runtime.session import AgentSession
from voiceai.voice.turn_detection import TurnSettings

M = {"X-Tenant-Id": "evergreen-care"}


async def personas(client) -> dict[str, str]:  # noqa: ANN001
    return {p["name"]: p["id"] for p in (await client.get("/api/personas", headers=M)).json()["items"]}


async def test_every_call_response_reports_the_sessions_settings(client, seeded):
    """Covers: PER-07"""
    ids = await personas(client)
    started = (await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text",
                                                                "persona_id": ids["Grace"]})).json()
    cid = started["call_id"]
    assert started["settings"]["persona"]["name"] == "Grace"
    patched = (await client.patch(f"/api/calls/{cid}/live", headers=M, json={"persona_id": ids["Leo"]})).json()["settings"]
    detail = (await client.get(f"/api/calls/{cid}", headers=M)).json()["settings"]
    session = await AgentSession.open(cid, "evergreen-care")
    assert patched == detail == session.settings() and detail["persona"]["name"] == "Leo"


async def test_a_deleted_override_falls_back_to_the_snapshot(client, seeded):
    """Covers: PER-07"""
    ids = await personas(client)
    cid = (await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text",
                                                            "persona_id": ids["Grace"]})).json()["call_id"]
    async with sessionmaker()() as s:
        await s.delete(await s.get(Persona, ids["Grace"]))
        await s.commit()
    from voiceai.runtime.session import REGISTRY

    REGISTRY.pop(cid, None)  # a fresh session resolves again, as after a restart
    detail = (await client.get(f"/api/calls/{cid}", headers=M)).json()["settings"]
    session = await AgentSession.open(cid, "evergreen-care")
    assert detail["persona"]["name"] == session.settings()["persona"]["name"] != "Grace"


async def test_live_changes_reach_the_pipeline_only_through_the_session(client, seeded):
    """Covers: TD-09"""
    cid = (await client.post("/api/calls", headers=M, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})).json()["call_id"]
    untouched = LiveControls(turn=TurnSettings(mode="vad", min_silence_ms=700))
    # controls not following the session: the route has no other way to reach a pipeline
    await client.patch(f"/api/calls/{cid}/live", headers=M, json={"turn_detection": {"min_silence_ms": 400}})
    assert untouched.turn.min_silence_ms == 700

    session = await AgentSession.open(cid, "evergreen-care")
    voices: list[tuple[str, float]] = []

    async def on_voice(voice: str, speed: float) -> None:
        voices.append((voice, speed))

    controls = LiveControls(turn=session.turn_settings(), on_voice=on_voice)
    follow(session, controls)
    ids = await personas(client)
    await client.patch(f"/api/calls/{cid}/live", headers=M, json={"turn_detection": {"min_silence_ms": 900}, "persona_id": ids["Leo"]})
    assert controls.turn.min_silence_ms == 900 and voices == [("aura-2-apollo-en", 1.05)]

    heard: list[SettingsChange] = []

    async def listener(change: SettingsChange) -> None:
        heard.append(change)

    session.subscribe(listener)
    await session.end("hangup")
    await session.change_turn_detection({"min_silence_ms": 300})  # after the end: nothing is delivered
    assert heard == []
