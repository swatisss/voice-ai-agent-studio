"""scripts/twilio_sim.py against a stub platform: REST, inbound dial, outbound ringing, audio bridging and hand-off.

Covers: SIM-01, SIM-02, SIM-03, SIM-04, SIM-05
"""
from __future__ import annotations

import asyncio
import audioop
import base64
import importlib.util
import json
import sys
import threading
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request, Response, WebSocket

REPO = Path(__file__).resolve().parents[3]


def _load():  # noqa: ANN202
    spec = importlib.util.spec_from_file_location("twilio_sim", REPO / "scripts" / "twilio_sim.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


sim_mod = _load()
TOKEN, SID, NUMBER = "sim-token", "ACsim", "+15550001111"
PUBLIC = "https://public.example.app"


class StubPlatform:
    """The platform's voice webhook and media stream on one local port; records what the simulator sends."""

    def __init__(self) -> None:
        self.webhooks: list[tuple[dict, str, str]] = []   # (form, signature, url the signature must cover)
        self.events: list[dict] = []
        self.sockets: list[WebSocket] = []
        self.close_after_media: int | None = None
        self.url = ""

    def app(self) -> FastAPI:
        app = FastAPI()

        @app.post("/api/telephony/twilio/voice")
        async def voice(request: Request) -> Response:
            form = {k: str(v) for k, v in (await request.form()).items()}
            self.webhooks.append((form, request.headers.get("x-twilio-signature", ""), PUBLIC + request.url.path))
            xml = (f'<Response><Connect><Stream url="wss://{PUBLIC.split("//")[1]}/api/telephony/twilio/stream/c1?token=t1">'
                   '<Parameter name="call_id" value="c1"/></Stream></Connect><Hangup/></Response>')
            return Response(xml, media_type="application/xml")

        @app.websocket("/api/telephony/twilio/stream/{call_id}")
        async def stream(ws: WebSocket, call_id: str) -> None:
            await ws.accept()
            self.sockets.append(ws)
            media = 0
            try:
                while True:
                    ev = json.loads(await ws.receive_text())
                    self.events.append(ev)
                    if ev["event"] == "media":
                        media += 1
                        if self.close_after_media and media >= self.close_after_media:
                            await ws.close()
                            return
                    if ev["event"] == "stop":
                        return
            except Exception:  # noqa: BLE001 - the simulator closed the socket
                return

        return app

    def start(self) -> None:
        server = uvicorn.Server(uvicorn.Config(self.app(), host="127.0.0.1", port=0, log_level="warning"))
        started = threading.Event()
        loop = asyncio.new_event_loop()

        def run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(server.serve())

        threading.Thread(target=run, daemon=True).start()

        def wait() -> None:
            while not (server.started and server.servers):
                threading.Event().wait(0.05)
            started.set()

        threading.Thread(target=wait, daemon=True).start()
        assert started.wait(15)
        self.url = f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
        self._server = server

    def stop(self) -> None:
        self._server.should_exit = True

    async def send(self, event: dict) -> None:
        await self.sockets[-1].send_text(json.dumps(event))


@pytest.fixture
def platform():  # noqa: ANN201
    p = StubPlatform()
    p.start()
    yield p
    p.stop()


def make_sim(platform: StubPlatform) -> sim_mod.Sim:
    return sim_mod.Sim(sim_mod.Config(platform_url=platform.url, public_base=PUBLIC, sid=SID, token=TOKEN, number=NUMBER))


async def until(cond, timeout: float = 5.0) -> None:  # noqa: ANN001
    end = asyncio.get_event_loop().time() + timeout
    while not cond():
        assert asyncio.get_event_loop().time() < end, "condition not reached in time"
        await asyncio.sleep(0.02)


class FakeBrowser:
    def __init__(self) -> None:
        self.audio: list[bytes] = []
        self.events: list[dict] = []

    async def send_bytes(self, data: bytes) -> None:
        self.audio.append(data)

    async def send_text(self, text: str) -> None:
        self.events.append(json.loads(text))


def media_event(pcm: bytes) -> dict:
    return {"event": "media", "media": {"payload": base64.b64encode(audioop.lin2ulaw(pcm, 2)).decode()}}


async def test_rest_number_listing_and_update():
    """Covers: SIM-01"""
    app = sim_mod.create_app(sim_mod.Config(sid=SID, token=TOKEN, number=NUMBER))
    auth = (SID, TOKEN)
    base = f"/2010-04-01/Accounts/{SID}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sim") as c:
        listed = (await c.get(base + "/IncomingPhoneNumbers.json", params={"PhoneNumber": NUMBER}, auth=auth)).json()["incoming_phone_numbers"]
        assert listed == [{"sid": "PNsimulator", "phone_number": NUMBER, "voice_url": "", "voice_method": "POST"}]
        assert (await c.get(base + "/IncomingPhoneNumbers.json", params={"PhoneNumber": "+15559990000"}, auth=auth)).json()["incoming_phone_numbers"] == []
        updated = await c.post(base + "/IncomingPhoneNumbers/PNsimulator.json", data={"VoiceUrl": "https://x.example/voice", "VoiceMethod": "POST"}, auth=auth)
        assert updated.json()["voice_url"] == "https://x.example/voice"
        assert (await c.get(base + "/IncomingPhoneNumbers.json", params={"PhoneNumber": NUMBER}, auth=auth)).json()["incoming_phone_numbers"][0]["voice_url"] == "https://x.example/voice"
        assert (await c.get(base + "/IncomingPhoneNumbers.json", auth=("ACsim", "wrong"))).status_code == 401
        assert (await c.post(base + "/Calls.json", data={"To": "+1", "Twiml": "<Response/>"})).status_code == 401


async def test_inbound_dial_signs_the_webhook_and_runs_the_stream(platform):
    """Covers: SIM-02"""
    sim = make_sim(platform)
    call = await sim.dial(NUMBER, "+15551112222")
    assert call.status == "connected"
    form, signature, url = platform.webhooks[0]
    assert form["To"] == NUMBER and form["From"] == "+15551112222" and form["CallSid"] == call.sid
    assert signature == sim_mod.sign(TOKEN, url, form)  # signed with the auth token over the public URL and the form
    assert url == PUBLIC + "/api/telephony/twilio/voice"
    await until(lambda: len(platform.events) >= 2)
    assert [e["event"] for e in platform.events[:2]] == ["connected", "start"]
    start = platform.events[1]["start"]
    assert start["callSid"] == call.sid and start["streamSid"].startswith("MZ") and start["customParameters"] == {"call_id": "c1"}
    await sim.hangup(call.sid)
    await until(lambda: platform.events[-1]["event"] == "stop")
    assert call.status == "ended"


async def test_audio_is_bridged_both_ways(platform):
    """Covers: SIM-03"""
    sim = make_sim(platform)
    call = await sim.dial(NUMBER)
    await until(lambda: len(platform.sockets) == 1 and len(platform.events) >= 2)
    pcm_out = b"".join((i * 100 % 8000 - 4000).to_bytes(2, "little", signed=True) for i in range(160))
    await platform.send(media_event(pcm_out))                      # agent audio before the page attached
    await until(lambda: call.pending)
    browser = FakeBrowser()
    await sim.attach_browser(call, browser)                        # flushed on attach
    assert len(browser.audio) == 1 and len(browser.audio[0]) == 320
    assert audioop.rms(audioop.add(browser.audio[0], audioop.mul(pcm_out, 2, -1), 2), 2) < 400  # mu-law round trip, close to the source
    await platform.send({"event": "clear"})
    await until(lambda: browser.events and browser.events[-1] == {"event": "clear"})
    await platform.send(media_event(pcm_out))
    await until(lambda: len(browser.audio) == 2)
    mic = b"\x10\x20" * 200                                        # 200 samples: one 20 ms frame and 40 samples left over
    await sim.phone_audio(call, mic)
    await until(lambda: sum(e["event"] == "media" for e in platform.events) == 1)
    await sim.phone_audio(call, b"\x10\x20" * 120)                 # 40 + 120 = 160: a second frame
    await until(lambda: sum(e["event"] == "media" for e in platform.events) == 2)
    frames = [e for e in platform.events if e["event"] == "media"]
    assert all(len(base64.b64decode(f["media"]["payload"])) == 160 and f["streamSid"] == call.stream_sid for f in frames)
    assert [f["media"]["chunk"] for f in frames] == ["1", "2"]
    await sim.hangup(call.sid)


TWIML_STREAM = (f'<Response><Connect><Stream url="wss://{PUBLIC.split("//")[1]}/api/telephony/twilio/stream/c1?token=t1">'
                '<Parameter name="call_id" value="c1"/></Stream></Connect><Hangup/></Response>')


async def test_outbound_call_rings_and_can_be_answered_declined_or_missed(platform):
    """Covers: SIM-04"""
    sim = make_sim(platform)
    a = await sim.create_outbound({"To": "+15559999999", "From": NUMBER, "Twiml": TWIML_STREAM, "Timeout": "30"})
    assert a.status == "ringing" and (a.to, a.from_) == ("+15559999999", NUMBER) and a.direction == "outbound"
    await sim.answer(a.sid)
    assert a.status == "connected"
    await until(lambda: len(platform.events) >= 2)
    assert platform.events[1]["start"]["callSid"] == a.sid and platform.events[1]["start"]["customParameters"] == {"call_id": "c1"}
    await sim.hangup(a.sid)
    b = await sim.create_outbound({"To": "+15559999999", "From": NUMBER, "Twiml": TWIML_STREAM})
    await sim.decline(b.sid)
    assert b.status == "declined" and len(platform.sockets) == 1  # nothing was opened for it
    c = await sim.create_outbound({"To": "+15559999999", "From": NUMBER, "Twiml": TWIML_STREAM, "Timeout": "0.2"})
    await asyncio.sleep(0.5)
    assert c.status == "no-answer"
    with pytest.raises(Exception, match="409|ringing|declined"):
        await sim.answer(b.sid)  # no longer ringing


async def test_transfer_hangup_and_platform_close(platform):
    """Covers: SIM-05"""
    app = sim_mod.create_app(sim_mod.Config(platform_url=platform.url, public_base=PUBLIC, sid=SID, token=TOKEN, number=NUMBER))
    sim: sim_mod.Sim = app.state.sim
    base, auth = f"/2010-04-01/Accounts/{SID}", (SID, TOKEN)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://sim") as c:
        call = await sim.dial(NUMBER)
        browser = FakeBrowser()
        await sim.attach_browser(call, browser)
        await until(lambda: len(platform.events) >= 2)
        r = await c.post(base + f"/Calls/{call.sid}.json", data={"Twiml": "<Response><Dial>+15557654321</Dial></Response>"}, auth=auth)
        assert r.json()["status"] == "transferred" and call.note == "transferred to +15557654321"
        await until(lambda: browser.events and browser.events[-1]["event"] == "transferred")

        second = await sim.dial(NUMBER)
        await sim.attach_browser(second, FakeBrowser())
        await until(lambda: len(platform.sockets) == 2)
        done = await c.post(base + f"/Calls/{second.sid}.json", data={"Status": "completed"}, auth=auth)
        assert done.json()["status"] == "ended"

        platform.close_after_media = 1                              # the platform ends the call from its side
        third = await sim.dial(NUMBER)
        ended = FakeBrowser()
        await sim.attach_browser(third, ended)
        await until(lambda: len(platform.sockets) == 3 and len(platform.events) >= 2)
        await sim.phone_audio(third, b"\x10\x20" * 160)
        await until(lambda: third.status == "ended")
        await until(lambda: ended.events and ended.events[-1]["event"] == "ended")
        assert (await c.post(base + "/Calls/CAunknown.json", data={"Status": "completed"}, auth=auth)).status_code == 404


def test_twiml_and_url_helpers():
    """Covers: SIM-02, SIM-05"""
    parsed = sim_mod.parse_twiml(TWIML_STREAM)
    assert parsed["stream"].endswith("token=t1") and parsed["parameters"] == {"call_id": "c1"} and parsed["dial"] is None
    assert sim_mod.parse_twiml("<Response><Dial><Sip>sip:a@b.example</Sip></Dial></Response>")["dial"] == "sip:a@b.example"
    assert sim_mod.parse_twiml("<Response><Say>Sorry, this number is not in service.</Say><Hangup/></Response>")["say"].startswith("Sorry")
    assert sim_mod.to_platform("wss://public.example.app/api/x?token=t", "http://127.0.0.1:8000") == "ws://127.0.0.1:8000/api/x?token=t"
    assert sim_mod.to_platform("wss://public.example.app/api/x", "https://app.example.com") == "wss://app.example.com/api/x"
