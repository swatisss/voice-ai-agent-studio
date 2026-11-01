"""WebRTC transport: offer/answer behind a single-use token, TURN on Cloud Run, the end message on the data channel.

Covers: WRTC-01, WRTC-02, WRTC-03, WRTC-04
"""
from __future__ import annotations

import pytest

from voiceai.config import get_settings
from voiceai.public import auth, tokens

H = {"X-Tenant-Id": "evergreen-care"}


@pytest.fixture
def voice_env(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setenv("PUBLIC_API_SECRET", "s3cret")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://voice.example.test")
    monkeypatch.setenv("WEBRTC_STUN_URLS", "")  # no network in unit tests: host candidates only
    get_settings.cache_clear()
    auth.reset_limits()
    tokens._used.clear()
    yield
    get_settings.cache_clear()


async def client_offer() -> tuple[object, str]:
    from aiortc import RTCPeerConnection

    pc = RTCPeerConnection()
    pc.addTransceiver("audio", direction="sendrecv")
    pc.createDataChannel("control")
    await pc.setLocalDescription(await pc.createOffer())
    return pc, pc.localDescription.sdp


async def webrtc_conversation(client, seeded) -> dict:  # noqa: ANN001
    r = await client.post("/api/conversations", headers=H, json={"channel": "voice", "scope": "member", "transport": "webrtc",
                                                                 "agent_id": seeded["care"]["agent_id"]})
    assert r.status_code == 201, r.text
    return r.json()


async def test_offer_gets_an_answer_and_starts_the_conversation(client, seeded, voice_env, monkeypatch):
    """Covers: WRTC-01"""
    from voiceai import voice_calls

    started = []

    async def fake_serve(link, conv, phone=None):  # noqa: ANN001, ANN202
        started.append((type(link).__name__, conv.id))

    monkeypatch.setattr(voice_calls, "serve_conversation", fake_serve)
    body = await webrtc_conversation(client, seeded)
    connect = body["connect"]
    assert connect["offer_url"] == f"https://voice.example.test/v1/webrtc/{body['conversation_id']}/offer"
    assert connect["ice_servers"] == [] and connect["token"]
    from voiceai.config import Settings

    assert Settings.model_fields["webrtc_stun_urls"].default.startswith("stun:")  # the default STUN server (cleared here)
    pc, sdp = await client_offer()
    r = await client.post(f"/v1/webrtc/{body['conversation_id']}/offer", json={"sdp": sdp, "type": "offer"},
                          headers={"Authorization": f"Bearer {connect['token']}"})
    assert r.status_code == 200, r.text
    answer = r.json()
    assert answer["type"] == "answer" and "m=audio" in answer["sdp"]
    import asyncio

    await asyncio.sleep(0)
    assert started == [("SmallWebRTCConnection", body["conversation_id"])]
    await pc.close()


async def test_bad_tokens_are_refused(client, seeded, voice_env, monkeypatch):
    """Covers: WRTC-02"""
    from voiceai import voice_calls

    async def fake_serve(link, conv, phone=None):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(voice_calls, "serve_conversation", fake_serve)
    a, b = await webrtc_conversation(client, seeded), await webrtc_conversation(client, seeded)
    pc, sdp = await client_offer()
    url = f"/v1/webrtc/{a['conversation_id']}/offer"
    for headers in ({}, {"Authorization": f"Bearer {b['connect']['token']}"}, {"Authorization": "Bearer 1.abc"}):
        r = await client.post(url, json={"sdp": sdp}, headers=headers)
        assert r.status_code == 401 and r.json()["error"] == "invalid_token"
    assert (await client.post(url, json={"sdp": sdp}, headers={"Authorization": f"Bearer {a['connect']['token']}"})).status_code == 200
    again = await client.post(url, json={"sdp": sdp}, headers={"Authorization": f"Bearer {a['connect']['token']}"})
    assert again.status_code == 401  # single use
    await pc.close()


async def test_cloud_run_needs_turn(client, seeded, voice_env, monkeypatch):
    """Covers: WRTC-03"""
    monkeypatch.setenv("K_SERVICE", "voiceai")
    get_settings.cache_clear()
    r = await client.post("/api/conversations", headers=H, json={"channel": "voice", "scope": "member", "transport": "webrtc",
                                                                 "agent_id": seeded["care"]["agent_id"]})
    assert r.status_code == 503 and r.json()["error"] == "webrtc_unavailable"
    assert (await client.get("/healthz")).json()["webrtc"] is False
    monkeypatch.setenv("WEBRTC_TURN_URLS", "turns:turn.example.test:443?transport=tcp")
    monkeypatch.setenv("WEBRTC_TURN_USERNAME", "u")
    monkeypatch.setenv("WEBRTC_TURN_CREDENTIAL", "p")
    get_settings.cache_clear()
    assert (await client.get("/healthz")).json()["webrtc"] is True
    body = await webrtc_conversation(client, seeded)
    turn = body["connect"]["ice_servers"][-1]
    assert turn["urls"] == ["turns:turn.example.test:443?transport=tcp"] and turn["username"] == "u"


async def test_end_message_goes_over_the_data_channel():
    """Covers: WRTC-04"""
    from pipecat.frames.frames import EndFrame, OutputTransportMessageUrgentFrame

    from voiceai.voice.pipeline import CallEnder, WebRTCControl

    queued = []

    class Task:
        async def queue_frame(self, frame):  # noqa: ANN001, ANN202
            queued.append(frame)

    class Session:
        ended = None

        async def end(self, reason):  # noqa: ANN001, ANN202
            Session.ended = reason

    ender = CallEnder(Session(), WebRTCControl(), None)
    ender.task = Task()
    await ender("hangup")
    assert Session.ended == "hangup"
    assert isinstance(queued[0], OutputTransportMessageUrgentFrame) and queued[0].message == {"type": "end", "reason": "hangup"}
    assert isinstance(queued[-1], EndFrame)
