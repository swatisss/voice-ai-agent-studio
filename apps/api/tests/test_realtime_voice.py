"""The realtime speech-to-speech pipeline: bridge rules against a scripted provider connection (no network).

Covers: RV-02, RV-03, RV-04, RV-05, RV-06, RV-07, RV-08, RV-09, RV-10, RV-11, RV-12, RV-13
"""
from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace
from typing import Any

import pytest
from pipecat.frames.frames import OutputTransportMessageUrgentFrame, TTSAudioRawFrame
from sqlalchemy import select
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voiceai.db import sessionmaker
from voiceai.live import LiveControls
from voiceai.llm.gateway import gateway, reset_gateway
from voiceai.models import CallEvent, Escalation
from voiceai.runtime import endings, escalation
from voiceai.runtime.prompt import system_prompt
from voiceai.runtime.session import AgentSession, create_call
from voiceai.runtime.tools import all_schemas
from voiceai.voice import realtime as rt
from voiceai.voice.turn_detection import TurnSettings

H = {"X-Tenant-Id": "evergreen-care"}
AUDIO = base64.b64encode(b"\x01\x02" * 480).decode()


class FakeConn:
    """A scripted Realtime service: answers response.cancel and response.create the way the real one does."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.inbox: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.active: str | None = None
        self.counter = 0
        self.reply = "Okay, one moment."
        self.reply_usage: dict[str, Any] = {}

    def feed(self, event: dict[str, Any] | None) -> None:
        self.inbox.put_nowait(event)

    async def recv(self) -> dict[str, Any] | None:
        return await self.inbox.get()

    async def close(self) -> None:
        self.feed(None)

    async def send(self, event: dict[str, Any]) -> None:
        self.sent.append(event)
        if event["type"] == "response.cancel" and self.active:
            self.finish(self.active, "cancelled")
        elif event["type"] == "response.create":
            response = event.get("response") or {}
            exact = (response.get("metadata") or {}).get("kind") == "exact"
            if exact:
                self.speak(response["metadata"]["text"], exact=True)
            elif self.active is None and self.reply is not None:
                self.speak(self.reply)

    def speak(self, text: str, exact: bool = False) -> str:
        self.counter += 1
        rid = f"resp{self.counter}"
        self.active = rid
        meta: dict[str, Any] | None = {"kind": "exact", "text": text} if exact else None
        self.feed({"type": "response.created", "response": {"id": rid, **({"metadata": meta} if meta else {})}})
        self.feed({"type": "response.output_audio.delta", "response_id": rid, "item_id": f"item{rid}", "delta": AUDIO})
        self.feed({"type": "response.output_audio_transcript.delta", "response_id": rid, "delta": text})
        self.finish(rid, "completed", usage=self.reply_usage)
        return rid

    def start_reply(self, text: str) -> str:
        """A model reply that is still being produced (no `response.done` yet)."""
        self.counter += 1
        rid = f"resp{self.counter}"
        self.active = rid
        self.feed({"type": "response.created", "response": {"id": rid}})
        self.feed({"type": "response.output_audio.delta", "response_id": rid, "item_id": f"item{rid}", "delta": AUDIO})
        self.feed({"type": "response.output_audio_transcript.delta", "response_id": rid, "delta": text})
        return rid

    def finish(self, rid: str, status: str, usage: dict[str, Any] | None = None, output: list | None = None) -> None:
        self.active = None
        self.feed({"type": "response.done", "response": {"id": rid, "status": status, "usage": usage or {}, "output": output or []}})

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.sent if e["type"] == kind]

    def exact_texts(self) -> list[str]:
        return [e["response"]["metadata"]["text"] for e in self.of("response.create") if (e.get("response") or {}).get("metadata")]


class Bridge(rt.RealtimeBridge):
    FINISH_WAIT_S = 0.2
    FINISH_GRACE_S = 0.01

    def __init__(self, *a: Any, **k: Any) -> None:  # noqa: ANN401
        super().__init__(*a, **k)
        self.floor.RUN_WATCHDOG = False
        self.floor.WELCOME_GRACE_S = 0.02
        self.pushed: list = []
        self.interrupted = 0

    async def push_frame(self, frame, direction=None) -> None:  # type: ignore[override]  # noqa: ANN001
        self.pushed.append(frame)

    async def broadcast_interruption(self) -> None:  # type: ignore[override]
        self.interrupted += 1


async def pump(bridge: Bridge, rounds: int = 3) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0.02)
        await bridge.settle()


async def build(seeded, agent: str = "claims", turn: dict | None = None):  # noqa: ANN001, ANN202
    async with sessionmaker()() as s:
        call = await create_call(s, "evergreen-care", seeded[agent]["agent_id"], "voice")
        await s.commit()
    session = await AgentSession.open(call.id, "evergreen-care")
    if turn:
        session.live["turn_detection"] = turn
    conn = FakeConn()
    ended: list[str] = []

    async def on_end(reason: str) -> None:
        ended.append(reason)
        await session.end(reason)

    controls = LiveControls(turn=session.turn_settings())
    bridge = Bridge(session, controls, conn, on_end)
    await bridge.start()
    return bridge, conn, session, ended


async def finish_welcome(bridge: Bridge, conn: FakeConn) -> None:
    await bridge.greet()
    await pump(bridge)
    bridge.on_bot_started()
    await bridge.on_bot_stopped()
    await asyncio.sleep(0.1)
    await pump(bridge)
    assert not bridge.controls.welcoming


async def events(session: AgentSession) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == session.call_id).order_by(CallEvent.seq))).all())


def user_says(conn: FakeConn, text: str) -> None:
    conn.feed({"type": "input_audio_buffer.speech_started"})
    conn.feed({"type": "input_audio_buffer.speech_stopped"})
    conn.feed({"type": "conversation.item.input_audio_transcription.completed", "transcript": text})


async def test_session_carries_the_shared_prompt_and_tools(client, seeded):
    """Covers: RV-04"""
    bridge, conn, session, _ = await build(seeded)
    payload = conn.of("session.update")[0]["session"]
    base = system_prompt(session.config, session.tenant_name, None, session.started_at, session.context)
    assert payload["instructions"].startswith(base) and "You are speaking on a live phone or voice call" in payload["instructions"]
    assert "One moment while I check that" in payload["instructions"]  # voice_filler is on
    expected = all_schemas(session.config["tools"])
    assert [t["name"] for t in payload["tools"]] == [e["function"]["name"] for e in expected]
    assert [t["parameters"] for t in payload["tools"]] == [e["function"]["parameters"] for e in expected]
    assert {"search_knowledge", "escalate_to_human", "end_call", "start_claim", "get_claim_requirements"} <= {t["name"] for t in payload["tools"]}
    assert payload["tool_choice"] == "auto" and payload["output_modalities"] == ["audio"]
    audio = payload["audio"]
    assert audio["input"]["format"] == {"type": "audio/pcm", "rate": 24000} and audio["output"]["voice"] == gateway().speech_voices()[0]
    assert audio["input"]["transcription"]["model"] == gateway().speech_params()["transcription_model"]
    await bridge.shutdown()


async def test_function_calls_go_through_the_verification_gate(client, seeded):
    """Covers: RV-05"""
    bridge, conn, session, _ = await build(seeded)
    await finish_welcome(bridge, conn)

    def call(n: int, name: str, args: dict) -> None:
        conn.feed({"type": "response.function_call_arguments.done", "response_id": "rc", "call_id": f"c{n}", "name": name, "arguments": json.dumps(args)})

    call(1, "get_claim_status", {"claim_id": "C-20931"})
    await pump(bridge)
    outputs = {e["item"]["call_id"]: json.loads(e["item"]["output"]) for e in conn.of("conversation.item.create")}
    assert "identity_not_verified" in json.dumps(outputs["c1"])
    updates_before = len(conn.of("session.update"))
    call(2, "verify_member", {"member_id": "482913", "date_of_birth": "1986-04-12"})
    await pump(bridge)
    assert session.state.verified_member_ref == "EVG-482913" and len(conn.of("session.update")) == updates_before + 1  # prompt refreshed
    assert "EVG-482913" in conn.of("session.update")[-1]["session"]["instructions"]
    call(3, "get_claim_status", {"claim_id": "C-20931"})
    call(4, "get_member_claims", {})
    call(5, "get_member_policies", {})
    await pump(bridge)
    outputs = {e["item"]["call_id"]: json.loads(e["item"]["output"]) for e in conn.of("conversation.item.create")}
    assert outputs["c3"]["claim_id"] == "C-20931" and outputs["c4"]["claims"] and outputs["c5"] == {"error": "tool_round_limit"}
    kinds = [(e.kind, (e.data or {}).get("name")) for e in await events(session) if e.kind in ("tool_call", "tool_result")]
    assert kinds[:4] == [("tool_call", "get_claim_status"), ("tool_result", "get_claim_status"), ("tool_call", "verify_member"), ("tool_result", "verify_member")]
    conn.finish("rc", "completed", output=[{"type": "function_call", "call_id": "c1"}])  # the turn's tools are done: the model answers
    conn.of("response.create")  # the follow-up reply is requested once tools finished
    await pump(bridge)
    assert any((e.get("response") or {}).get("metadata") is None for e in conn.of("response.create")[1:])
    await bridge.shutdown()


async def test_transcripts_and_replies_are_stored_in_order(client, seeded):
    """Covers: RV-06, RV-12"""
    bridge, conn, session, _ = await build(seeded)
    await finish_welcome(bridge, conn)
    conn.reply = "Claim C-20931 was paid."
    conn.reply_usage = {"input_tokens": 1000, "output_tokens": 500, "input_token_details": {"audio_tokens": 800}, "output_token_details": {"audio_tokens": 400}}
    user_says(conn, "What happened with my claim?")
    await pump(bridge)
    # the caller's turn makes the service reply by itself (server turn detection); simulate its reply
    conn.speak("Claim C-20931 was paid.")
    await pump(bridge)
    evs = [e for e in await events(session) if e.kind in ("user", "assistant")]
    assert [e.kind for e in evs][-2:] == ["user", "assistant"]
    assert evs[-2].text == "What happened with my claim?" and evs[-1].text == "Claim C-20931 was paid."
    assert evs[-1].data["latency_ms"] is not None and session.state.turns == 1
    price = gateway().models[gateway().speech_ref()]
    expected = (200 * price["input"] + 100 * price["output"] + 800 * price["audio_input"] + 400 * price["audio_output"]) / 1e6
    assert session.state.tokens_in == 1000 and session.state.tokens_out == 500 and session.state.cost_usd == pytest.approx(expected)
    audio = [f for f in bridge.pushed if isinstance(f, TTSAudioRawFrame)]
    assert audio and audio[0].sample_rate == 24000 and len(audio[0].audio) == 960  # streamed as it arrives

    conn.reply_usage = {}
    user_says(conn, "And the other one?")
    await pump(bridge)
    conn.counter += 1
    rid = "cut"
    conn.feed({"type": "response.created", "response": {"id": rid}})
    conn.feed({"type": "response.output_audio.delta", "response_id": rid, "item_id": "itemcut", "delta": AUDIO})
    conn.feed({"type": "response.output_audio_transcript.delta", "response_id": rid, "delta": "The second claim is"})
    await pump(bridge)
    conn.active = rid
    conn.feed({"type": "input_audio_buffer.speech_started"})  # the caller barges in
    await pump(bridge)
    assert bridge.interrupted == 1 and conn.of("response.cancel") and conn.of("conversation.item.truncate")
    last = [e for e in await events(session) if e.kind == "assistant"][-1]
    assert last.text == "The second claim is [interrupted]"
    await bridge.shutdown()


async def test_welcome_is_exact_once_and_protected(client, seeded):
    """Covers: RV-07"""
    bridge, conn, session, _ = await build(seeded)
    await bridge.greet()
    await bridge.greet()  # a repeated connect signal does not speak it again
    await pump(bridge)
    greeting = session.config["persona"]["greeting"] + " " + session.config["persona"]["disclosure"]
    assert conn.exact_texts() == [greeting] and len(conn.of("response.create")) == 1
    assert rt.EXACT_PREFIX + greeting == conn.of("response.create")[0]["response"]["instructions"]
    ready = [f for f in bridge.pushed if isinstance(f, OutputTransportMessageUrgentFrame)]
    assert len(ready) == 1 and ready[0].message == {"type": "ready"}
    protected = conn.of("session.update")[-1]["session"]["audio"]["input"]["turn_detection"]
    assert protected["interrupt_response"] is False and protected["create_response"] is False
    bridge.on_bot_started()
    user_says(conn, "uh hello?")  # noise, or the agent's own voice leaking in
    await pump(bridge)
    assert bridge.interrupted == 0 and not conn.of("response.cancel") and session.state.turns == 0
    await bridge.on_bot_stopped()
    await asyncio.sleep(0.1)
    await pump(bridge)
    free = conn.of("session.update")[-1]["session"]["audio"]["input"]["turn_detection"]
    assert free["interrupt_response"] is True and free["create_response"] is True
    user_says(conn, "Hi, I have a question.")
    await pump(bridge)
    assert session.state.turns == 1
    await bridge.shutdown()


async def test_fixed_lines_replace_the_models_reply(client, seeded):
    """Covers: RV-08"""
    bridge, conn, session, ended = await build(seeded)
    await finish_welcome(bridge, conn)
    conn.reply = None  # type: ignore[assignment]
    conn.start_reply("Let me look that up for you.")  # the model already started answering
    await pump(bridge)
    user_says(conn, "No, that's all, thank you.")
    await pump(bridge, 4)
    assert bridge.interrupted >= 1 and endings.GOODBYE in conn.exact_texts()
    assert ended == ["farewell"] and session.state.ended
    assert [e.text for e in await events(session) if e.kind == "assistant"][-1] == endings.GOODBYE
    closing = conn.of("session.update")[-1]["session"]["audio"]["input"]["turn_detection"]
    assert closing["interrupt_response"] is False and closing["create_response"] is False  # nothing may cut the goodbye short
    await bridge.shutdown()

    bridge, conn, session, ended = await build(seeded)
    await finish_welcome(bridge, conn)
    conn.reply = None  # type: ignore[assignment]
    user_says(conn, "I have chest pain")
    await pump(bridge, 4)
    assert escalation.SAFETY_MESSAGE in conn.exact_texts() and ended == ["handoff"]
    async with sessionmaker()() as s:
        esc = (await s.scalars(select(Escalation).where(Escalation.call_id == session.call_id))).all()
    assert len(esc) == 1 and esc[0].reason_category == "safety"
    await bridge.shutdown()


async def test_escalation_speaks_the_handoff_verbatim_and_ends(client, seeded):
    """Covers: RV-09"""
    bridge, conn, session, ended = await build(seeded)
    await finish_welcome(bridge, conn)
    args = {"reason_category": "policy_required", "reason_detail": "Caller wants to appeal"}
    for n in (1, 2):  # a second call changes nothing (ES-08)
        conn.feed({"type": "response.function_call_arguments.done", "response_id": "re", "call_id": f"e{n}", "name": "escalate_to_human", "arguments": json.dumps(args)})
    await pump(bridge)
    conn.finish("re", "completed", output=[{"type": "function_call", "call_id": "e1"}])
    await pump(bridge, 4)
    handoff = session.config["policy"]["handoff_message"]
    assert handoff in conn.exact_texts() and ended == ["handoff"]
    async with sessionmaker()() as s:
        assert len((await s.scalars(select(Escalation).where(Escalation.call_id == session.call_id))).all()) == 1
    await bridge.shutdown()


def test_turn_detection_follows_the_agent_settings():
    """Covers: RV-10"""
    vad = TurnSettings(mode="vad", min_silence_ms=700, allow_interruptions=False, evaluator="llm", max_extra_wait_ms=3000)
    assert rt.turn_detection(vad) == {"type": "server_vad", "silence_duration_ms": 700, "prefix_padding_ms": 300, "create_response": False, "interrupt_response": False}
    assert rt.turn_detection(TurnSettings(mode="vad", min_silence_ms=700, allow_interruptions=False)) == rt.turn_detection(vad)  # evaluator and extra wait are ignored
    semantic = rt.turn_detection(TurnSettings(mode="semantic", allow_interruptions=True))
    assert semantic == {"type": "semantic_vad", "eagerness": "auto", "create_response": True, "interrupt_response": True}
    assert rt.turn_detection(TurnSettings(mode="vad", min_silence_ms=400), welcoming=True)["interrupt_response"] is False


async def test_without_interruptions_the_bridge_asks_for_each_reply(client, seeded):
    """Covers: RV-10"""
    bridge, conn, session, _ = await build(seeded, turn={"allow_interruptions": False})
    await finish_welcome(bridge, conn)
    conn.reply = "Sure."
    before = len(conn.of("response.create"))
    conn.feed({"type": "input_audio_buffer.speech_started"})
    conn.feed({"type": "input_audio_buffer.speech_stopped"})
    await pump(bridge)
    assert len(conn.of("response.create")) == before + 1 and bridge.interrupted == 0
    conn.reply = None  # type: ignore[assignment]
    conn.speak("Still talking.")
    conn.active = None
    await bridge.shutdown()


async def test_silence_and_length_clocks(client, seeded):
    """Covers: RV-11"""
    bridge, conn, session, ended = await build(seeded)
    await finish_welcome(bridge, conn)
    t0 = bridge.floor.clock.silent_since  # the silence began when the welcome ended
    await bridge.floor.tick(t0 + 5)
    assert endings.REMINDER_LINE not in conn.exact_texts()
    await bridge.floor.tick(t0 + 11)
    await bridge.floor.tick(t0 + 12)  # only once
    await pump(bridge)
    assert conn.exact_texts().count(endings.REMINDER_LINE) == 1 and not ended
    conn.reply = None  # type: ignore[assignment]
    rid = conn.start_reply("Let me check.")  # the agent is producing a reply
    await pump(bridge)
    await bridge.floor.tick(t0 + 400)  # nobody is silent while the agent speaks or a tool runs
    assert not ended and endings.IDLE_LINE not in conn.exact_texts()
    conn.finish(rid, "completed")
    await pump(bridge)
    t1 = bridge.floor.clock.silent_since  # a fresh silence after the reply
    await bridge.floor.tick(t1 + 31)
    await pump(bridge, 4)
    assert endings.IDLE_LINE in conn.exact_texts() and ended == ["idle"]
    await bridge.shutdown()

    bridge, conn, session, ended = await build(seeded)
    await finish_welcome(bridge, conn)
    await bridge.floor.tick(bridge.floor.clock.started + session.config["policy"]["max_call_seconds"] + 1)
    await pump(bridge, 4)
    assert endings.MAX_DURATION_LINE in conn.exact_texts() and ended == ["max_duration"]
    await bridge.shutdown()


async def test_losing_the_provider_ends_the_call_with_an_escalation(client, seeded):
    """Covers: RV-13"""
    bridge, conn, session, ended = await build(seeded)
    await finish_welcome(bridge, conn)
    conn.feed(None)  # the provider closed the socket
    for _ in range(250):  # the reader task notices it and escalates (a database write): wait for that, up to 5 s
        if ended:
            break
        await pump(bridge, 1)
    assert ended == ["error"] and session.state.escalated
    async with sessionmaker()() as s:
        esc = (await s.scalars(select(Escalation).where(Escalation.call_id == session.call_id))).one()
    assert esc.reason_category == "other"
    await bridge.shutdown()


# ---------------------------------------------------------------- pipeline selection over the voice socket
@pytest.fixture
def voice_app(app, tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'rv.db').as_posix()}")
    monkeypatch.setenv("AUTO_SEED", "1")
    from voiceai.config import get_settings

    def keys(openai: str = "", deepgram: str = "") -> None:
        monkeypatch.setenv("OPENAI_API_KEY", openai)
        monkeypatch.setenv("DEEPGRAM_API_KEY", deepgram)
        get_settings.cache_clear()
        reset_gateway()

    keys()
    with TestClient(app) as c:
        agents = {a["name"]: a["id"] for a in c.get("/api/agents", headers=H).json()["items"]}
        yield SimpleNamespace(client=c, agents=agents, keys=keys)
    get_settings.cache_clear()
    reset_gateway()


def start_voice(vapp, agent: str) -> str:  # noqa: ANN001
    """Create a voice call; returns the call id, or the refusal reason of POST /api/calls (ADM-02)."""
    r = vapp.client.post("/api/calls", headers=H, json={"agent_id": vapp.agents[agent], "channel": "voice"})
    return r.json()["call_id"] if r.status_code == 200 else r.json()["error"]


def connect(vapp, call_id: str) -> int | None:  # noqa: ANN001
    try:
        with vapp.client.websocket_connect(f"/api/voice/{call_id}?tenant=evergreen-care") as ws:
            ws.receive_text()
    except WebSocketDisconnect as exc:
        return exc.code
    return None


def test_the_call_picks_its_pipeline_and_its_key(voice_app, monkeypatch):
    """Covers: RV-02, RV-03, RV-13"""
    from voiceai.voice import pipeline

    ran: list[str] = []

    async def fake_realtime(websocket, session, controls, connector, phone=None):  # noqa: ANN001, ANN202
        ran.append("realtime")
        await websocket.close(code=1000)

    async def fake_cascade(websocket, session, key, controls=None, phone=None):  # noqa: ANN001, ANN202
        ran.append("cascade")
        await websocket.close(code=1000)

    monkeypatch.setattr(pipeline, "run_realtime", fake_realtime)
    monkeypatch.setattr(pipeline, "run", fake_cascade)
    voice_app.keys(openai="sk-test")  # OpenAI only: the realtime agent connects without any Deepgram key
    assert connect(voice_app, start_voice(voice_app, "Insurance Claims Agent")) == 1000 and ran == ["realtime"]
    assert start_voice(voice_app, "Customer Care Agent") == "voice_unavailable"  # the cascade still needs Deepgram (ADM-02)
    voice_app.keys(deepgram="dg-test")
    assert connect(voice_app, start_voice(voice_app, "Customer Care Agent")) == 1000 and ran == ["realtime", "cascade"]
    assert start_voice(voice_app, "Insurance Claims Agent") == "voice_unavailable"  # no OpenAI key: refused up front
    voice_app.keys(openai="sk-test", deepgram="dg-test")
    planned = start_voice(voice_app, "Insurance Claims Agent")
    voice_app.keys(deepgram="dg-test")  # RV-03: the OpenAI key is gone when the socket opens
    assert connect(voice_app, planned) == 4500
    assert voice_app.client.get("/healthz").json()["status"] == "ok"

    async def unavailable(websocket, session, controls, connector, phone=None):  # noqa: ANN001, ANN202
        raise rt.ProviderUnavailable("cannot reach the service")

    monkeypatch.setattr(pipeline, "run_realtime", unavailable)
    voice_app.keys(openai="sk-test")
    assert connect(voice_app, start_voice(voice_app, "Insurance Claims Agent")) == 4500  # RV-13: the provider socket cannot be opened


def test_realtime_pipeline_has_no_deepgram_services(monkeypatch):
    """Covers: RV-02"""
    from voiceai.voice import pipeline as pipeline_module
    from voiceai.voice.pipeline import build_realtime

    def forbidden(*a: Any, **k: Any) -> None:  # noqa: ANN401
        raise AssertionError("the realtime pipeline must not construct a Deepgram service")

    monkeypatch.setattr(pipeline_module, "DeepgramSTTService", forbidden)
    monkeypatch.setattr(pipeline_module, "DeepgramTTSService", forbidden)

    class FakeWS:
        headers: dict = {}

    session = SimpleNamespace(config={"policy": {}}, history=[], turn_settings=lambda: TurnSettings())
    controls = LiveControls(turn=TurnSettings())
    task, transport, bridge, serializer = build_realtime(FakeWS(), session, controls, FakeConn())  # type: ignore[arg-type]
    assert task is not None and isinstance(bridge, rt.RealtimeBridge) and serializer.end_reason == "hangup"
