"""CP-0050: live voice handover on a hosted media room - tokens, admission, the handover state machine, the scribe's events, end paths.

Everything runs against a fake room backend (`tests/livekit_fakes.py`), a fake LLM, the hash embedder and a temp SQLite database:
no LiveKit account, no network, no secret.

Covers: LKH-01, LKH-02, LKH-03, LKH-04, LKH-05, LKH-06, LKH-07, LKH-08, LKH-09, LKH-10, LKH-11, LKH-12, LKH-13, LKH-14, LKH-15, LKH-17, LKH-18, LKH-19, LKH-20, LKH-21
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from tests.conftest import script
from tests.livekit_fakes import FakeBackend
from voiceai import desk, media_room
from voiceai.config import Settings, get_settings
from voiceai.db import sessionmaker
from voiceai.events import bus
from voiceai.models import Call, CallEvent, Escalation
from voiceai.runtime import escalation as esc_mod
from voiceai.runtime.session import REGISTRY

H = {"X-Tenant-Id": "northgate-health"}
SECRET = "lk-secret-0123456789abcdef-never-leaks"
KEY = "APIkeyForTests"
URL = "wss://example-project.livekit.cloud"


@pytest.fixture
def room(monkeypatch, fake_llm):  # noqa: ANN001, ANN201
    """LiveKit settings set, a fake backend installed, a fake LLM that never answers except by rule."""
    for k, v in {"LIVEKIT_URL": URL, "LIVEKIT_API_KEY": KEY, "LIVEKIT_API_SECRET": SECRET, "DEEPGRAM_API_KEY": "dg-test",
                 "HANDOVER_WAIT_S": "30"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    backend = FakeBackend()
    media_room.set_backend(backend)
    media_room.ROOMS.clear()
    fake_llm(script())
    yield backend
    media_room.set_backend(None)
    media_room.ROOMS.clear()
    get_settings.cache_clear()


async def start(client, seeded, **extra):  # noqa: ANN001, ANN201
    body = {"agent_id": seeded["care"]["agent_id"], "channel": "voice", "transport": "livekit", **extra}
    r = await client.post("/api/calls", headers=H, json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def escalate(call_id: str):  # noqa: ANN201
    """The customer asks for a person: the runtime escalates and wants the hand-off (the pipeline's `end("handoff")`)."""
    session = REGISTRY[call_id]
    await session.reply("I want to speak to a human")
    await media_room.settle()
    await esc_mod.wait_packets()
    return session


async def esc_of(call_id: str) -> Escalation:
    async with sessionmaker()() as s:
        return await s.scalar(select(Escalation).where(Escalation.call_id == call_id))


async def call_of(call_id: str) -> Call:
    async with sessionmaker()() as s:
        return await s.get(Call, call_id)


async def events_of(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


async def join_specialist(client, esc_id: str, name: str = "Sam Specialist"):  # noqa: ANN001, ANN201
    r = await client.post(f"/api/escalations/{esc_id}/voice/join", headers=H, json={})
    assert r.status_code == 200, r.text
    return r.json()


async def waiting_call(client, seeded):  # noqa: ANN001, ANN201
    started = await start(client, seeded)
    call_id = started["call_id"]
    await media_room.participant_connected(call_id, "cust-abc")
    await escalate(call_id)
    return call_id, (await esc_of(call_id)).id


# ------------------------------------------------------------------ LKH-01, LKH-02, LKH-21
async def test_start_returns_connect_and_503_without_settings(client, seeded, room, monkeypatch):
    """Covers: LKH-01"""
    got = await start(client, seeded)
    assert got["connect"]["url"] == URL and got["connect"]["room"] == f"lk-{got['call_id']}"
    assert media_room.decode(got["connect"]["token"])["video"]["room"] == f"lk-{got['call_id']}"
    assert (await call_of(got["call_id"])).media_room == f"lk-{got['call_id']}"
    assert (await client.get("/healthz")).json()["livekit"] is True
    direct = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})
    assert "connect" not in direct.json()  # the other transports are unchanged
    monkeypatch.setenv("LIVEKIT_API_SECRET", "")
    get_settings.cache_clear()
    refused = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "voice", "transport": "livekit"})
    assert refused.status_code == 503 and refused.json()["error"] == "livekit_unavailable"
    assert (await client.get("/healthz")).json()["livekit"] is False
    bad = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text", "transport": "livekit"})
    assert bad.status_code in (422, 503)


async def test_customer_token_grants_and_secret_never_leaks(client, seeded, room, caplog):
    """Covers: LKH-02"""
    caplog.set_level("DEBUG")
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "voice", "transport": "livekit"})
    claims = media_room.decode(r.json()["connect"]["token"])
    v = claims["video"]
    assert v["roomJoin"] and v["canPublish"] and v["canSubscribe"] and v["canPublishData"] is False and v["roomAdmin"] is False
    assert v["canPublishSources"] == ["microphone"]
    assert claims["sub"].startswith("cust-") and len(claims["sub"]) > len("cust-")
    assert claims["exp"] - claims["nbf"] <= get_settings().livekit_token_ttl_s
    assert claims["iss"] == KEY
    assert SECRET not in r.text and SECRET not in caplog.text
    assert SECRET not in json.dumps((await client.get("/healthz")).json())
    spec = media_room.decode(media_room.mint("specialist", "lk-x", "spec-1")["token"])["video"]
    assert spec["canPublish"] and spec["canPublishData"] and spec["roomAdmin"] is False
    scribe = media_room.decode(media_room.mint("scribe", "lk-x", "scribe-1")["token"])["video"]
    assert scribe["canPublish"] is False and scribe["canSubscribe"] and scribe["canPublishData"] is False
    assert media_room.mint("customer", "lk-x", "cust-1", ttl_s=99999)["token"]  # a longer ask is capped, not refused
    capped = media_room.decode(media_room.mint("customer", "lk-x", "cust-1", ttl_s=99999)["token"])
    assert capped["exp"] - capped["nbf"] <= get_settings().livekit_token_ttl_s


def test_settings_from_dotenv_lines_only(tmp_path, monkeypatch):
    """Covers: LKH-21"""
    env = tmp_path / ".env"
    env.write_text(f"LIVEKIT_URL={URL}\nLIVEKIT_API_KEY={KEY}\nLIVEKIT_API_SECRET={SECRET}\n", encoding="utf-8")
    for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(k, raising=False)
    full = Settings(_env_file=env)
    assert (full.livekit_url, full.livekit_api_key, full.livekit_api_secret) == (URL, KEY, SECRET)
    monkeypatch.setattr(media_room, "get_settings", lambda: full)
    assert media_room.configured() is True
    for missing in ("livekit_url", "livekit_api_key", "livekit_api_secret"):
        monkeypatch.setattr(media_room, "get_settings", lambda m=missing: full.model_copy(update={m: None}))
        assert media_room.configured() is False
    deploy = (Path(__file__).resolve().parents[3] / "infra" / "deploy-cloudrun.sh").read_text(encoding="utf-8")
    assert "LIVEKIT_API_KEY LIVEKIT_API_SECRET" in deploy and "LIVEKIT_URL" in deploy


# ------------------------------------------------------------------ LKH-03, LKH-13
async def test_ai_joins_and_hears_only_the_customer(client, seeded, room):
    """Covers: LKH-03"""
    from pipecat.processors.frame_processor import FrameProcessor

    from voiceai.voice.livekit_transport import CustomerAudioOnly, is_customer

    got = await start(client, seeded)
    await media_room.settle()
    assert room.ai_started == [got["call_id"]]
    assert is_customer("cust-a1") and not is_customer("spec-a1") and not is_customer("scribe-x") and not is_customer(None)

    class Audio:  # shaped like pipecat's UserAudioRawFrame: audio plus the speaker's identity
        def __init__(self, user_id): self.user_id = user_id  # noqa: E704, ANN001

    from pipecat.frames.frames import InputAudioRawFrame

    pushed: list = []
    proc = CustomerAudioOnly()

    async def push(frame, direction=None):  # noqa: ANN001, ANN202
        pushed.append(frame)

    async def no_base(self, frame, direction):  # noqa: ANN001, ANN202
        return None

    proc.push_frame = push  # type: ignore[method-assign]
    orig = FrameProcessor.process_frame
    FrameProcessor.process_frame = no_base  # type: ignore[method-assign]
    try:
        for who in ("cust-1", "spec-1", "ai-x", "cust-2"):
            f = InputAudioRawFrame(audio=b"\x00\x00", sample_rate=16000, num_channels=1)
            f.user_id = who  # type: ignore[attr-defined]
            await proc.process_frame(f, None)
    finally:
        FrameProcessor.process_frame = orig  # type: ignore[method-assign]
    assert [f.user_id for f in pushed] == ["cust-1", "cust-2"]


async def test_the_room_pipeline_builds_without_network(room):
    """Covers: LKH-03"""
    from voiceai.call_settings import CallSettings
    from voiceai.live import LiveControls
    from voiceai.voice.livekit_transport import RoomLink
    from voiceai.voice.pipeline import build
    from voiceai.voice.turn_detection import TurnSettings

    config = {"persona": {"voice": "aura-2-thalia-en", "speed": 1.0}}
    session = SimpleNamespace(config=config, call_settings=CallSettings.of(config), history=[], turn_settings=lambda: TurnSettings(), in_room=True)
    task, _transport, brain, serializer = build(RoomLink(URL, "tok", "lk-x"), session, "dg-test", LiveControls(turn=TurnSettings()))  # type: ignore[arg-type]
    assert task is not None and brain.session is session and serializer.end_reason == "hangup"


async def test_join_failure_ends_the_call_error(client, seeded, room):
    """Covers: LKH-13"""
    room.fail_join = True
    got = await start(client, seeded)
    await media_room.settle()
    call = await call_of(got["call_id"])
    assert call.ended_at is not None and call.end_reason == "error"
    assert room.messages("end") == [{"type": "end", "reason": "error"}] and room.closed == [f"lk-{got['call_id']}"]


async def test_join_timeout_ends_the_call_error(client, seeded, room, monkeypatch):
    """Covers: LKH-13"""
    monkeypatch.setattr(media_room, "AI_JOIN_TIMEOUT_S", 0.05)
    room.join_delay = 1.0
    got = await start(client, seeded)
    await media_room.settle()
    assert (await call_of(got["call_id"])).end_reason == "error"


# ------------------------------------------------------------------ LKH-04
async def test_customer_disconnect_ends_hangup_and_keeps_the_escalation(client, seeded, room):
    """Covers: LKH-04, LKH-17"""
    sub = bus.subscribe("northgate-health", {"dashboard"})
    call_id, esc_id = await waiting_call(client, seeded)
    await join_specialist(client, esc_id)
    await media_room.participant_disconnected(call_id, "cust-abc")
    call = await call_of(call_id)
    assert call.end_reason == "hangup" and call.ended_at is not None and call.outcome == "escalated"
    esc = await esc_of(call_id)
    assert esc.status == "accepted" and esc.voice_state == "ended"  # the specialist can still resolve
    assert any(e["type"] == "call.ended" for e in _drain(sub))
    bus.unsubscribe(sub)
    plain = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "voice", "transport": "livekit"})
    other = plain.json()["call_id"]
    await media_room.participant_disconnected(other, "cust-zzz")
    assert (await call_of(other)).end_reason == "hangup"


def _drain(sub) -> list:  # noqa: ANN001
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait())
    return out


# ------------------------------------------------------------------ LKH-05, LKH-17, LKH-18
async def test_escalation_in_a_room_keeps_the_call_open_and_silences_the_ai(client, seeded, room, fake_llm):
    """Covers: LKH-05, LKH-17"""
    sub = bus.subscribe("northgate-health", {"console"})
    started = await start(client, seeded)
    call_id = started["call_id"]
    await media_room.participant_connected(call_id, "cust-abc")
    session = await escalate(call_id)
    call, esc = await call_of(call_id), await esc_of(call_id)
    assert call.status == "escalated" and call.ended_at is None
    assert esc.voice_state == "waiting" and esc.status == "waiting"
    assert room.messages("handover") == [{"type": "handover", "state": "waiting"}]
    assert [e["data"].get("voice") for e in _drain(sub) if e["type"] == "escalation.updated" and e["data"].get("voice")] == ["waiting"]
    bus.unsubscribe(sub)
    assert room.scribes == [call_id]
    asked: list[str] = []
    fake_llm(lambda role, messages, tools: asked.append(role) or (_ for _ in ()).throw(RuntimeError("model was asked")))
    assert await session.reply("Hello? Is anyone there?") == ""
    assert (await session.caller_turn("Hello again")).model_turn is False
    assert asked == []


async def test_other_transports_still_end_on_handoff(client, seeded, room):
    """Covers: LKH-17"""
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})
    call_id = r.json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "I want to speak to a human"})
    call = await call_of(call_id)
    assert call.ended_at is not None and call.end_reason == "handoff" and call.media_room is None


async def test_no_idle_ending_while_a_room_call_waits_and_max_duration_applies(client, seeded, room):
    """Covers: LKH-18"""
    from voiceai.runtime.call_floor import CallFloor

    call_id, _ = await waiting_call(client, seeded)
    session = REGISTRY[call_id]
    said: list[str] = []
    ended: list[str] = []

    class Stage:
        def working(self): return False  # noqa: E704, ANN201
        async def say(self, text): said.append(text)  # noqa: E704, ANN001
        async def drained(self): return None  # noqa: E704
        async def guard_changed(self): return None  # noqa: E704

    async def on_end(reason):  # noqa: ANN001, ANN202
        ended.append(reason)

    floor = CallFloor(session, Stage(), on_end)
    floor.start()
    await floor.tick(now=10**9)  # an hour past every limit: nothing fires for a waiting room call
    await floor.stop()
    assert said == [] and ended == []
    session.config["policy"]["max_call_seconds"] = 0.05  # the hub's own clock still enforces the call length
    state = media_room.ROOMS[call_id]
    await media_room._max_clock(state)  # noqa: SLF001
    assert (await call_of(call_id)).end_reason == "max_duration"


# ------------------------------------------------------------------ LKH-06, LKH-12
async def test_wait_clock_ends_handover_timeout_and_keeps_the_escalation_waiting(client, seeded, room, monkeypatch):
    """Covers: LKH-06"""
    monkeypatch.setenv("HANDOVER_WAIT_S", "0.1")
    get_settings.cache_clear()
    call_id, _ = await waiting_call(client, seeded)
    await asyncio.sleep(0.35)
    await media_room.settle()
    call, esc = await call_of(call_id), await esc_of(call_id)
    assert call.end_reason == "handover_timeout" and call.ended_at is not None
    assert esc.status == "waiting"  # callback
    assert room.messages("end") == [{"type": "end", "reason": "handover_timeout"}]


async def test_specialist_drop_returns_to_waiting_and_no_ai_rejoins(client, seeded, room, monkeypatch):
    """Covers: LKH-12"""
    call_id, esc_id = await waiting_call(client, seeded)
    await join_specialist(client, esc_id)
    await media_room.participant_connected(call_id, "spec-one")
    assert (await esc_of(call_id)).voice_state == "connected"
    monkeypatch.setenv("HANDOVER_WAIT_S", "0.1")
    get_settings.cache_clear()
    await media_room.participant_disconnected(call_id, "spec-one")
    assert (await esc_of(call_id)).voice_state == "waiting"
    assert room.messages("handover")[-1] == {"type": "handover", "state": "waiting_again"}
    assert room.ai_started == [call_id]  # started once, never again
    rejoin = await join_specialist(client, esc_id)  # the same specialist may come back
    assert rejoin["room"] == f"lk-{call_id}"
    await media_room.participant_connected(call_id, "spec-two")
    assert (await esc_of(call_id)).voice_state == "connected"
    assert len(room.said) == 1 and room.ai_started == [call_id]  # no second introduction, no AI
    await media_room.participant_disconnected(call_id, "spec-two")
    await asyncio.sleep(0.35)  # the clock restarted when the specialist dropped
    await media_room.settle()
    assert (await call_of(call_id)).end_reason == "handover_timeout"


# ------------------------------------------------------------------ LKH-07, LKH-15, LKH-20
async def test_voice_join_accepts_and_returns_a_specialist_token(client, seeded, room):
    """Covers: LKH-07, LKH-20"""
    call_id, esc_id = await waiting_call(client, seeded)
    got = await join_specialist(client, esc_id)
    assert set(got) == {"url", "token", "room", "expires_at"} and got["url"] == URL and got["room"] == f"lk-{call_id}"
    claims = media_room.decode(got["token"])
    assert claims["sub"].startswith("spec-") and claims["video"]["roomAdmin"] is False and claims["video"]["canPublishData"] is True
    assert (await esc_of(call_id)).status == "accepted"
    again = await client.post(f"/api/escalations/{esc_id}/voice/join", headers=H, json={})
    assert again.status_code == 409 and again.json()["error"] == "already_taken"
    state = (await client.get(f"/api/escalations/{esc_id}/voice", headers=H)).json()
    assert state["state"] == "waiting" and state["room"] == f"lk-{call_id}"


async def test_voice_join_refusals(client, seeded, room, monkeypatch):
    """Covers: LKH-07, LKH-20"""
    text = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})
    await client.post(f"/api/calls/{text.json()['call_id']}/messages", headers=H, json={"text": "I want to speak to a human"})
    async with sessionmaker()() as s:
        plain = (await s.scalar(select(Escalation).where(Escalation.call_id == text.json()["call_id"]))).id
    r = await client.post(f"/api/escalations/{plain}/voice/join", headers=H, json={})
    assert r.status_code == 409 and r.json()["error"] == "not_voice"
    assert (await client.get(f"/api/escalations/{plain}/voice", headers=H)).status_code == 404
    call_id, esc_id = await waiting_call(client, seeded)
    await media_room.participant_disconnected(call_id, "cust-abc")  # the call has ended
    ended = await client.post(f"/api/escalations/{esc_id}/voice/join", headers=H, json={})
    assert ended.status_code == 409 and ended.json()["error"] == "not_waiting"
    call2, esc2 = await waiting_call(client, seeded)
    monkeypatch.setenv("LIVEKIT_API_KEY", "")
    get_settings.cache_clear()
    off = await client.post(f"/api/escalations/{esc2}/voice/join", headers=H, json={})
    assert off.status_code == 503 and off.json()["error"] == "livekit_unavailable"
    other = await client.post(f"/api/escalations/{esc2}/voice/join", headers={"X-Tenant-Id": "someone-else"}, json={})
    assert other.status_code in (403, 404)


def test_the_specialist_allow_list_has_exactly_the_two_voice_requests():
    """Covers: LKH-15"""
    assert desk.allowed("POST", "/api/escalations/e1/voice/join") and desk.allowed("GET", "/api/escalations/e1/voice")
    for method, path in (("GET", "/api/escalations/e1/voice/join"), ("POST", "/api/escalations/e1/voice"), ("DELETE", "/api/escalations/e1/voice"),
                         ("POST", "/api/escalations/e1/voice/leave"), ("POST", "/api/calls"), ("PATCH", "/api/calls/c1/live"),
                         ("POST", "/api/escalations/e1/voice/join/x")):
        assert not desk.allowed(method, path), (method, path)


# ------------------------------------------------------------------ LKH-08, LKH-09, LKH-10, LKH-11
async def test_warm_handover_one_introduction_then_the_ai_leaves(client, seeded, room):
    """Covers: LKH-08"""
    call_id, esc_id = await waiting_call(client, seeded)
    await join_specialist(client, esc_id)
    await media_room.participant_connected(call_id, "spec-sam1")
    await media_room.participant_connected(call_id, "spec-sam1")  # reported twice (AI room and scribe): still one introduction
    assert room.said == [(call_id, "I'm bringing in Specialist, who has the details of your request.")]
    assert room.ai_stopped == [call_id]
    assert (await esc_of(call_id)).voice_state == "connected"
    assert room.messages("handover")[-1] == {"type": "handover", "state": "connected", "specialist": "Specialist"}
    lines = [e for e in await events_of(call_id) if e.kind == "assistant" and (e.data or {}).get("handover_intro")]
    assert len(lines) == 1
    assert any(e.kind == "system" and (e.data or {}).get("segment_end") == "handoff" for e in await events_of(call_id))
    assert (await call_of(call_id)).ended_at is None


async def test_scribe_turns_both_voices_into_ordered_events(client, seeded, room):
    """Covers: LKH-09"""
    call_id, esc_id = await waiting_call(client, seeded)
    await join_specialist(client, esc_id)
    await media_room.participant_connected(call_id, "spec-sam1")
    await media_room.transcript(call_id, "cust-abc", "I need help with my claim", False)  # partial: never stored
    await media_room.transcript(call_id, "cust-abc", "I need help with my claim", True)
    await media_room.transcript(call_id, "spec-sam1", "Of course, let me look at that.", True)
    await media_room.transcript(call_id, "ai-" + call_id, "ignored", True)  # not a human track
    evs = [e for e in await events_of(call_id) if e.kind in ("user", "human")]
    last_two = evs[-2:]
    assert [e.kind for e in last_two] == ["user", "human"] and last_two[0].seq < last_two[1].seq
    assert last_two[0].data["source"] == "voice" and last_two[1].data["source"] == "voice"
    assert last_two[1].data["role"] == "specialist" and last_two[1].data["participant"] == "spec-sam1"
    assert not any(e.text == "ignored" for e in await events_of(call_id))
    assert [e.text for e in await events_of(call_id)].count("I need help with my claim") == 1
    seqs = [e.seq for e in await events_of(call_id)]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # one seq order
    import voiceai.models as models

    assert not [t for t in models.Base.metadata.tables if "audio" in t]  # no audio is stored


async def test_spoken_specialist_lines_are_human_turns_for_analysis(client, seeded, room):
    """Covers: LKH-10"""
    call_id, esc_id = await waiting_call(client, seeded)
    await join_specialist(client, esc_id)
    await media_room.participant_connected(call_id, "spec-sam1")
    await media_room.transcript(call_id, "cust-abc", "My claim was denied", True)
    await media_room.transcript(call_id, "spec-sam1", "I will refile it today", True)
    lines = esc_mod.transcript_lines(await events_of(call_id))
    assert "Caller: My claim was denied" in lines and "Specialist: I will refile it today" in lines
    short = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "resolved_by_human", "resolution_note": "short"})
    assert short.status_code == 422 and short.json()["error"] == "note_too_short"  # ES-07 still holds
    assert (await call_of(call_id)).ended_at is None


async def test_resolve_ends_human_ended_closes_the_room_and_notifies(client, seeded, room):
    """Covers: LKH-11"""
    call_id, esc_id = await waiting_call(client, seeded)
    await join_specialist(client, esc_id)
    await media_room.participant_connected(call_id, "spec-sam1")
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H,
                          json={"disposition": "resolved_by_human", "resolution_note": "Refiled the claim and confirmed by phone."})
    assert r.status_code == 200, r.text
    call = await call_of(call_id)
    assert call.end_reason == "human_ended" and call.outcome == "escalated" and call.status == "ended"
    assert room.messages("end")[-1] == {"type": "end", "reason": "human_ended"}
    assert room.closed == [f"lk-{call_id}"]
    assert (await esc_of(call_id)).status == "resolved"


# ------------------------------------------------------------------ LKH-14
def test_importing_the_app_never_loads_the_livekit_sdk():
    """Covers: LKH-14"""
    code = "import sys, voiceai.main, voiceai.media_room, voiceai.voice.pipeline, voiceai.voice.livekit_transport, voiceai.voice.scribe;" \
           "bad=[m for m in sys.modules if m=='livekit' or m.startswith('livekit.')]; print(bad); sys.exit(1 if bad else 0)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1])
    assert out.returncode == 0, out.stdout + out.stderr


def test_the_default_backend_is_never_built_in_tests(room):
    """Covers: LKH-14"""
    assert isinstance(media_room.backend(), FakeBackend)


# ------------------------------------------------------------------ LKH-19
async def test_existing_database_gains_the_room_columns(tmp_path):
    """Covers: LKH-19"""
    from sqlalchemy import inspect, text

    from voiceai import db

    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    await db.init_db()
    async with db.engine().begin() as conn:
        tables_before = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        await conn.exec_driver_sql("ALTER TABLE calls DROP COLUMN media_room")
        await conn.exec_driver_sql("ALTER TABLE escalations DROP COLUMN voice_state")
        await conn.exec_driver_sql("ALTER TABLE escalations DROP COLUMN voice_joined_at")
    await db.init_db()
    async with db.engine().begin() as conn:
        calls = await conn.run_sync(lambda c: {x["name"]: x for x in inspect(c).get_columns("calls")})
        escs = await conn.run_sync(lambda c: {x["name"]: x for x in inspect(c).get_columns("escalations")})
        assert "media_room" in calls and {"voice_state", "voice_joined_at"} <= set(escs)
        assert calls["media_room"]["nullable"] and escs["voice_state"]["nullable"]
        assert await conn.run_sync(lambda c: set(inspect(c).get_table_names())) == tables_before  # the table count is the same
        assert (await conn.execute(text("SELECT count(*) FROM calls WHERE media_room IS NOT NULL"))).scalar() == 0
    await db.engine().dispose()
