"""The talking avatar: a stage that can never make the agent harder to hear.

Covers: AV-01, AV-02, AV-03, AV-04, AV-05, AV-06, AV-07, AV-08, AV-09, AV-10, AV-11, AV-12
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest
from pipecat.frames.frames import (
    InterruptionFrame,
    OutputImageRawFrame,
    TextFrame,
    TTSAudioRawFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voiceai.core.config import Settings
from voiceai.modules.conversation import api as calls_api
from voiceai.modules.voice import avatar as avatar_mod
from voiceai.modules.voice import room as room_mod
from voiceai.modules.voice.avatar import PassThroughOnFailure, scrub

KEY = "simli-test-key-do-not-leak-0123456789"
M = {"X-Tenant-Id": "evergreen-care"}
SECRET = "a-test-secret-long-enough-for-hs256"


def _audio(tag: bytes = b"\x01\x00" * 160) -> TTSAudioRawFrame:
    return TTSAudioRawFrame(audio=tag, sample_rate=24000, num_channels=1)


def _video() -> OutputImageRawFrame:
    return OutputImageRawFrame(image=b"\x10" * (8 * 8 * 3), size=(8, 8), format="RGB")


class Recorder:
    """Collects what a processor pushes, in place of a linked pipeline.

    Patches `FrameProcessor.push_frame` at class level, not on the instance, so the avatar mixin's
    own `push_frame` (which notices the vendor handing speech back) still runs and then reaches here.
    """

    def __init__(self, processor: FrameProcessor) -> None:
        self.frames: list = []     # what travels downstream, towards the caller
        self.upstream: list = []   # what travels back up the pipeline (errors)
        self.processor = processor

        async def capture(owner, frame, direction=FrameDirection.DOWNSTREAM):  # noqa: ANN001, ANN202
            if owner is processor:
                (self.frames if direction == FrameDirection.DOWNSTREAM else self.upstream).append(frame)

        FrameProcessor.push_frame = capture  # type: ignore[method-assign]

    async def feed(self, frame) -> None:  # noqa: ANN001
        await self.processor.process_frame(frame, FrameDirection.DOWNSTREAM)


@pytest.fixture(autouse=True)
def _restore_push_frame(monkeypatch):  # noqa: ANN001, ANN202
    original = FrameProcessor.push_frame
    monkeypatch.setattr(avatar_mod, "READY_PROOF_S", 0.05)   # the stub shows no frame; do not wait 5 s for one
    avatar_mod._LIVE.clear()  # noqa: SLF001
    yield
    avatar_mod._LIVE.clear()  # noqa: SLF001
    FrameProcessor.push_frame = original  # type: ignore[method-assign]


class FakeService(FrameProcessor):
    """Stands in for the vendor service: consumes TTS audio and renders it, as Simli does."""

    def __init__(self) -> None:
        super().__init__()
        self.sent = 0
        self.cleared = 0
        self.explode = False
        self.silent = False       # consumes speech and never hands anything back

    async def process_frame(self, frame, direction):  # noqa: ANN001, ANN201
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame):
            if self.explode:
                raise ConnectionError(f"vendor dropped the connection (key {KEY})")
            self.sent += 1
            if self.silent:
                return                                           # swallowed: the vendor hung
            await self.push_frame(_video())                      # the face ...
            await self.push_frame(_audio(b"\x02\x00" * 160))     # ... and the speech, re-timed
            return                                               # the original audio is consumed
        if isinstance(frame, InterruptionFrame):
            self.cleared += 1
        await self.push_frame(frame, direction)


class StubAvatar(PassThroughOnFailure, FakeService):
    def __init__(self) -> None:
        super().__init__()
        self.started = 0
        self.stopped = 0
        self.hang_on_open = False

    async def _start_avatar(self) -> None:
        self.started += 1
        if self.hang_on_open:
            await asyncio.sleep(3600)

    async def _stop_avatar(self) -> None:
        self.stopped += 1


@pytest.fixture
def configured(monkeypatch):  # noqa: ANN001, ANN201
    s = Settings(_env_file=None, simli_api_key=KEY, simli_face_id="face-123",
                 livekit_url="wss://t.livekit.cloud", livekit_api_key="K", livekit_api_secret=SECRET)
    monkeypatch.setattr(avatar_mod, "get_settings", lambda: s)
    monkeypatch.setattr(room_mod, "get_settings", lambda: s)
    return s


# ---------------------------------------------------------------- AV-01: availability and the flag
def test_avatar_is_available_only_with_both_settings_and_the_sdk(monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-01"""
    def available(**kw) -> bool:  # noqa: ANN003
        monkeypatch.setattr(avatar_mod, "get_settings", lambda: Settings(_env_file=None, **kw))
        return avatar_mod.avatar_available()

    assert available(simli_api_key=KEY, simli_face_id="f") is True
    assert available(simli_api_key=KEY) is False          # a key is not a face
    assert available(simli_face_id="f") is False          # a face is not a key
    assert available() is False

    # and the SDK being absent is the same quiet answer, not an error
    monkeypatch.setattr(avatar_mod, "get_settings", lambda: Settings(_env_file=None, simli_api_key=KEY, simli_face_id="f"))
    monkeypatch.setattr(avatar_mod.importlib.util, "find_spec", lambda name: None)
    assert avatar_mod.avatar_available() is False


async def _video_call(client, agent_id):  # noqa: ANN001, ANN202
    return (await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})).json()


async def _agent(client) -> str:  # noqa: ANN001
    return next(a["id"] for a in (await client.get("/api/agents", headers=M)).json()["items"] if a["published_version"])


class _Vision:
    def role_available(self, role: str) -> bool:
        return True


async def test_media_avatar_reports_whether_a_face_is_coming(client, seeded, configured, monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-01, AV-08"""
    monkeypatch.setattr(calls_api, "video_room", lambda: room_mod.LiveKitVideoRoom())
    monkeypatch.setattr(calls_api, "gateway", lambda: _Vision())
    monkeypatch.setattr(room_mod.LiveKitVideoRoom, "start_agent", lambda self, c, t: None)
    agent_id = await _agent(client)

    r = await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})
    body = r.json()
    assert body["media"]["avatar"] is True
    assert "video_unavailable" not in body
    assert KEY not in r.text      # the vendor key is never in an API response (AV-08)

    # unconfigured: still a video call, with a room and a token, and no face
    monkeypatch.setattr(avatar_mod, "get_settings", lambda: Settings(_env_file=None))
    body = await _video_call(client, agent_id)
    assert body["media"]["avatar"] is False
    assert "video_unavailable" not in body and body["media"]["room"].startswith("call-")


# ---------------------------------------------------------------- AV-02: the pipeline
class _Session:
    call_id = "c-avatar"
    config = {"persona": {"voice": "aura-2-thalia-en", "speed": 1.0}, "policy": {}}
    history: list = []

    def turn_settings(self):  # noqa: ANN201
        from voiceai.modules.agentcfg.contract import TurnSettings

        return TurnSettings.from_dict({})


def _names(task) -> list[str]:  # noqa: ANN001
    inner = next(p for p in task._pipeline._processors if type(p).__name__ == "Pipeline")  # noqa: SLF001
    return [type(p).__name__ for p in inner._processors]  # noqa: SLF001


def test_the_avatar_sits_after_tts_and_enables_video_out(configured) -> None:  # noqa: ANN001
    """Covers: AV-02"""
    from voiceai.modules.voice import frames, pipeline

    holder = frames.register("c-avatar")
    try:
        plain_task, plain_transport, _ = pipeline.build_room(_Session(), "dg", "wss://x", "tok", "call-1", holder=holder)
        avatar = StubAvatar()
        task, transport, _ = pipeline.build_room(_Session(), "dg", "wss://x", "tok", "call-1", holder=holder, avatar=avatar)

        with_avatar, without = _names(task), _names(plain_task)
        # exactly one extra stage, between TTS and the transport output, nothing else moved
        assert with_avatar.index("StubAvatar") == with_avatar.index("DeepgramTTSService") + 1
        assert with_avatar.index("StubAvatar") + 1 == with_avatar.index("LiveKitOutputTransport")
        assert [n for n in with_avatar if n != "StubAvatar"] == without
        # the input tap is still the first thing after the transport input
        assert with_avatar.index("FrameTap") == with_avatar.index("LiveKitInputTransport") + 1

        assert transport._params.video_out_enabled is True          # noqa: SLF001
        assert transport._params.video_out_is_live is True          # noqa: SLF001
        assert plain_transport._params.video_out_enabled is False   # noqa: SLF001
        assert (transport._params.video_out_width, transport._params.video_out_framerate) == (512, 25)  # noqa: SLF001
    finally:
        frames.release("c-avatar")


# ---------------------------------------------------------------- AV-03: face and speech
async def test_the_caller_gets_the_avatars_audio_not_the_tts_audio() -> None:
    """Covers: AV-03"""
    avatar = StubAvatar()
    out = Recorder(avatar)
    await avatar.open_avatar()
    await out.feed(_audio(b"\x01\x00" * 160))

    kinds = [type(f).__name__ for f in out.frames]
    assert "OutputImageRawFrame" in kinds                       # the face
    speech = [f for f in out.frames if isinstance(f, TTSAudioRawFrame)]
    assert [f.audio for f in speech] == [b"\x02\x00" * 160]    # the re-timed audio ...
    assert b"\x01\x00" * 160 not in [f.audio for f in speech]  # ... and not the original


# ---------------------------------------------------------------- AV-04: interruption
async def test_an_interruption_reaches_the_service() -> None:
    """Covers: AV-04"""
    avatar = StubAvatar()
    out = Recorder(avatar)
    await avatar.open_avatar()
    await out.feed(InterruptionFrame())
    assert avatar.cleared == 1


async def test_the_real_simli_stage_clears_its_buffer_on_interruption(configured) -> None:  # noqa: ANN001
    """Covers: AV-04"""
    class FakeClient:
        def __init__(self) -> None:
            self.cleared = 0

        async def clearBuffer(self) -> None:  # noqa: N802
            self.cleared += 1

    avatar = avatar_mod.make_avatar()
    fake = FakeClient()
    avatar._simli_client = fake  # noqa: SLF001
    avatar._avatar_open = True   # noqa: SLF001 - as if a participant had joined
    avatar._avatar_ready = True  # noqa: SLF001 - and the vendor session had come up
    out = Recorder(avatar)
    await out.feed(InterruptionFrame())
    assert fake.cleared == 1
    assert any(isinstance(f, InterruptionFrame) for f in out.frames)  # and it still travels on


# ---------------------------------------------------------------- AV-05: the agent is always heard
async def test_a_failing_avatar_never_silences_the_agent() -> None:
    """Covers: AV-05"""
    reasons: list[str] = []

    async def noted(reason: str) -> None:
        reasons.append(reason)

    avatar = StubAvatar()
    avatar.configure_failure(noted)
    out = Recorder(avatar)
    await avatar.open_avatar()

    avatar.explode = True
    original = _audio(b"\x07\x00" * 160)
    await out.feed(original)                         # the vendor raises mid-call ...

    assert avatar.avatar_failed is True
    assert out.frames[-1] is original                # ... and the agent's speech still goes out unchanged
    assert not any(isinstance(f, OutputImageRawFrame) for f in out.frames)

    out.frames.clear()
    again = _audio(b"\x08\x00" * 160)
    await out.feed(again)
    await out.feed(TextFrame("still flowing"))
    assert [f for f in out.frames if isinstance(f, TTSAudioRawFrame)] == [again]  # transparent from now on
    assert len(reasons) == 1                         # reported once, however many frames follow
    assert avatar.stopped >= 1                       # and the session that is not working is closed


async def test_an_avatar_that_never_started_is_transparent() -> None:
    """Covers: AV-05"""
    avatar = StubAvatar()
    out = Recorder(avatar)
    first = _audio()
    await out.feed(first)       # before anyone has joined, the stage is not rendering
    assert out.frames == [first]
    assert avatar.sent == 0 and avatar.started == 0


async def test_a_start_failure_degrades_to_pass_through(configured) -> None:  # noqa: ANN001
    """Covers: AV-05"""
    class BrokenClient:
        async def start(self) -> None:
            raise ConnectionError(f"could not reach the vendor with {KEY}")

        async def stop(self) -> None:
            return None

        async def sendSilence(self) -> None:  # noqa: N802
            return None

    avatar = avatar_mod.make_avatar()
    avatar._simli_client = BrokenClient()  # noqa: SLF001
    out = Recorder(avatar)

    await avatar.open_avatar()                      # must not raise: a vendor failure never ends a call
    assert avatar.avatar_failed is True

    heard = _audio(b"\x05\x00" * 160)
    await out.feed(heard)
    assert out.frames == [heard]                    # the agent is heard

    # the vendor's error went upstream, and neither its text nor its exception carries the key (AV-08)
    assert out.upstream, "the failure should be reported upstream"
    for error in out.upstream:
        assert KEY not in str(error.error) and KEY not in str(error.exception)


async def test_the_vendor_reporting_an_error_means_stop_relying_on_it(configured) -> None:  # noqa: ANN001
    """Covers: AV-05"""
    avatar = avatar_mod.make_avatar()
    assert avatar.avatar_failed is False
    await avatar._fail("vendor reported an error")  # noqa: SLF001
    assert avatar.avatar_failed is True


# ---------------------------------------------------------------- AV-06: never evidence
def test_avatar_frames_never_reach_evidence_storage_or_a_model() -> None:
    """Covers: AV-06"""
    source = Path(avatar_mod.__file__).read_text(encoding="utf-8")
    for forbidden in ("evidence", "blob_store", "blobstore", "store_frame", "gateway", "complete_json", "media"):
        assert forbidden not in source.lower().replace("media-protocol", ""), forbidden

    from voiceai.modules.voice import frames, pipeline

    holder = frames.register("c-av6")
    try:
        task, _, _ = pipeline.build_room(_Session(), "dg", "wss://x", "tok", "call-6", holder=holder, avatar=StubAvatar())
        names = _names(task)
        # the tap only sees inbound video: it sits before everything, the avatar after TTS
        assert names.index("FrameTap") < names.index("VADProcessor") < names.index("StubAvatar")
    finally:
        frames.release("c-av6")


# ---------------------------------------------------------------- AV-07: lifetime and isolation
async def test_the_vendor_session_opens_on_demand_and_closes_with_the_call() -> None:
    """Covers: AV-07"""
    avatar = StubAvatar()
    assert avatar.started == 0                  # constructing it opens nothing
    await avatar.close_avatar()
    assert avatar.stopped == 0                  # closing what was never opened does nothing

    await avatar.open_avatar()
    await avatar.open_avatar()                  # idempotent
    assert avatar.started == 1 and avatar.avatar_open

    await avatar.close_avatar()
    await avatar.close_avatar()
    assert avatar.stopped == 1 and not avatar.avatar_open


def test_the_session_is_opened_by_the_first_participant_not_at_pipeline_start() -> None:
    """Covers: AV-07"""
    import inspect

    from voiceai.modules.voice import pipeline

    src = inspect.getsource(pipeline.run_room)
    joined = src[src.index("async def _joined"):src.index("on_participant_disconnected")]
    assert joined.index("open_avatar") < joined.index("brain.greet()")   # opened first, then the welcome
    assert "open_avatar" not in src[:src.index("async def _joined")]     # and nowhere earlier
    assert "close_avatar" in src[src.index("finally:"):]                 # closed with the call

    # the stock service starts its vendor session in setup(); ours must not
    guarded = avatar_mod._guarded_simli_class()  # noqa: SLF001
    setup_src = inspect.getsource(guarded.setup)
    assert "super(SimliVideoService, self).setup" in setup_src
    assert "_start_connection" not in setup_src


async def test_voice_and_text_calls_never_construct_the_avatar(client, seeded, configured, monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-07"""
    def boom(*a, **kw):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("an avatar was constructed for a call that is not a video call")

    monkeypatch.setattr(avatar_mod, "make_avatar", boom)
    agent_id = await _agent(client)
    for channel in ("voice", "text"):
        r = await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": channel})
        assert r.status_code == 200 and "media" not in r.json()


# ---------------------------------------------------------------- AV-08: the key stays put
async def test_the_vendor_key_never_reaches_a_log_line(caplog, configured) -> None:  # noqa: ANN001
    """Covers: AV-08"""
    assert scrub(f"401 Unauthorized for {KEY} at https://api.simli.ai") == "401 Unauthorized for *** at https://api.simli.ai"
    assert scrub("nothing sensitive") == "nothing sensitive"

    avatar = StubAvatar()
    out = Recorder(avatar)
    await avatar.open_avatar()
    avatar.explode = True              # this vendor error message contains the key
    with caplog.at_level(logging.DEBUG, logger="voiceai.voice"):
        await out.feed(_audio())
    assert caplog.text, "the failure should be logged"
    assert KEY not in caplog.text


# ---------------------------------------------------------------- AV-05: a hung vendor is a failure too
async def test_a_vendor_that_never_opens_cannot_hold_the_agent(monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-05, AV-09"""
    monkeypatch.setattr(avatar_mod, "OPEN_TIMEOUT_S", 0.1)
    avatar = StubAvatar()
    avatar.hang_on_open = True
    out = Recorder(avatar)

    await asyncio.wait_for(avatar.open_avatar(), 2)     # returns: the hang is cut short
    assert avatar.avatar_failed is True and not avatar._avatar_ready  # noqa: SLF001

    heard = _audio()
    await out.feed(heard)
    assert out.frames == [heard]                        # and the agent is heard


async def test_the_welcome_is_heard_while_the_vendor_is_still_opening() -> None:
    """Covers: AV-05, AV-09"""
    avatar = StubAvatar()
    avatar.hang_on_open = True
    out = Recorder(avatar)

    opening = asyncio.create_task(avatar.open_avatar())  # the join handler does this and moves on
    await asyncio.sleep(0)
    assert avatar.avatar_open and not avatar._avatar_ready  # noqa: SLF001 - asked for, not up yet

    welcome = _audio(b"\x09\x00" * 160)
    await out.feed(welcome)
    assert out.frames == [welcome]                       # not consumed: the stage is transparent until ready
    assert avatar.sent == 0
    opening.cancel()


async def test_speech_the_vendor_swallows_is_heard_late_not_never(monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-05, AV-09"""
    monkeypatch.setattr(avatar_mod, "RETURN_TIMEOUT_S", 0.3)
    avatar = StubAvatar()
    avatar.silent = True                                 # connected, but hands nothing back
    out = Recorder(avatar)
    await avatar.open_avatar()

    first = _audio(b"\x0a\x00" * 160)
    await out.feed(first)
    assert out.frames == []                              # consumed, waiting for the vendor
    await asyncio.sleep(0.9)                             # longer than the return timeout

    assert avatar.avatar_failed is True
    assert out.frames == [first]                         # the swallowed speech is given back, late

    nxt = _audio(b"\x0b\x00" * 160)
    await out.feed(nxt)
    assert out.frames[-1] is nxt                         # and everything after passes straight through


async def test_a_healthy_avatar_is_not_failed_by_the_watchdog(monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-05, AV-09"""
    monkeypatch.setattr(avatar_mod, "RETURN_TIMEOUT_S", 0.3)
    avatar = StubAvatar()
    out = Recorder(avatar)
    await avatar.open_avatar()

    await out.feed(_audio())                             # the vendor answers at once
    await asyncio.sleep(0.9)
    assert avatar.avatar_failed is False
    assert not (avatar._pending)                         # noqa: SLF001 - nothing is held back


# ---------------------------------------------------------------- AV-10..12: refusal, cap, shutdown
async def test_a_refusal_after_connecting_fails_the_stage_before_it_swallows_speech(monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-10"""
    monkeypatch.setattr(avatar_mod, "READY_PROOF_S", 2.0)
    avatar = StubAvatar()
    out = Recorder(avatar)

    opening = asyncio.create_task(avatar.open_avatar())
    await asyncio.sleep(0.1)                       # connected; waiting for proof of life
    avatar.vendor_ended("rate limit")              # the SDK's ERROR event arrives
    await asyncio.wait_for(opening, 1)

    assert avatar.avatar_failed and not avatar._avatar_ready  # noqa: SLF001
    heard = _audio()
    await out.feed(heard)
    assert out.frames == [heard] and avatar.sent == 0   # heard directly, never sent to the vendor


async def test_a_session_with_no_frame_yet_is_trusted_not_failed() -> None:
    """Covers: AV-10"""
    avatar = StubAvatar()                          # connects, shows nothing, reports nothing
    await avatar.open_avatar()
    assert avatar._avatar_ready and not avatar.avatar_failed  # noqa: SLF001 - silence is not a refusal


async def test_a_first_frame_marks_the_session_ready_at_once(monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-10"""
    monkeypatch.setattr(avatar_mod, "READY_PROOF_S", 30.0)
    avatar = StubAvatar()
    Recorder(avatar)
    opening = asyncio.create_task(avatar.open_avatar())
    await asyncio.sleep(0.1)
    await avatar.push_frame(_video())              # the vendor renders its first frame
    await asyncio.wait_for(opening, 1)
    assert avatar._avatar_ready  # noqa: SLF001


async def test_calls_over_the_session_cap_get_no_avatar_and_no_vendor_contact(configured, monkeypatch) -> None:  # noqa: ANN001
    """Covers: AV-11"""
    monkeypatch.setattr(avatar_mod, "get_settings", lambda: configured.model_copy(update={"avatar_max_sessions": 1}))
    first, second = StubAvatar(), StubAvatar()
    out = Recorder(second)

    await first.open_avatar()
    await second.open_avatar()

    assert first.started == 1 and first._avatar_ready  # noqa: SLF001
    assert second.started == 0 and second.avatar_failed   # never contacted the vendor
    heard = _audio()
    await out.feed(heard)
    assert out.frames == [heard]                        # and the agent is still heard

    await first.close_avatar()                          # the slot comes back
    third = StubAvatar()
    await third.open_avatar()
    assert third.started == 1 and not third.avatar_failed


async def test_shutdown_closes_every_open_session(configured) -> None:  # noqa: ANN001
    """Covers: AV-12"""
    a = StubAvatar()
    await a.open_avatar()
    assert a.stopped == 0

    await room_mod.close_avatars()

    assert a.stopped == 1 and not a.avatar_open
    assert not avatar_mod._LIVE  # noqa: SLF001
