"""Voice pipeline smoke tests (guards Pipecat API drift). Covers: VO-02, VO-04, VO-05, VO-06"""
from __future__ import annotations

import asyncio

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voiceai.voice.processors import TurnAggregator, UserTurnFrame
from voiceai.voice.serializer import RawPCMSerializer


async def test_turn_aggregator_merges_finals():
    """Covers: VO-02"""
    from pipecat.frames.frames import TranscriptionFrame, VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame

    agg = TurnAggregator(delay_ms=50)
    out: list[str] = []

    async def capture(frame, direction=None):  # noqa: ANN001, ANN202
        if isinstance(frame, UserTurnFrame):
            out.append(frame.text)

    agg.push_frame = capture  # type: ignore[method-assign]
    await agg.handle(VADUserStartedSpeakingFrame())
    await agg.handle(TranscriptionFrame("My claim is", "u", "t"))
    await agg.handle(VADUserStoppedSpeakingFrame())
    await agg.handle(TranscriptionFrame("C-20931.", "u", "t"))
    await asyncio.sleep(0.15)
    assert out == ["My claim is C-20931."]


async def test_serializer_round_trip():
    """Covers: VO-06"""
    from pipecat.frames.frames import InputAudioRawFrame, InterruptionFrame

    ser = RawPCMSerializer()
    frame = await ser.deserialize(b"\x00\x01" * 320)
    assert isinstance(frame, InputAudioRawFrame) and frame.sample_rate == 16000
    assert await ser.serialize(InterruptionFrame()) == '{"type": "interrupt"}'


@pytest.fixture
def sync_client(app, tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'ws.db').as_posix()}")
    monkeypatch.setenv("AUTO_SEED", "1")
    from voiceai.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_websocket_close_codes(sync_client):
    """Covers: VO-04, VO-05"""
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/api/voice/doesnotexist?tenant=evergreen-members") as ws:
            ws.receive_text()
    assert exc.value.code == 4404
    agent_id = sync_client.get("/api/agents", headers={"X-Tenant-Id": "evergreen-members"}).json()["items"][0]["id"]
    call_id = sync_client.post("/api/calls", headers={"X-Tenant-Id": "evergreen-members"},
                               json={"agent_id": agent_id, "channel": "voice"}).json()["call_id"]
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(f"/api/voice/{call_id}?tenant=evergreen-members") as ws:
            ws.receive_text()
    assert exc.value.code == 4500
    assert sync_client.get("/healthz").json()["status"] == "ok"


def test_pipeline_builds_without_network():
    """Covers: VO-06"""
    from types import SimpleNamespace

    from voiceai.voice.pipeline import build

    class FakeWS:
        headers: dict = {}

    session = SimpleNamespace(config={"persona": {"voice": "aura-2-thalia-en"}})
    task, transport, brain, serializer = build(FakeWS(), session, "dummy-key")  # type: ignore[arg-type]
    assert task is not None and brain.session is session and serializer.end_reason == "hangup"
