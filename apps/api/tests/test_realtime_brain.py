"""The realtime brain: one OpenAI Realtime model inside the Pipecat, LiveKit and Simli pipeline.

Spec: /architecture/realtime-brain.md
Covers: RB-01, RB-02, RB-03, RB-04, RB-05, RB-06, RB-07, RB-08, RB-09, RB-10, RB-11, RB-12, RB-13, RB-14

The real Pipecat OpenAI Realtime service, the real context aggregators and our gate, tap and brain
run against `tests/realtime_fake.py`, a fake server: no key, no network.
"""
from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from loguru import logger as loguru_logger

from tests.realtime_fake import FakeRealtime, Harness
from voiceai.core.config import Settings
from voiceai.core.db import sessionmaker
from voiceai.modules.conversation import api as calls_api
from voiceai.modules.conversation.contract import (
    GOODBYE, IDLE_LINE, MAX_DURATION_LINE, REMINDER_LINE, SAFETY_MESSAGE, call_events,
)
from voiceai.modules.conversation.session import AgentSession, create_call
from voiceai.modules.voice import realtime as rtm
from voiceai.modules.voice import room as room_mod
from voiceai.modules.voice.controls import LIVE, LiveControls
from voiceai.modules.voice.live_control import InProcessVoiceControl

KEY = "sk-realtime-test-key-do-not-leak-0123456789"
M = {"X-Tenant-Id": "evergreen-care"}
PRICES = {"input": 4.0, "output": 16.0, "input_audio": 32.0, "output_audio": 64.0}


# ---------------------------------------------------------------- harness
@pytest.fixture(autouse=True)
def _quick_closing(monkeypatch):  # noqa: ANN001, ANN202
    monkeypatch.setattr(rtm, "CLOSE_WAIT_S", 0.5)   # a closing wait bounded for tests, 10 s in production


@pytest.fixture
async def env(app, database, seeded, fake_llm, monkeypatch):  # noqa: ANN001, ANN201
    """A real session on a video call, a fake Realtime server, and the pipeline joined to them."""
    fake_llm(lambda *a: None)
    monkeypatch.setattr(rtm, "speech_model", lambda: rtm.SpeechModel("openai:gpt-realtime-2.1", "gpt-realtime-2.1", KEY, PRICES))
    async with sessionmaker()() as s:
        call = await create_call(s, "evergreen-care", seeded["care"]["agent_id"], "video")
        await s.commit()
    session = await AgentSession.open(call.id, "evergreen-care")
    fake = FakeRealtime()
    await fake.start()
    controls = LiveControls(turn=session.turn_settings())
    LIVE[call.id] = controls
    harness = Harness(session, fake, controls)
    await harness.start()
    await asyncio.wait_for(fake.updated.wait(), 5)
    ns = SimpleNamespace(call_id=call.id, session=session, fake=fake, controls=controls, h=harness, brain=harness.pieces.brain)
    yield ns
    LIVE.pop(call.id, None)
    await harness.stop()
    await fake.stop()


async def _welcomed(env) -> None:  # noqa: ANN001
    """Greet, let the welcome play, and end its protection so the caller can be heard."""
    await env.brain.greet()
    await env.fake.wait_for("response.create")
    await env.fake.agent_says("Welcome.", "r0", "a0")
    await asyncio.sleep(0.15)
    env.brain._end_welcome()  # noqa: SLF001


async def _events(env):  # noqa: ANN001, ANN202
    async with sessionmaker()() as s:
        return await call_events(s, "evergreen-care", env.call_id)


async def _tool_output(env) -> dict:  # noqa: ANN001
    """The next function_call_output the service sent to the model (the setup message items are skipped)."""
    def outputs() -> list[dict]:
        return [e["item"] for e in env.fake.of("conversation.item.create") if e["item"].get("type") == "function_call_output"]
    await _until(lambda: outputs())
    return outputs()[-1]


async def _until(cond, timeout: float = 3.0) -> None:  # noqa: ANN001
    async def poll() -> None:
        while not cond():
            await asyncio.sleep(0.02)
    await asyncio.wait_for(poll(), timeout)


# ---------------------------------------------------------------- RB-01: availability and choice
class _GW:
    def __init__(self, speech: bool) -> None:
        self.speech = speech

    def role_available(self, role: str) -> bool:
        return self.speech if role == "speech" else True


def _settings(monkeypatch, brain: str = "auto", speech: bool = True) -> None:  # noqa: ANN001
    s = Settings(_env_file=None, video_brain=brain, livekit_url="wss://t.livekit.cloud", livekit_api_key="K",
                 livekit_api_secret="a-test-secret-long-enough-for-hs256")
    monkeypatch.setattr(rtm, "get_settings", lambda: s)
    monkeypatch.setattr(room_mod, "get_settings", lambda: s)
    monkeypatch.setattr(rtm, "gateway", lambda: _GW(speech))


def test_the_brain_is_chosen_from_configuration_and_availability(monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-01"""
    _settings(monkeypatch, "auto", True)
    assert rtm.resolve_brain() == "realtime"
    _settings(monkeypatch, "realtime", True)
    assert rtm.resolve_brain() == "realtime"
    _settings(monkeypatch, "auto", False)                 # no usable model in the speech role (no key)
    assert rtm.resolve_brain() == "pipeline"
    _settings(monkeypatch, "realtime", False)             # asked for, not available: not an error
    assert rtm.resolve_brain() == "pipeline"
    _settings(monkeypatch, "pipeline", True)              # the switch always wins
    assert rtm.resolve_brain() == "pipeline"

    _settings(monkeypatch, "auto", True)                  # and the SDK being absent is the same quiet answer
    import builtins

    real_import = builtins.__import__

    def deny(name, *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
        if name.startswith("pipecat.services.openai.realtime"):
            raise ImportError("not installed")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", deny)
    assert rtm.resolve_brain() == "pipeline"


async def test_media_brain_is_reported_and_the_call_is_created_either_way(client, seeded, monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-01, RB-14"""
    started: list[tuple] = []
    monkeypatch.setattr(room_mod.LiveKitVideoRoom, "start_agent", lambda self, c, t, brain="pipeline": started.append(brain))
    monkeypatch.setattr(calls_api, "video_room", lambda: room_mod.LiveKitVideoRoom())
    monkeypatch.setattr(calls_api, "gateway", lambda: _GW(True))   # the vision role is usable
    agent_id = next(a["id"] for a in (await client.get("/api/agents", headers=M)).json()["items"] if a["published_version"])

    _settings(monkeypatch, "auto", True)
    r = await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})
    assert r.json()["media"]["brain"] == "realtime" and started[-1] == "realtime"
    assert KEY not in r.text                                   # RB-14

    _settings(monkeypatch, "auto", False)
    r = await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})
    body = r.json()
    assert body["media"]["brain"] == "pipeline" and started[-1] == "pipeline"
    assert "video_unavailable" not in body and body["media"]["room"].startswith("call-")


# ---------------------------------------------------------------- RB-02: the pipeline
def _names(task) -> list[str]:  # noqa: ANN001
    inner = next(p for p in task._pipeline._processors if type(p).__name__ == "Pipeline")  # noqa: SLF001
    return [type(p).__name__ for p in inner._processors]  # noqa: SLF001


async def test_the_realtime_pipeline_has_the_service_and_none_of_the_stages_it_replaces(env, monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-02"""
    from tests.test_avatar import StubAvatar
    from voiceai.modules.voice import frames, pipeline

    holder = frames.register("c-rb02")
    try:
        task, transport, _ = pipeline.build_room_realtime(
            env.session, "dg", "wss://x", "tok", "call-1", holder=holder, avatar=StubAvatar())
        names = _names(task)
        order = ["LiveKitInputTransport", "FrameTap", "RealtimeGate", "LLMUserAggregator", "RealtimeTap",
                 "OpenAIRealtimeLLMService", "RealtimeBrain", "StubAvatar", "LiveKitOutputTransport", "LLMAssistantAggregator"]
        assert [n for n in names if n in order] == order
        for gone in ("VADProcessor", "DeepgramSTTService", "TurnAggregator", "BrainProcessor", "DeepgramTTSService"):
            assert gone not in names
        assert transport._params.video_out_enabled and transport._params.audio_in_sample_rate == 24000  # noqa: SLF001

        plain, _, _ = pipeline.build_room_realtime(env.session, "dg", "wss://x", "tok", "call-1", holder=holder)
        assert "StubAvatar" not in _names(plain)
    finally:
        frames.release("c-rb02")


# ---------------------------------------------------------------- RB-03 / RB-04: the welcome and the exact lines
async def test_the_welcome_is_instructed_once_and_protected(env) -> None:  # noqa: ANN001
    """Covers: RB-03, RB-04"""
    await env.brain.greet()
    await env.brain.greet()                                    # a repeated join does not speak it again
    creates = await env.fake.wait_for("response.create")
    await asyncio.sleep(0.2)
    assert len(env.fake.of("response.create")) == 1
    greeting = env.session.history[0]["content"]
    assert creates[0]["response"]["instructions"] == rtm.SAY_EXACTLY + greeting      # exactly this text (RB-04)
    assert creates[0]["response"]["tool_choice"] == "none"
    first = next(e for e in await _events(env) if e.kind == "assistant")
    assert first.text == greeting and first.data.get("greeting") is True               # recorded exactly

    await env.h.mic()                                           # the caller speaks during the welcome ...
    await env.fake.caller_says("hello? anyone?")
    await asyncio.sleep(0.25)
    assert not env.fake.of("input_audio_buffer.append")        # ... the audio never reaches the model
    assert not any(m["role"] == "user" for m in env.session.history)    # ... and no turn is answered

    env.brain._end_welcome()  # noqa: SLF001
    await env.h.mic()
    await env.fake.wait_for("input_audio_buffer.append")       # once it is over the caller is heard


async def test_the_welcome_protection_has_a_safety_timeout(env, monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-03"""
    monkeypatch.setattr(rtm.RealtimeBrain, "WELCOME_MIN_TIMEOUT_S", 0.2)
    monkeypatch.setattr(rtm.RealtimeBrain, "WELCOME_SLOW_CHARS_PER_S", 10_000.0)
    await env.brain.greet()
    assert env.controls.welcoming
    await _until(lambda: not env.controls.welcoming, 2.0)     # the model never spoke; protection still ends


async def test_reminder_and_closing_lines_are_recorded_exactly_and_instructed(env) -> None:  # noqa: ANN001
    """Covers: RB-04, RB-09"""
    await _welcomed(env)
    env.brain._start_clocks()  # noqa: SLF001
    now = time.monotonic()
    env.brain._silent_since = now - 11                          # noqa: SLF001 - past the 10 s reminder, before the 30 s end
    await env.brain.check_clocks(now)
    creates = await env.fake.wait_for("response.create", 2)
    assert creates[-1]["response"]["instructions"] == rtm.SAY_EXACTLY + REMINDER_LINE
    assert any(e.kind == "assistant" and e.text == REMINDER_LINE and e.data.get("silence_reminder") for e in await _events(env))
    await env.brain.check_clocks(now)                           # once only
    await asyncio.sleep(0.1)
    assert len(env.fake.of("response.create")) == 2


# ---------------------------------------------------------------- RB-05: instructions, tools, the executor
async def test_the_session_has_our_instructions_tools_and_the_configured_model(env) -> None:  # noqa: ANN001
    """Covers: RB-05"""
    sent = env.fake.of("session.update")[0]["session"]
    assert sent["model"] == "gpt-realtime-2.1"                  # from configuration, never a literal in code
    assert "You are Ava" in sent["instructions"]                # the agent's system prompt ...
    assert "This is a live video call" in sent["instructions"]  # ... then the realtime addendum
    assert sent["instructions"].index("You are Ava") < sent["instructions"].index("This is a live video call")
    names = [t["name"] for t in sent["tools"]]
    assert {"search_knowledge", "escalate_to_human", "end_call", "look_at_camera"} <= set(names)
    assert "verify_member" in names                             # and the agent's own tools
    assert sent["audio"]["output"]["voice"] == "marin"

    # look_at_camera exists on a video call only (RT-10)
    voice = AgentSession(call=SimpleNamespace(id="x", tenant_id="evergreen-care", agent_id="a", channel="voice",
                                              is_eval=False, started_at=None), config=env.session.config, tenant_name="T")
    assert "look_at_camera" not in [s["function"]["name"] for s in voice.tool_schemas()]


async def test_a_tool_call_runs_through_the_executor_and_returns_to_the_model(env) -> None:  # noqa: ANN001
    """Covers: RB-05"""
    await _welcomed(env)
    await env.fake.caller_says("What is my deductible?")
    await env.fake.calls_tool("search_knowledge", {"query": "deductible"})
    out = await _tool_output(env)
    assert out["type"] == "function_call_output" and out["call_id"] == "c1"
    kinds = [(e.kind, (e.data or {}).get("name")) for e in await _events(env) if e.kind.startswith("tool")]
    assert kinds == [("tool_call", "search_knowledge"), ("tool_result", "search_knowledge")]   # in order


async def test_a_context_frame_never_reaches_the_model(env) -> None:  # noqa: ANN001
    """Covers: RB-05

    The service treats the first context frame it sees as the start of the conversation: it replays
    the context as a "previously saved conversation" message and asks for a response nobody wanted.
    The tap must stop one, whenever it arrives.
    """
    from pipecat.frames.frames import LLMContextFrame
    from pipecat.processors.aggregators.llm_context import LLMContext

    await _welcomed(env)
    before = len(env.fake.received)
    await env.h.pieces.user_aggregator.push_frame(LLMContextFrame(context=LLMContext(messages=[{"role": "user", "content": "hi"}])))
    await asyncio.sleep(0.4)
    stray = [e["type"] for e in env.fake.received[before:] if e["type"] in ("conversation.item.create", "response.create")]
    assert stray == []                                          # nothing replayed, nothing asked for

    # and the first tool call, with no context frame having come first, still gets its result back
    await env.fake.calls_tool("search_knowledge", {"query": "deductible"})
    out = await _tool_output(env)
    assert out["call_id"] == "c1"


async def test_the_identity_gate_still_holds_on_this_brain(env) -> None:  # noqa: ANN001
    """Covers: RB-05"""
    await _welcomed(env)
    await env.fake.calls_tool("get_member_claims", {"member_id": "EVG-482913"})   # before the caller is verified
    out = (await _tool_output(env))["output"]
    assert "verif" in out.lower()                               # refused, and the refusal went back to the model
    result = next(e for e in await _events(env) if e.kind == "tool_result")
    assert result.data["ok"] is False


# ---------------------------------------------------------------- RB-06: the safety screen
async def test_an_emergency_phrase_stops_the_reply_and_speaks_the_exact_message(env, monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-06"""
    audio = b"\x02\x00" * 4800                                  # 200 ms of rendered speech
    rendered: list[tuple] = []

    async def render(text, voice, key):  # noqa: ANN001, ANN202
        rendered.append((text, voice))
        return audio

    monkeypatch.setattr(rtm, "render_speech", render)
    await _welcomed(env)
    await env.fake.caller_says("I want to kill myself")
    await _until(lambda: env.h.ended)
    assert env.fake.of("response.cancel")                       # the reply in progress was stopped
    assert env.session.state.escalated
    assert rendered[0][0] == SAFETY_MESSAGE                     # exactly the fixed message, rendered by our own text-to-speech
    assert b"".join(env.h.out.audio).count(b"\x02\x00") >= 4800 # ... and pushed as audio, not spoken by the model
    assert any(e.kind == "assistant" and e.text == SAFETY_MESSAGE and e.data.get("safety") for e in await _events(env))
    assert len(env.fake.of("response.create")) == 1             # only the welcome: the model was not asked to say it
    assert env.h.ended == ["handoff"]


async def test_if_the_message_cannot_be_rendered_the_model_is_told_to_say_it(env, monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-06"""
    async def nothing(*a):  # noqa: ANN002, ANN202
        return None

    monkeypatch.setattr(rtm, "render_speech", nothing)
    await _welcomed(env)
    await env.fake.caller_says("I am thinking of suicide")
    creates = await env.fake.wait_for("response.create", 2)
    assert creates[-1]["response"]["instructions"] == rtm.SAY_EXACTLY + SAFETY_MESSAGE
    assert any(e.kind == "assistant" and e.text == SAFETY_MESSAGE for e in await _events(env))   # still recorded and shown


async def test_rendering_speech_returns_audio_or_none(monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-06"""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        return httpx.Response(200, content=b"\x01\x00" * 100)

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert await rtm.render_speech("hi", "aura-2-thalia-en", "dg-key") == b"\x01\x00" * 100
    assert "model=aura-2-thalia-en" in seen["url"] and "sample_rate=24000" in seen["url"] and seen["auth"] == "Token dg-key"
    assert await rtm.render_speech("hi", "aura-2-thalia-en", "") is None             # no key
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(500)), **kw))
    assert await rtm.render_speech("hi", "aura-2-thalia-en", "dg-key") is None       # a vendor error is not an exception


# ---------------------------------------------------------------- RB-07: turn detection
def test_turn_settings_map_onto_the_models_own_detector() -> None:
    """Covers: RB-07"""
    from voiceai.modules.voice.turn_detection import TurnSettings

    vad = rtm.turn_detection_for(TurnSettings.from_dict({"mode": "vad", "min_silence_ms": 500}))
    assert vad.type == "server_vad" and vad.silence_duration_ms == 500 and vad.interrupt_response is True
    sem = rtm.turn_detection_for(TurnSettings.from_dict({"mode": "semantic"}))
    assert sem.type == "semantic_vad"
    no_barge = rtm.turn_detection_for(TurnSettings.from_dict({"mode": "vad", "allow_interruptions": False}))
    assert no_barge.interrupt_response is False


async def test_a_live_turn_detection_change_updates_the_session(env) -> None:  # noqa: ANN001
    """Covers: RB-07"""
    before = len(env.fake.of("session.update"))
    ok = InProcessVoiceControl().set_turn(env.call_id, {"mode": "vad", "min_silence_ms": 400, "max_extra_wait_ms": 1500})
    assert ok
    await _until(lambda: len(env.fake.of("session.update")) > before)
    td = env.fake.of("session.update")[-1]["session"]["audio"]["input"]["turn_detection"]
    assert td["type"] == "server_vad" and td["silence_duration_ms"] == 400
    assert not env.h.ended                                      # and the call continues


# ---------------------------------------------------------------- RB-08: transcripts
async def test_transcripts_become_the_same_call_events_with_latency(env) -> None:  # noqa: ANN001
    """Covers: RB-08"""
    await _welcomed(env)
    await env.fake.caller_says("What is my deductible?")
    await asyncio.sleep(0.1)
    await env.fake.agent_says("It is five hundred dollars.", "r1", "a1")
    await _until(lambda: any(m.get("content") == "It is five hundred dollars." for m in env.session.history))
    await asyncio.sleep(0.1)
    evs = [e for e in await _events(env) if e.kind in ("user", "assistant")]
    assert [(e.kind, e.text) for e in evs][-2:] == [("user", "What is my deductible?"), ("assistant", "It is five hundred dollars.")]
    assert isinstance(evs[-1].data.get("latency_ms"), int)      # time from the end of the caller's speech to the first audio
    assert env.session.state.turns == 1


# ---------------------------------------------------------------- RB-09: the clocks
async def test_silence_ends_the_call_and_neither_clock_runs_during_the_welcome(env) -> None:  # noqa: ANN001
    """Covers: RB-09"""
    env.brain._start_clocks()  # noqa: SLF001
    now = time.monotonic()
    env.controls.welcoming = True
    env.brain._silent_since = now - 999                         # noqa: SLF001
    await env.brain.check_clocks(now)
    assert not env.h.ended and not env.fake.of("response.create")      # not during the welcome

    env.controls.welcoming = False
    env.brain._bot_speaking = True                              # noqa: SLF001
    await env.brain.check_clocks(now)
    assert not env.h.ended and not env.fake.of("response.create")      # nor while the agent speaks
    env.brain._bot_speaking = False                             # noqa: SLF001

    await env.brain.check_clocks(now)                           # 999 s of silence
    creates = await env.fake.wait_for("response.create")
    assert creates[-1]["response"]["instructions"] == rtm.SAY_EXACTLY + IDLE_LINE
    assert env.h.ended == ["idle"]


async def test_the_call_clock_ends_the_call_at_the_maximum_duration(env) -> None:  # noqa: ANN001
    """Covers: RB-09"""
    env.brain._start_clocks()  # noqa: SLF001
    env.brain._call_started = time.monotonic() - 99_999         # noqa: SLF001
    await env.brain.check_clocks()
    creates = await env.fake.wait_for("response.create")
    assert creates[-1]["response"]["instructions"] == rtm.SAY_EXACTLY + MAX_DURATION_LINE
    assert env.h.ended == ["max_duration"]


# ---------------------------------------------------------------- RB-10: persona
async def test_a_persona_switch_changes_the_style_and_never_the_voice(env) -> None:  # noqa: ANN001
    """Covers: RB-10"""
    await _welcomed(env)
    creates_before = len(env.fake.of("response.create"))
    updates = len(env.fake.of("session.update"))
    await env.session.switch_persona({**env.session.config["persona"], "name": "Zed", "style": "Brisk and formal.", "voice": "aura-2-other"})
    await env.controls.on_voice("aura-2-other", 1.4)            # what PATCH /live calls
    await _until(lambda: len(env.fake.of("session.update")) > updates)
    sent = env.fake.of("session.update")[-1]["session"]
    assert "Zed" in sent["instructions"] and "Brisk and formal." in sent["instructions"]
    assert sent["audio"]["output"]["voice"] == "marin"          # the voice does not change
    assert any(e.kind == "system" and "Persona switched to Zed" in (e.text or "") for e in await _events(env))
    await asyncio.sleep(0.1)
    assert len(env.fake.of("response.create")) == creates_before       # the greeting is not repeated


# ---------------------------------------------------------------- RB-11: ending
async def test_end_call_lets_the_goodbye_finish_then_ends_once(env) -> None:  # noqa: ANN001
    """Covers: RB-11"""
    await _welcomed(env)
    await env.fake.caller_says("That is everything, thanks.")
    await env.fake.calls_tool("end_call", {"summary": "answered the deductible question"})
    await _tool_output(env)
    assert not env.h.ended                                      # the goodbye has not been spoken yet
    await env.fake.agent_says("You are welcome. Goodbye!", "r2", "a2")
    await _until(lambda: env.h.ended)
    assert env.h.ended == ["end_call"]


async def test_escalation_ends_with_handoff_after_the_handoff_line(env) -> None:  # noqa: ANN001
    """Covers: RB-11"""
    await _welcomed(env)
    await env.fake.calls_tool("escalate_to_human", {"reason_category": "complaint", "reason_detail": "wants a person"})
    out = (await _tool_output(env))["output"]
    assert "escalated" in out
    assert env.session.state.escalated and not env.h.ended
    await env.fake.agent_says("I'm connecting you with a specialist.", "r2", "a2")
    await _until(lambda: env.h.ended)
    assert env.h.ended == ["handoff"]


async def test_a_farewell_ends_the_call_after_the_reply(env) -> None:  # noqa: ANN001
    """Covers: RB-11"""
    await _welcomed(env)
    await env.fake.caller_says("No, that's all, goodbye")
    await asyncio.sleep(0.2)
    assert not env.h.ended
    await env.fake.agent_says("Take care!", "r2", "a2")
    await _until(lambda: env.h.ended)
    assert env.h.ended == ["farewell"]


async def test_an_ending_with_no_spoken_reply_is_closed_with_our_own_line(env, monkeypatch) -> None:  # noqa: ANN001
    """Covers: RB-11"""
    monkeypatch.setattr(rtm, "END_DEADLINE_S", 0.2)
    await _welcomed(env)
    await env.fake.calls_tool("end_call", {"summary": "done"})
    await _until(lambda: any(
        (e.get("response") or {}).get("instructions") == rtm.SAY_EXACTLY + GOODBYE for e in env.fake.of("response.create")))
    await _until(lambda: env.h.ended)
    assert env.h.ended == ["end_call"]


# ---------------------------------------------------------------- RB-12: cost
def test_usage_is_priced_with_audio_and_text_separately() -> None:
    """Covers: RB-12"""
    # 100 text in, 500 audio in, 100 text out, 300 audio out
    cost = rtm.usage_cost(PRICES, 600, 400, 500, 300)
    assert cost == pytest.approx((100 * 4 + 100 * 16 + 500 * 32 + 300 * 64) / 1e6)
    assert rtm.usage_cost({}, 600, 400, 500, 300) == 0


async def test_a_responses_usage_is_added_to_the_call(env) -> None:  # noqa: ANN001
    """Covers: RB-12"""
    await _welcomed(env)                                        # the welcome's response reports 600 in / 400 out
    await env.fake.caller_says("hello")
    await env.fake.agent_says("Hi there.", "r2", "a2")
    await _until(lambda: env.session.state.tokens_in >= 1200)
    assert (env.session.state.tokens_in, env.session.state.tokens_out) == (1200, 800)
    assert env.session.state.cost_usd == pytest.approx(2 * 37_200 / 1e6)


async def test_a_model_with_no_price_costs_zero_and_warns(env, caplog) -> None:  # noqa: ANN001
    """Covers: RB-12"""
    env.brain.prices = {}
    await _welcomed(env)
    assert env.session.state.cost_usd == 0 and env.session.state.tokens_in == 600
    assert any("no price" in r.message for r in caplog.records)


# ---------------------------------------------------------------- RB-13: failure
async def test_a_model_error_ends_the_call_with_error_and_keeps_the_transcript(env) -> None:  # noqa: ANN001
    """Covers: RB-13"""
    await _welcomed(env)
    await env.fake.caller_says("hello")
    await asyncio.sleep(0.1)
    await env.fake.send({"type": "error", "error": {"type": "invalid_request_error", "code": "boom", "message": "bad"}})
    await _until(lambda: env.h.ended)
    assert env.h.ended == ["error"]
    assert any(m["role"] == "user" for m in env.session.history)       # the transcript so far is kept
    assert env.session.state.ended


async def test_a_dropped_connection_ends_the_call_with_error(env) -> None:  # noqa: ANN001
    """Covers: RB-13"""
    await _welcomed(env)
    await env.fake.ws.close()
    await _until(lambda: getattr(env.brain.service, "_receive_task", None) is not None and env.brain.service._receive_task.done())  # noqa: SLF001
    await env.brain.check_clocks()
    assert env.h.ended == ["error"]


# ---------------------------------------------------------------- RB-14: nothing secret leaks
async def test_the_key_is_in_no_log_event_or_message(env, caplog) -> None:  # noqa: ANN001
    """Covers: RB-14"""
    lines: list[str] = []
    sink = loguru_logger.add(lambda m: lines.append(str(m)), level="DEBUG")
    try:
        await _welcomed(env)
        await env.fake.caller_says("What is my deductible?")
        await env.fake.agent_says("It is five hundred dollars.", "r1", "a1")
        await env.fake.send({"type": "error", "error": {"type": "invalid_request_error", "code": "boom", "message": "bad"}})
        await _until(lambda: env.h.ended)
    finally:
        loguru_logger.remove(sink)
    assert KEY not in "\n".join(lines) and KEY not in caplog.text
    for e in await _events(env):
        assert KEY not in f"{e.text} {e.data}"
    assert KEY not in str(env.session.history)
    assert KEY not in str(env.fake.of("session.update"))               # nor in what the session configuration says
