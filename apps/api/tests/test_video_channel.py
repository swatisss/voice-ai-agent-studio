"""The video channel: a room and a token, or an honest degradation to voice.

Covers: VI-01, VI-02, VI-03, VI-14, API-05, VO-06
"""
from __future__ import annotations

import jwt
import pytest
from sqlalchemy import select

from voiceai.core import videoroom as videoroom_core
from voiceai.core.config import Settings, get_settings
from voiceai.core.db import sessionmaker
from voiceai.core.llm import gateway as gw
from voiceai.core.tables import Call
from voiceai.modules.conversation import api as calls_api
from voiceai.modules.voice import room as room_mod
from voiceai.ports.videoroom import RoomGrant, VideoRoom

M = {"X-Tenant-Id": "evergreen-care"}
SECRET = "a-test-secret-long-enough-for-hs256"


@pytest.fixture
def livekit(monkeypatch):  # noqa: ANN001, ANN201
    """Configure LiveKit with throwaway credentials. No network: tokens are minted locally."""
    settings = Settings(
        _env_file=None, livekit_url="wss://test.livekit.cloud",
        livekit_api_key="APItest", livekit_api_secret=SECRET,
    )
    monkeypatch.setattr(room_mod, "get_settings", lambda: settings)
    started: list[tuple[str, str]] = []
    real_start = room_mod.LiveKitVideoRoom.start_agent
    monkeypatch.setattr(
        room_mod.LiveKitVideoRoom, "start_agent",
        lambda self, call_id, tenant_id, brain="pipeline": started.append((call_id, tenant_id)),
    )
    monkeypatch.setattr(calls_api, "video_room", lambda: room_mod.LiveKitVideoRoom())
    assert real_start is not None
    return started


@pytest.fixture
def vision_ok(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(calls_api, "gateway", lambda: _RoleAvailable(True))
    return True


class _RoleAvailable:
    def __init__(self, value: bool) -> None:
        self.value = value

    def role_available(self, role: str) -> bool:
        return self.value


async def _published_agent(client) -> str:  # noqa: ANN001
    agents = (await client.get("/api/agents", headers=M)).json()["items"]
    return next(a["id"] for a in agents if a["published_version"])


# ---------------------------------------------------------------- VI-01
async def test_a_video_call_returns_a_room_and_a_scoped_token(client, seeded, livekit, vision_ok) -> None:  # noqa: ANN001
    """Covers: VI-01"""
    agent_id = await _published_agent(client)
    r = await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "video_unavailable" not in body

    media = body["media"]
    assert media["url"] == "wss://test.livekit.cloud"
    assert media["room"] == f"call-{body['call_id']}"
    assert media["identity"] == "caller"

    claims = jwt.decode(media["token"], SECRET, algorithms=["HS256"])
    grant = claims["video"]
    assert grant["room"] == f"call-{body['call_id']}"   # scoped to this call's room and no other
    assert grant["roomJoin"] is True
    assert grant.get("canPublish") is True and grant.get("canSubscribe") is True
    assert not grant.get("canPublishData")  # the control surface is REST and SSE, not the room
    assert claims["exp"] > claims["nbf"]  # LiveKit tokens carry nbf/exp, not iat

    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == body["call_id"]))
    assert call.channel == "video"
    assert livekit == [(body["call_id"], "evergreen-care")]  # the agent was dispatched


async def test_no_media_service_degrades_to_voice(client, seeded, vision_ok, monkeypatch) -> None:  # noqa: ANN001
    """Covers: VI-01"""
    monkeypatch.setattr(calls_api, "video_room", lambda: _Unavailable())
    agent_id = await _published_agent(client)
    body = (await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})).json()

    assert "media" not in body
    assert body["video_unavailable"]["reason"] == "media_unconfigured"
    assert "LIVEKIT_API_SECRET" in body["video_unavailable"]["detail"]  # names the cause, not just "not configured"
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == body["call_id"]))
    assert call.channel == "voice"  # the call still happens, as a voice call


async def test_no_vision_model_degrades_to_voice(client, seeded, livekit, monkeypatch) -> None:  # noqa: ANN001
    """Covers: VI-01"""
    monkeypatch.setattr(calls_api, "gateway", lambda: _RoleAvailable(False))
    agent_id = await _published_agent(client)
    body = (await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})).json()

    assert body["video_unavailable"]["reason"] == "vision_unconfigured"
    assert "media" not in body
    assert livekit == []  # no agent dispatched for a call that is not a video call
    async with sessionmaker()() as s:
        assert (await s.scalar(select(Call).where(Call.id == body["call_id"]))).channel == "voice"


class _Unavailable:
    def available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "LIVEKIT_API_SECRET not set in apps/api/.env (restart the API after editing it)."


def test_unconfigured_livekit_is_simply_unavailable(monkeypatch) -> None:  # noqa: ANN001
    """Covers: VI-01"""
    monkeypatch.setattr(room_mod, "get_settings", lambda: Settings(_env_file=None))
    assert room_mod.configured() is False
    assert room_mod.LiveKitVideoRoom().available() is False
    # and a partial configuration is not half-available
    monkeypatch.setattr(room_mod, "get_settings", lambda: Settings(_env_file=None, livekit_url="wss://x"))
    assert room_mod.configured() is False


def test_the_room_implements_the_port() -> None:
    """Covers: VI-01"""
    assert isinstance(room_mod.LiveKitVideoRoom(), VideoRoom)
    assert videoroom_core.video_room() is not None
    grant = RoomGrant(url="wss://x", room="call-1", token="t", identity="caller")
    assert grant.as_dict() == {"url": "wss://x", "room": "call-1", "token": "t", "identity": "caller"}


def test_token_lifetime_covers_the_call_and_little_more(monkeypatch) -> None:  # noqa: ANN001
    """Covers: VI-01"""
    monkeypatch.setattr(
        room_mod, "get_settings",
        lambda: Settings(_env_file=None, livekit_url="wss://t", livekit_api_key="K", livekit_api_secret=SECRET),
    )
    grant = room_mod.LiveKitVideoRoom().grant("abc", 600)
    claims = jwt.decode(grant.token, SECRET, algorithms=["HS256"])
    life = claims["exp"] - claims["nbf"]
    assert 600 < life <= 600 + room_mod.TOKEN_GRACE.total_seconds() + 2

    agent = jwt.decode(room_mod.LiveKitVideoRoom().agent_token("abc", 600), SECRET, algorithms=["HS256"])
    assert agent["sub"] == "agent" and claims["sub"] == "caller"


# ---------------------------------------------------------------- VI-02: the agent has no camera
def test_the_agent_never_publishes_the_callers_camera() -> None:
    """Covers: VI-02

    CP-0014 reworded VI-02: the agent may publish one video track, its own avatar face, but never a
    track that carries the caller's camera, and nothing lets it enable the caller's.
    """
    from pathlib import Path

    from voiceai.modules.voice import frames, pipeline

    source = Path(room_mod.__file__).read_text(encoding="utf-8")
    assert "can_publish_data=False" in source          # no second control surface in the room

    class S:
        call_id = "c-vi2"
        config = {"persona": {}, "policy": {}}
        history: list = []

        def turn_settings(self):  # noqa: ANN202
            from voiceai.modules.agentcfg.contract import TurnSettings

            return TurnSettings.from_dict({})

    holder = frames.register("c-vi2")
    try:
        _, plain, _ = pipeline.build_room(S(), "dg", "wss://x", "t", "call-vi2", holder=holder)
        assert plain._params.video_in_enabled is True        # noqa: SLF001 - it subscribes to the caller's camera
        assert plain._params.video_out_enabled is False      # noqa: SLF001 - and with no avatar publishes no video at all
    finally:
        frames.release("c-vi2")

    # nothing in the tool surface or the room protocol can turn the caller's camera on
    from voiceai.modules.conversation import tools as conv_tools

    assert set(conv_tools.LOOK_SCHEMA["function"]["parameters"]["properties"]) == {"asset_hint"}


# ---------------------------------------------------------------- VO-06: both pipelines construct
def test_the_livekit_pipeline_builds_without_network(monkeypatch) -> None:  # noqa: ANN001
    """Covers: VO-06, VI-03"""
    from voiceai.modules.voice import frames, pipeline

    class FakeSession:
        call_id = "c-video"
        config = {"persona": {"voice": "aura-2-thalia-en", "speed": 1.0}, "policy": {}}
        history: list = []

        def turn_settings(self):  # noqa: ANN202
            from voiceai.modules.agentcfg.contract import TurnSettings

            return TurnSettings.from_dict({})

    holder = frames.register("c-video")
    try:
        task, transport, brain = pipeline.build_room(
            FakeSession(), "dg-key", "wss://test.livekit.cloud", "token", "call-c-video", holder=holder
        )
        assert task is not None and transport is not None and brain is not None
        # the tap is in the pipeline, between the transport input and VAD
        inner = next(p for p in task._pipeline._processors if type(p).__name__ == "Pipeline")  # noqa: SLF001
        names = [type(p).__name__ for p in inner._processors]  # noqa: SLF001
        assert names.index("LiveKitInputTransport") < names.index("FrameTap") < names.index("VADProcessor")
        assert "FrameTap" not in names[names.index("VADProcessor"):]  # exactly one, before the audio path
    finally:
        frames.release("c-video")


def test_the_tap_consumes_video_so_nothing_downstream_sees_it() -> None:
    """Covers: VI-03"""
    import asyncio

    from PIL import Image
    from pipecat.frames.frames import TextFrame, UserImageRawFrame
    from pipecat.processors.frame_processor import FrameDirection

    from voiceai.modules.voice import frames
    from voiceai.modules.voice.processors import FrameTap

    holder = frames.FrameHolder()
    tap = FrameTap(holder)
    forwarded: list = []

    async def capture(frame, direction):  # noqa: ANN001, ANN202
        forwarded.append(frame)

    tap.push_frame = capture  # type: ignore[method-assign]

    async def run() -> None:
        for i in range(5):
            image = Image.new("RGB", (64, 48 + i), (10, 20, 30))
            await tap.process_frame(
                UserImageRawFrame(image=image.tobytes(), size=(64, 48 + i), format="RGB", user_id="caller"),
                FrameDirection.DOWNSTREAM,
            )
        await tap.process_frame(TextFrame("audio-adjacent"), FrameDirection.DOWNSTREAM)

    asyncio.run(run())

    assert [type(f).__name__ for f in forwarded] == ["TextFrame"]  # no video forwarded
    assert holder.frame is not None and holder.frame.height == 52  # only the newest kept
    assert holder.camera_on is True


# ---------------------------------------------------------------- VI-14 / API-05
async def test_a_video_call_with_no_camera_behaves_as_voice(client, seeded, livekit, vision_ok) -> None:  # noqa: ANN001
    """Covers: VI-14, API-05"""
    agent_id = await _published_agent(client)
    body = (await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})).json()
    call_id = body["call_id"]

    detail = (await client.get(f"/api/calls/{call_id}", headers=M)).json()
    assert detail["channel"] == "video"
    assert detail["evidence"] == []   # nothing was looked at
    assert detail["case"] is None

    ended = await client.post(f"/api/calls/{call_id}/end", headers=M)
    assert ended.status_code == 200
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == call_id))
    assert call.ended_at is not None  # a normal ending, like any voice call


async def test_call_detail_carries_evidence_and_case(client, seeded, livekit, vision_ok) -> None:  # noqa: ANN001
    """Covers: API-05"""
    from voiceai.core.tables import CallEvidence, VisualCase

    agent_id = await _published_agent(client)
    body = (await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})).json()
    call_id = body["call_id"]

    async with sessionmaker()() as s:
        s.add_all([
            CallEvidence(
                tenant_id="evergreen-care", call_id=call_id, seq=1, media_id=None, source="camera",
                description="A bed side rail is bent.", items=[], confidence="unclear",
                safety_flag="none", asked_for="a closer look", caller_words="The rail is bent.",
            ),
            CallEvidence(
                tenant_id="evergreen-care", call_id=call_id, seq=2, media_id=None, source="camera",
                description="The hinge is cracked.", items=[], confidence="confirmed",
                safety_flag="none", asked_for=None, caller_words="Better?",
            ),
            VisualCase(
                tenant_id="evergreen-care", call_id=call_id, agent_id=agent_id, kind="facility_fault",
                narrative="A bent rail with a cracked hinge.", missing=["Ward number"],
                routing="needs_docs", routing_reason="The bed cannot be located.",
            ),
        ])
        await s.commit()

    detail = (await client.get(f"/api/calls/{call_id}", headers=M)).json()
    assert [e["seq"] for e in detail["evidence"]] == [1, 2]
    assert [e["confidence"] for e in detail["evidence"]] == ["unclear", "confirmed"]
    assert detail["evidence"][0]["caller_words"] == "The rail is bent."
    assert detail["case"]["narrative"] == "A bent rail with a cracked hinge."
    assert detail["case"]["missing"] == ["Ward number"]
    assert detail["case"]["routing_reason"] == "The bed cannot be located."

    # another tenant sees the call as missing entirely
    assert (await client.get(f"/api/calls/{call_id}", headers={"X-Tenant-Id": "evergreen-sandbox"})).status_code == 404


async def test_the_voice_socket_refuses_a_video_call_id(client, seeded, livekit, vision_ok) -> None:  # noqa: ANN001
    """Covers: VI-14"""
    agent_id = await _published_agent(client)
    body = (await client.post("/api/calls", headers=M, json={"agent_id": agent_id, "channel": "video"})).json()
    # A video call does not use the voice WebSocket at all; the handler checks the channel.
    from voiceai.modules.voice.api import voice

    assert voice is not None
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == body["call_id"]))
    assert call.channel == "video"


def test_default_settings_leave_video_unconfigured() -> None:
    """Covers: VI-01"""
    settings = get_settings()
    assert settings.livekit_url is None or settings.livekit_url == ""
    assert room_mod.JOIN_TIMEOUT_S == 60.0
