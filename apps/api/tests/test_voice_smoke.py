"""Voice pipeline smoke tests (guards Pipecat API drift). Covers: VO-04, VO-05, VO-06"""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voiceai.modules.voice.serializer import RawPCMSerializer


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
    from voiceai.core.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_websocket_close_codes(sync_client):
    """Covers: VO-04, VO-05"""
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect("/api/voice/doesnotexist?tenant=evergreen-care") as ws:
            ws.receive_text()
    assert exc.value.code == 4404
    agent_id = sync_client.get("/api/agents", headers={"X-Tenant-Id": "evergreen-care"}).json()["items"][0]["id"]
    call_id = sync_client.post("/api/calls", headers={"X-Tenant-Id": "evergreen-care"},
                               json={"agent_id": agent_id, "channel": "voice"}).json()["call_id"]
    with pytest.raises(WebSocketDisconnect) as exc:
        with sync_client.websocket_connect(f"/api/voice/{call_id}?tenant=evergreen-care") as ws:
            ws.receive_text()
    assert exc.value.code == 4500
    assert sync_client.get("/healthz").json()["status"] == "ok"


def test_pipeline_builds_without_network():
    """Covers: VO-06"""
    from types import SimpleNamespace

    from voiceai.modules.voice.pipeline import build

    class FakeWS:
        headers: dict = {}

    from pipecat.frames.frames import TTSUpdateSettingsFrame
    from pipecat.services.deepgram.tts import DeepgramTTSService

    from voiceai.modules.voice.controls import LiveControls
    from voiceai.modules.voice.turn_detection import TurnSettings

    session = SimpleNamespace(config={"persona": {"voice": "aura-2-thalia-en", "speed": 1.1}}, history=[], turn_settings=lambda: TurnSettings())
    controls = LiveControls(turn=TurnSettings())
    task, transport, brain, serializer = build(FakeWS(), session, "dummy-key", controls)  # type: ignore[arg-type]
    assert task is not None and brain.session is session and serializer.end_reason == "hangup"
    assert controls.on_voice is not None  # live persona switches change the TTS voice
    frame = TTSUpdateSettingsFrame(delta=DeepgramTTSService.Settings(voice="aura-2-apollo-en", speed=1.05))
    assert frame.delta.voice == "aura-2-apollo-en" and frame.delta.speed == 1.05
