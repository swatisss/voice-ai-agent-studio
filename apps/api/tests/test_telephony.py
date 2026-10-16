"""Twilio phone channel: number mapping, webhook, signatures, media stream, IVR context and transfer.

Covers: TEL-01, TEL-02, TEL-03, TEL-04, TEL-05, TEL-06, TEL-07, TEL-08, TEL-10, TEL-11
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree

import httpx
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voiceai import telephony

H = {"X-Tenant-Id": "evergreen-care"}
TOKEN = "twilio-test-token"
BASE = "https://abc123.ngrok.test"
NUMBER = "+15550001111"
CALLER = "+15551234567"
VOICE = "/api/telephony/twilio/voice"


@pytest.fixture
def phone(app, tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """A running app with a seeded temp database, Twilio credentials, an OpenAI key and the claims agent mapped to NUMBER."""
    db_path = tmp_path / "phone.db"
    for key, value in {
        "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}", "AUTO_SEED": "1", "TWILIO_AUTH_TOKEN": TOKEN,
        "TWILIO_ACCOUNT_SID": "ACtest", "PUBLIC_BASE_URL": BASE, "OPENAI_API_KEY": "sk-test", "DEEPGRAM_API_KEY": "dg-test",
    }.items():
        monkeypatch.setenv(key, value)
    from voiceai.config import get_settings
    from voiceai.llm.gateway import reset_gateway

    get_settings.cache_clear()
    reset_gateway()
    with TestClient(app) as client:
        agents = {a["name"]: a["id"] for a in client.get("/api/agents", headers=H).json()["items"]}
        r = client.post("/api/phone-numbers", headers=H, json={"e164": NUMBER, "agent_id": agents["Insurance Claims Agent"]})
        assert r.status_code == 200, r.text
        yield SimpleNamespace(client=client, agents=agents, db=db_path, number_id=r.json()["id"])
    get_settings.cache_clear()
    reset_gateway()


def signed_post(client, params: dict[str, str], path: str = VOICE, query: str = "", sign: bool = True, url: str | None = None):  # noqa: ANN001, ANN202
    full = BASE + path + (f"?{query}" if query else "")
    headers = {"X-Twilio-Signature": telephony.compute_signature(TOKEN, url or full, {k: [v] for k, v in params.items()})} if sign else {}
    return client.post(path + (f"?{query}" if query else ""), data=params, headers=headers)


def call_params(to: str = NUMBER, **extra: str) -> dict[str, str]:
    return {"CallSid": "CA123", "From": CALLER, "To": to, "CallStatus": "ringing", **extra}


def rows(phone, sql: str, *args):  # noqa: ANN001, ANN202
    con = sqlite3.connect(phone.db)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


def stream_of(twiml: str) -> tuple[str, str]:
    root = ElementTree.fromstring(twiml)
    url = root.find("Connect/Stream").attrib["url"]  # type: ignore[union-attr]
    return url, root.find("Connect/Stream/Parameter").attrib["value"]  # type: ignore[union-attr]


def test_webhook_creates_the_call_and_answers_with_a_stream(phone):
    """Covers: TEL-01"""
    r = signed_post(phone.client, call_params())
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    root = ElementTree.fromstring(r.text)
    assert [child.tag for child in root] == ["Connect", "Hangup"]
    url, call_id = stream_of(r.text)
    parsed = urlparse(url)
    assert parsed.scheme == "wss" and parsed.netloc == "abc123.ngrok.test" and parsed.path == f"/api/telephony/twilio/stream/{call_id}"
    assert parse_qs(parsed.query)["token"][0]
    (channel, direction, status, agent_version, meta), = rows(phone, "select channel, direction, status, agent_version_id, meta from calls where id=?", call_id)
    assert (channel, direction, status) == ("voice", "inbound", "active") and agent_version
    telephony_meta = json.loads(meta)["telephony"]
    assert telephony_meta == {"provider": "twilio", "call_sid": "CA123", "from_last4": "4567", "to": NUMBER}
    assert CALLER not in meta and "5551234567" not in meta
    detail = phone.client.get(f"/api/calls/{call_id}", headers=H).json()
    assert detail["transport"] == "phone" and detail["telephony"]["to"] == NUMBER
    assert phone.client.get("/api/calls", headers=H).json()["items"][0]["transport"] == "phone"


def test_signature_is_required_and_bound_to_the_public_url(phone):
    """Covers: TEL-02"""
    count = lambda: rows(phone, "select count(*) from calls where meta like '%twilio%'")[0][0]  # noqa: E731
    assert signed_post(phone.client, call_params(), sign=False).status_code == 403
    assert signed_post(phone.client, call_params(), url="https://other.example/api/telephony/twilio/voice").status_code == 403
    bad = phone.client.post(VOICE, data=call_params(), headers={"X-Twilio-Signature": "AAAA"})
    assert bad.status_code == 403 and count() == 0
    assert signed_post(phone.client, call_params()).status_code == 200 and count() == 1
    tampered = phone.client.post(VOICE, data={**call_params(), "To": "+15559998888"},
                                 headers={"X-Twilio-Signature": telephony.compute_signature(TOKEN, BASE + VOICE, {k: [v] for k, v in call_params().items()})})
    assert tampered.status_code == 403


def not_in_service(r) -> bool:  # noqa: ANN001
    root = ElementTree.fromstring(r.text)
    return r.status_code == 200 and [c.tag for c in root] == ["Say", "Hangup"] and "not in service" in (root.find("Say").text or "")  # type: ignore[union-attr]


def test_unroutable_calls_hear_not_in_service(phone, monkeypatch):
    """Covers: TEL-03"""
    from voiceai.config import get_settings
    from voiceai.llm.gateway import reset_gateway

    count = lambda: rows(phone, "select count(*) from calls")[0][0]  # noqa: E731
    before = count()
    assert not_in_service(signed_post(phone.client, call_params(to="+15559990000")))  # unmapped
    outbound = phone.agents["Renewal Outreach Agent"]
    phone.client.post("/api/phone-numbers", headers=H, json={"e164": "+15550002222", "agent_id": outbound})
    assert not_in_service(signed_post(phone.client, call_params(to="+15550002222")))  # outbound agents do not answer
    draft = phone.client.post("/api/agents", headers=H, json={"name": "Unpublished", "description": ""}).json()["id"]
    phone.client.post("/api/phone-numbers", headers=H, json={"e164": "+15550003333", "agent_id": draft})
    assert not_in_service(signed_post(phone.client, call_params(to="+15550003333")))  # not published
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    reset_gateway()
    assert not_in_service(signed_post(phone.client, call_params()))  # realtime agent without an OpenAI key
    assert count() == before


def test_ivr_parameters_become_context_but_never_verification(phone):
    """Covers: TEL-05"""
    extra = {f"ivr_extra{i}": str(i) for i in range(12)}
    r = signed_post(phone.client, call_params(ivr_lang="en", foo="bar", ivr_long="x" * 500, **{"SipHeader_X-IVR-Account": "gold"}, **extra), query="ivr_menu=claims")
    assert r.status_code == 200
    _, call_id = stream_of(r.text)
    (meta,), = rows(phone, "select meta from calls where id=?", call_id)
    ctx = json.loads(meta)["context"]
    assert ctx["ivr_menu"] == "claims" and ctx["ivr_lang"] == "en" and ctx["ivr_account"] == "gold" and "foo" not in ctx
    assert len(ctx) == 10 and all(len(v) <= 200 for v in ctx.values())
    assert json.loads(meta).get("state", {}).get("verified_member_ref") is None

    import asyncio

    from voiceai.runtime.prompt import mode_instructions

    text = mode_instructions("inbound", {"ivr_menu": "claims", "ivr_lang": "en"})
    assert "- ivr_menu: claims" in text and "- ivr_lang: en" in text and "never proves who the caller is" in text
    assert "(no context)" in mode_instructions("inbound", {})
    del asyncio


def ws_url(twiml: str) -> str:
    url, _ = stream_of(twiml)
    return url.replace("wss://abc123.ngrok.test", "")


def test_stream_accepts_only_the_call_bound_single_use_token(phone, monkeypatch):
    """Covers: TEL-04"""
    from voiceai.voice import pipeline

    seen: list = []

    async def fake_run_realtime(websocket, session, controls, connector, phone=None):  # noqa: ANN001, ANN202
        seen.append(("realtime", phone.stream_sid, phone.call_sid, phone.parameters))

    monkeypatch.setattr(pipeline, "run_realtime", fake_run_realtime)
    r = signed_post(phone.client, call_params())
    url = ws_url(r.text)
    path, query = url.split("?")
    _, call_id = stream_of(r.text)
    start = json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "CA123", "customParameters": {"call_id": call_id}}})

    def attempt(target: str, send_start: bool = True):  # noqa: ANN202
        with phone.client.websocket_connect(target) as ws:
            if send_start:
                ws.send_text(json.dumps({"event": "connected"}))
                ws.send_text(start)
            ws.receive_text()

    for bad in (path, path + "?token=nope", path + "?token=" + str(int(time.time()) - 5) + ".deadbeef"):
        with pytest.raises(WebSocketDisconnect) as exc:
            attempt(bad)
        assert exc.value.code == 4401
    other = signed_post(phone.client, call_params())
    other_path = ws_url(other.text).split("?")[0]
    with pytest.raises(WebSocketDisconnect) as exc:  # a token minted for another call
        attempt(other_path + "?" + query)
    assert exc.value.code == 4401
    with pytest.raises(WebSocketDisconnect) as exc:  # valid token: the pipeline starts on the Twilio `start` event
        attempt(url)
    assert exc.value.code == 1000 and seen == [("realtime", "MZ1", "CA123", {"call_id": call_id})]
    with pytest.raises(WebSocketDisconnect) as exc:  # used once
        attempt(url)
    assert exc.value.code == 4401
    ghost = "0" * 32
    token = telephony.mint_token(TOKEN, ghost)
    with pytest.raises(WebSocketDisconnect) as exc:  # unknown call with a valid token
        attempt(f"/api/telephony/twilio/stream/{ghost}?token={token}")
    assert exc.value.code == 4404


def test_phone_call_end_closes_normally_without_feedback(phone, monkeypatch):
    """Covers: TEL-11"""
    from voiceai.voice import pipeline

    async def ends_idle(websocket, session, controls, connector, phone=None):  # noqa: ANN001, ANN202
        await session.end("idle")

    monkeypatch.setattr(pipeline, "run_realtime", ends_idle)
    r = signed_post(phone.client, call_params())
    _, call_id = stream_of(r.text)
    with pytest.raises(WebSocketDisconnect) as exc:
        with phone.client.websocket_connect(ws_url(r.text)) as ws:
            ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ2", "callSid": "CA123"}}))
            ws.receive_text()
    assert exc.value.code == 1000
    assert rows(phone, "select end_reason, status from calls where id=?", call_id) == [("idle", "ended")]
    assert rows(phone, "select count(*) from call_feedback where call_id=?", call_id) == [(0,)]


async def test_phone_serializer_speaks_mulaw_and_twilio_events():
    """Covers: TEL-06"""
    from pipecat.audio.utils import ulaw_to_pcm
    from pipecat.frames.frames import (
        InputAudioRawFrame, InputTransportMessageFrame, InterruptionFrame, OutputAudioRawFrame, OutputTransportMessageUrgentFrame,
    )

    from voiceai.voice.phone import PhoneSerializer

    ser = PhoneSerializer("MZ9", "CA9")
    await ser.setup(SimpleNamespace(audio_in_sample_rate=16000))
    tone = bytes([0x7F, 0x80]) * 80  # 20 ms of mu-law at 8 kHz
    media = json.dumps({"event": "media", "media": {"payload": base64.b64encode(tone).decode()}})
    frames = [await ser.deserialize(media) for _ in range(12)]  # the stream resampler hands audio on in bursts
    frame = next(f for f in frames if f is not None)
    assert isinstance(frame, InputAudioRawFrame) and frame.sample_rate == 16000 and len(frame.audio) >= 600
    stop = await ser.deserialize(json.dumps({"event": "stop"}))
    assert isinstance(stop, InputTransportMessageFrame) and stop.message == {"type": "hangup"}
    assert await ser.deserialize(json.dumps({"event": "mark"})) is None
    sent = [await ser.serialize(OutputAudioRawFrame(audio=b"\x00\x10" * 480, sample_rate=24000, num_channels=1)) for _ in range(12)]
    out = json.loads(next(m for m in sent if m is not None))
    assert out["event"] == "media" and out["streamSid"] == "MZ9" and base64.b64decode(out["media"]["payload"])
    assert json.loads(await ser.serialize(InterruptionFrame())) == {"event": "clear", "streamSid": "MZ9"}
    assert await ser.serialize(OutputTransportMessageUrgentFrame(message={"type": "ready"})) is None
    del ulaw_to_pcm


class _Stub:
    """Twilio REST double: records requests and answers with a status."""

    def __init__(self, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status, json={})

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _phone_session(transfer_to: str | None, escalated: bool = True):  # noqa: ANN202
    events: list[tuple] = []

    async def _event(kind, text=None, data=None):  # noqa: ANN001, ANN202
        events.append((kind, text, data))

    return SimpleNamespace(config={"telephony": {"transfer_to": transfer_to}}, state=SimpleNamespace(escalated=escalated), _event=_event), events


async def test_hand_off_redirects_the_live_call(monkeypatch):
    """Covers: TEL-07"""
    from voiceai.config import get_settings

    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", TOKEN)
    get_settings.cache_clear()
    try:
        ok = _Stub()
        session, events = _phone_session("+15557654321")
        await telephony.on_phone_end(session, "handoff", "CA123", ok.client())
        assert len(ok.requests) == 1
        req = ok.requests[0]
        assert req.url.path == "/2010-04-01/Accounts/ACtest/Calls/CA123.json" and req.method == "POST"
        body = parse_qs(req.content.decode())
        assert body["Twiml"] == ["<?xml version=\"1.0\" encoding=\"UTF-8\"?><Response><Dial>+15557654321</Dial></Response>"]
        assert events[-1][2]["transfer"]["ok"] is True

        sip = _Stub()
        session, _ = _phone_session("sip:claims@example.com")
        await telephony.on_phone_end(session, "handoff", "CA123", sip.client())
        assert "<Dial><Sip>sip:claims@example.com</Sip></Dial>" in parse_qs(sip.requests[0].content.decode())["Twiml"][0]

        failing = _Stub(500)
        session, events = _phone_session("+15557654321")
        await telephony.on_phone_end(session, "handoff", "CA123", failing.client())  # never raises
        assert len(failing.requests) == 1 and events[-1][0] == "system" and events[-1][2]["transfer"]["ok"] is False

        for transfer_to, escalated in ((None, True), ("+15557654321", False)):
            idle = _Stub()
            session, events = _phone_session(transfer_to, escalated)
            await telephony.on_phone_end(session, "handoff", "CA123", idle.client())
            assert idle.requests == [] and events == []
    finally:
        get_settings.cache_clear()


def test_phone_number_api(phone):
    """Covers: TEL-08"""
    c = phone.client
    listed = c.get("/api/phone-numbers", headers=H).json()["items"]
    assert [(n["e164"], n["agent_name"]) for n in listed] == [(NUMBER, "Insurance Claims Agent")]
    assert c.post("/api/phone-numbers", headers=H, json={"e164": NUMBER, "agent_id": phone.agents["Customer Care Agent"]}).json()["error"] == "number_in_use"
    for bad in ("5551234", "+0123456789", "+1 555 123 4567", "+1"):
        assert c.post("/api/phone-numbers", headers=H, json={"e164": bad, "agent_id": phone.agents["Customer Care Agent"]}).status_code == 422, bad
    assert c.post("/api/phone-numbers", headers=H, json={"e164": "+15550004444", "agent_id": "nope"}).status_code == 422
    sandbox = {"X-Tenant-Id": "evergreen-sandbox"}
    assert c.get("/api/phone-numbers", headers=sandbox).json()["items"] == []
    assert c.delete(f"/api/phone-numbers/{phone.number_id}", headers=sandbox).status_code == 404
    assert c.post("/api/phone-numbers", headers=sandbox, json={"e164": "+15550005555", "agent_id": phone.agents["Customer Care Agent"]}).status_code == 422  # other tenant's agent
    assert signed_post(c, call_params()).text.count("<Connect>") == 1
    assert c.delete(f"/api/phone-numbers/{phone.number_id}", headers=H).status_code == 204
    assert not_in_service(signed_post(c, call_params()))


def test_signature_switch_and_missing_token(phone, monkeypatch):
    """Covers: TEL-10"""
    from voiceai.config import get_settings

    monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "0")
    monkeypatch.delenv("K_SERVICE", raising=False)
    get_settings.cache_clear()
    telephony.assert_safe_settings()  # allowed off Cloud Run
    assert signed_post(phone.client, call_params(), sign=False).status_code == 200  # unsigned accepted, with a warning in the log
    monkeypatch.setenv("K_SERVICE", "voiceai")
    with pytest.raises(RuntimeError, match="Cloud Run"):
        telephony.assert_safe_settings()
    from voiceai.main import create_app

    with pytest.raises(RuntimeError):
        create_app()  # the routes refuse to start
    monkeypatch.delenv("K_SERVICE")
    monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "1")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    get_settings.cache_clear()
    assert not_in_service(signed_post(phone.client, call_params(), sign=False))
    assert phone.client.get("/healthz").json()["providers"]["twilio"] is False
    get_settings.cache_clear()


def test_stream_token_helpers():
    """Covers: TEL-04"""
    token = telephony.mint_token("k", "call1", now=1000)
    assert not telephony.consume_token("k", "call2", token, now=1001)
    assert not telephony.consume_token("other", "call1", token, now=1001)
    assert not telephony.consume_token("k", "call1", token, now=1000 + telephony.TOKEN_TTL_S + 1)
    assert telephony.consume_token("k", "call1", token, now=1001) and not telephony.consume_token("k", "call1", token, now=1002)


# ---------------------------------------------------------------- the whole phone path against a scripted Realtime service
class ScriptedRealtime:
    """A local stand-in for the OpenAI Realtime WebSocket, run on its own thread. Records what the platform sent."""

    def __init__(self) -> None:
        self.log: list[dict] = []
        self.url = ""
        self.replied = False  # the scripted caller turn was answered
        self._loop = None
        self._done = None  # set on the server thread

    def start(self) -> None:
        import asyncio
        import threading

        started = threading.Event()

        async def handler(ws):  # noqa: ANN001, ANN202
            tone = base64.b64encode(b"\x10\x20" * 2400).decode()
            n, heard, spoke = 0, 0, False

            async def say(text: str, exact: bool) -> None:
                nonlocal n
                n += 1
                rid = f"r{n}"
                created = {"id": rid, **({"metadata": {"kind": "exact", "text": text}} if exact else {})}
                await ws.send(json.dumps({"type": "response.created", "response": created}))
                for _ in range(4):
                    await ws.send(json.dumps({"type": "response.output_audio.delta", "response_id": rid, "item_id": f"i{rid}", "delta": tone}))
                    await asyncio.sleep(0.03)
                await ws.send(json.dumps({"type": "response.output_audio_transcript.delta", "response_id": rid, "delta": text}))
                await ws.send(json.dumps({"type": "response.done", "response": {"id": rid, "status": "completed", "usage": {"input_tokens": 100, "output_tokens": 50}}}))

            async for raw in ws:
                ev = json.loads(raw)
                self.log.append(ev)
                if ev["type"] == "response.create":
                    meta = (ev.get("response") or {}).get("metadata")
                    asyncio.ensure_future(say(meta["text"] if meta else "Let me check on that claim.", bool(meta)))
                elif ev["type"] == "input_audio_buffer.append":
                    heard += len(ev["audio"])
                    welcome_over = sum(1 for e in self.log if e["type"] == "session.update") >= 3  # configured, welcome-protected, welcome over
                    if heard > 60000 and not spoke and welcome_over:
                        spoke = self.replied = True
                        await ws.send(json.dumps({"type": "input_audio_buffer.speech_started"}))
                        await ws.send(json.dumps({"type": "input_audio_buffer.speech_stopped"}))
                        asyncio.ensure_future(say("Let me check on that claim.", False))
                        await ws.send(json.dumps({"type": "conversation.item.input_audio_transcription.completed", "transcript": "I want to check on a claim."}))

        def run() -> None:
            import websockets.asyncio.server as srv

            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def main() -> None:
                self._done = asyncio.Event()
                async with srv.serve(handler, "127.0.0.1", 0) as server:
                    self.url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
                    started.set()
                    await self._done.wait()

            self._loop.run_until_complete(main())
            self._loop.close()

        threading.Thread(target=run, daemon=True).start()
        assert started.wait(10)

    def stop(self) -> None:
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._done.set)


@pytest.fixture
def provider(monkeypatch):  # noqa: ANN001, ANN201
    scripted = ScriptedRealtime()
    scripted.start()
    monkeypatch.setenv("OPENAI_REALTIME_URL", scripted.url)
    yield scripted
    scripted.stop()


def test_phone_call_runs_end_to_end_through_the_pipeline(provider, phone):
    """Covers: TEL-01, TEL-04, TEL-06, RV-02"""
    from voiceai.config import get_settings

    get_settings.cache_clear()
    r = signed_post(phone.client, call_params(), query="ivr_menu=claims")
    _, call_id = stream_of(r.text)
    media_in = json.dumps({"event": "media", "streamSid": "MZe2e", "media": {"payload": base64.b64encode(bytes([0x7F, 0x80]) * 80).decode()}})
    # the test client may cancel the server task while it finishes cleaning up after the hang-up: both outcomes are a normal end
    with pytest.raises((WebSocketDisconnect, concurrent.futures.CancelledError)):
        with phone.client.websocket_connect(ws_url(r.text)) as ws:
            ws.send_text(json.dumps({"event": "connected"}))
            ws.send_text(json.dumps({"event": "start", "streamSid": "MZe2e", "start": {"streamSid": "MZe2e", "callSid": "CA123", "customParameters": {}}}))
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                ws.send_text(media_in)  # the caller talks
                time.sleep(0.02)
                if provider.replied:
                    break
            time.sleep(1.5)
            ws.send_text(json.dumps({"event": "stop", "streamSid": "MZe2e"}))
            while True:
                message = json.loads(ws.receive_text())
                assert message["event"] in ("media", "clear") and message.get("streamSid") == "MZe2e"
    kinds = [e["type"] for e in provider.log]
    assert kinds[0] == "session.update" and kinds.count("response.create") >= 1  # configured, welcome requested
    welcome = next(e for e in provider.log if e["type"] == "response.create")
    assert "Thank you for calling Evergreen Health claims, this is Nora." in welcome["response"]["instructions"]
    assert any("ivr_menu: claims" in e["session"]["instructions"] for e in provider.log if e["type"] == "session.update")
    detail = phone.client.get(f"/api/calls/{call_id}", headers=H).json()
    assert detail["transport"] == "phone" and detail["end_reason"] == "hangup" and detail["status"] == "ended"
    spoken = [(e["kind"], e["text"]) for e in detail["events"] if e["kind"] in ("user", "assistant")]
    assert spoken[0][0] == "assistant" and ("user", "I want to check on a claim.") in spoken and spoken[-1] == ("assistant", "Let me check on that claim.")
    assert detail["tokens_in"] > 0 and detail["llm_cost_usd"] > 0
