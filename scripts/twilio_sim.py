#!/usr/bin/env python
"""A local stand-in for Twilio with a phone in the browser: dial the platform, or have it call you.

Spec: /build/twilio-simulator.md, /architecture/telephony.md

    python scripts/phone_demo.py --simulator          # recommended: simulator + API wired together
    cd apps/api && uv run python ../../scripts/twilio_sim.py   # the simulator alone (the API must be running)

It answers the REST calls the platform makes to Twilio (IncomingPhoneNumbers, Calls) and, for a call, plays Twilio's part towards
the platform: signed webhook, TwiML, Media Stream events with mu-law audio. Run it with the API's Python environment (fastapi,
uvicorn, httpx, websockets). Settings (environment): SIM_PORT (9200), SIM_PLATFORM_URL (http://127.0.0.1:8000), PUBLIC_BASE_URL,
TWILIO_ACCOUNT_SID (ACsimulator), TWILIO_AUTH_TOKEN (simulator-token), TWILIO_PHONE_NUMBER (+15550001111), SIM_TENANT (evergreen-care).
"""
from __future__ import annotations

import asyncio
import audioop  # Python 3.12 (the API's version); removed in 3.13
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import uuid
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law
WEBHOOK_PATH = "/api/telephony/twilio/voice"


# ------------------------------------------------------------------ pure helpers
def sign(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Twilio's request signature: Base64 HMAC-SHA1 over the URL and the sorted form fields."""
    data = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def parse_twiml(xml: str) -> dict[str, Any]:
    """What the simulator needs from TwiML: the stream URL and its parameters, a <Dial> destination, a spoken <Say>."""
    root = ElementTree.fromstring(xml)
    out: dict[str, Any] = {"stream": None, "parameters": {}, "dial": None, "say": None}
    stream = root.find("Connect/Stream")
    if stream is not None:
        out["stream"] = stream.attrib.get("url")
        out["parameters"] = {p.attrib["name"]: p.attrib.get("value", "") for p in stream.findall("Parameter")}
    dial = root.find("Dial")
    if dial is not None:
        sip = dial.find("Sip")
        out["dial"] = (sip.text if sip is not None else dial.text or "").strip()
    say = root.find("Say")
    if say is not None:
        out["say"] = say.text
    return out


def to_platform(stream_url: str, platform_url: str) -> str:
    """The stream URL names the platform's public host; the simulator talks to the platform where it actually listens."""
    parsed, base = urllib.parse.urlparse(stream_url), urllib.parse.urlparse(platform_url)
    scheme = "wss" if base.scheme == "https" else "ws"
    return f"{scheme}://{base.netloc}{parsed.path}" + (f"?{parsed.query}" if parsed.query else "")


# ------------------------------------------------------------------ the simulated Twilio
@dataclass
class Config:
    platform_url: str = "http://127.0.0.1:8000"
    public_base: str = ""
    sid: str = "ACsimulator"
    token: str = "simulator-token"
    number: str = "+15550001111"
    tenant: str = "evergreen-care"

    def __post_init__(self) -> None:
        self.platform_url = self.platform_url.rstrip("/")
        self.public_base = (self.public_base or self.platform_url).rstrip("/")


@dataclass
class Call:
    sid: str
    direction: str                      # "inbound" (the phone dialled the platform) or "outbound" (the platform dialled the phone)
    to: str
    from_: str
    status: str = "ringing"             # ringing | connected | ended | transferred | no-answer | declined
    twiml: dict[str, Any] = field(default_factory=dict)
    started: float = field(default_factory=time.time)
    note: str = ""
    platform: Any = None                # websocket to the platform's stream
    browser: Any = None                 # websocket to the browser phone
    pending: list[tuple[str, Any]] = field(default_factory=list)   # audio and events waiting for the browser
    stream_sid: str = ""
    seq: int = 0
    ulaw: bytearray = field(default_factory=bytearray)
    tasks: list[asyncio.Task[Any]] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"sid": self.sid, "direction": self.direction, "to": self.to, "from": self.from_, "status": self.status,
                "note": self.note, "started": self.started}


class Sim:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.voice_url = ""
        self.voice_method = "POST"
        self.calls: dict[str, Call] = {}
        self.http = httpx.AsyncClient(timeout=20)

    # -- calls: inbound (the phone dials the platform)
    async def dial(self, to: str, from_: str = "+15550009999") -> Call:
        params = {"CallSid": "CA" + uuid.uuid4().hex[:32], "From": from_, "To": to, "CallStatus": "ringing"}
        url = self.voice_url or self.cfg.platform_url + WEBHOOK_PATH
        public = url if self.voice_url else self.cfg.public_base + WEBHOOK_PATH
        call = Call(params["CallSid"], "inbound", to, from_)
        self.calls[call.sid] = call
        try:
            resp = await self.http.post(url if url.startswith("http") else self.cfg.platform_url + url, data=params,
                                        headers={"X-Twilio-Signature": sign(self.cfg.token, public, params)})
        except httpx.HTTPError as exc:
            return self._fail(call, f"cannot reach the platform: {exc}")
        if resp.status_code != 200:
            return self._fail(call, f"the platform answered HTTP {resp.status_code} to the voice webhook")
        call.twiml = parse_twiml(resp.text)
        if not call.twiml["stream"]:
            return self._fail(call, call.twiml.get("say") or "the platform did not connect the call")
        await self.connect(call)
        return call

    def _fail(self, call: Call, note: str) -> Call:
        call.status, call.note = "ended", note
        return call

    # -- calls: outbound (the platform dials the phone)
    async def create_outbound(self, form: dict[str, str]) -> Call:
        twiml_xml = form.get("Twiml")
        if not twiml_xml and form.get("Url"):
            params = {"CallSid": "CA" + uuid.uuid4().hex[:32], "From": form.get("From", ""), "To": form.get("To", ""), "CallStatus": "in-progress"}
            twiml_xml = (await self.http.post(form["Url"], data=params, headers={"X-Twilio-Signature": sign(self.cfg.token, form["Url"], params)})).text
        if not twiml_xml:
            raise HTTPException(400, "Calls.json needs Twiml or Url")
        call = Call("CA" + uuid.uuid4().hex[:32], "outbound", form.get("To", ""), form.get("From", ""), twiml=parse_twiml(twiml_xml))
        self.calls[call.sid] = call
        timeout = float(form.get("Timeout") or 30)
        call.tasks.append(asyncio.ensure_future(self._ring_out(call, timeout)))
        return call

    async def _ring_out(self, call: Call, timeout: float) -> None:
        await asyncio.sleep(timeout)
        if call.status == "ringing":
            call.status, call.note = "no-answer", "nobody answered"

    async def answer(self, sid: str) -> Call:
        call = self._call(sid)
        if call.status != "ringing":
            raise HTTPException(409, f"the call is {call.status}")
        if not call.twiml.get("stream"):
            return self._fail(call, "the call has nothing to connect to")
        await self.connect(call)
        return call

    async def decline(self, sid: str) -> Call:
        call = self._call(sid)
        if call.status == "ringing":
            call.status, call.note = "declined", "declined on the phone"
        return call

    # -- the Media Stream towards the platform
    async def connect(self, call: Call) -> None:
        url = to_platform(call.twiml["stream"], self.cfg.platform_url)
        call.stream_sid = "MZ" + uuid.uuid4().hex[:32]
        try:
            call.platform = await websockets.connect(url)
        except Exception as exc:  # noqa: BLE001
            self._fail(call, f"cannot open the media stream: {exc}")
            return
        call.status = "connected"
        call.started = time.time()
        await call.platform.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await call.platform.send(json.dumps({"event": "start", "streamSid": call.stream_sid, "start": {
            "streamSid": call.stream_sid, "callSid": call.sid, "accountSid": self.cfg.sid, "tracks": ["inbound"],
            "customParameters": call.twiml.get("parameters", {}),
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}}))
        call.tasks.append(asyncio.ensure_future(self._read_platform(call)))

    async def _read_platform(self, call: Call) -> None:
        try:
            async for raw in call.platform:
                msg = json.loads(raw)
                if msg.get("event") == "media":
                    await self._to_browser(call, "audio", audioop.ulaw2lin(base64.b64decode(msg["media"]["payload"]), 2))
                elif msg.get("event") == "clear":
                    await self._to_browser(call, "event", {"event": "clear"})
        except websockets.ConnectionClosed:
            pass
        if call.status == "connected":  # the platform ended the call
            call.status = "ended"
            await self._to_browser(call, "event", {"event": "ended"})

    async def _to_browser(self, call: Call, kind: str, payload: Any) -> None:
        if call.browser is None:
            call.pending.append((kind, payload))
            return
        try:
            await (call.browser.send_bytes(payload) if kind == "audio" else call.browser.send_text(json.dumps(payload)))
        except Exception:  # noqa: BLE001 - the page went away
            call.browser = None

    async def attach_browser(self, call: Call, ws: WebSocket) -> None:
        call.browser = ws
        pending, call.pending = call.pending, []
        for kind, payload in pending:
            await self._to_browser(call, kind, payload)
        if call.status in ("ended", "transferred"):
            await self._to_browser(call, "event", {"event": call.status, "note": call.note})

    async def phone_audio(self, call: Call, pcm: bytes) -> None:
        """8 kHz 16-bit audio from the phone's microphone, sent on as 20 ms mu-law media events."""
        if call.platform is None or call.status != "connected":
            return
        call.ulaw.extend(audioop.lin2ulaw(pcm, 2))
        while len(call.ulaw) >= FRAME_BYTES:
            frame, call.ulaw = bytes(call.ulaw[:FRAME_BYTES]), call.ulaw[FRAME_BYTES:]
            call.seq += 1
            try:
                await call.platform.send(json.dumps({"event": "media", "streamSid": call.stream_sid, "media": {
                    "track": "inbound", "chunk": str(call.seq), "timestamp": str(call.seq * 20), "payload": base64.b64encode(frame).decode()}}))
            except websockets.ConnectionClosed:
                return

    async def hangup(self, sid: str, note: str = "") -> Call:
        call = self._call(sid)
        if call.status == "ringing":
            call.status, call.note = "ended", note or "cancelled"
        elif call.status == "connected":
            call.status, call.note = "ended", note or "hung up"
            if call.platform is not None:
                try:
                    await call.platform.send(json.dumps({"event": "stop", "streamSid": call.stream_sid}))
                    await call.platform.close()
                except websockets.ConnectionClosed:
                    pass
            await self._to_browser(call, "event", {"event": "ended"})
        return call

    async def transfer(self, sid: str, destination: str) -> Call:
        """The platform redirected the live call (a hand-off): the media stream ends, the caller is bridged elsewhere."""
        call = self._call(sid)
        call.status, call.note = "transferred", f"transferred to {destination}"
        if call.platform is not None:
            try:
                await call.platform.close()
            except websockets.ConnectionClosed:
                pass
        await self._to_browser(call, "event", {"event": "transferred", "note": call.note})
        return call

    def _call(self, sid: str) -> Call:
        if sid not in self.calls:
            raise HTTPException(404, "unknown call")
        return self.calls[sid]


# ------------------------------------------------------------------ the web app
def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or config_from_env()
    sim = Sim(cfg)
    app = FastAPI(title="Twilio simulator")
    app.state.sim = sim
    account = f"/2010-04-01/Accounts/{cfg.sid}"

    def check_auth(request: Request) -> None:
        header = request.headers.get("authorization", "")
        expected = base64.b64encode(f"{cfg.sid}:{cfg.token}".encode()).decode()
        if header != f"Basic {expected}":
            raise HTTPException(401, "authentication failed")

    def number_row() -> dict[str, Any]:
        return {"sid": "PNsimulator", "phone_number": cfg.number, "voice_url": sim.voice_url, "voice_method": sim.voice_method}

    # -- fake Twilio REST (SIM-01, SIM-04, SIM-05)
    @app.get(account + "/IncomingPhoneNumbers.json")
    async def list_numbers(request: Request, PhoneNumber: str = "") -> dict:
        check_auth(request)
        return {"incoming_phone_numbers": [number_row()] if PhoneNumber in ("", cfg.number) else []}

    @app.post(account + "/IncomingPhoneNumbers/{pn}.json")
    async def update_number(request: Request, pn: str) -> dict:
        check_auth(request)
        if pn != "PNsimulator":
            raise HTTPException(404, "unknown number")
        form = dict((await request.form()).items())
        sim.voice_url = str(form.get("VoiceUrl", sim.voice_url))
        sim.voice_method = str(form.get("VoiceMethod", sim.voice_method))
        return number_row()

    @app.post(account + "/Calls.json", status_code=201)
    async def create_call(request: Request) -> dict:
        check_auth(request)
        call = await sim.create_outbound({k: str(v) for k, v in (await request.form()).items()})
        return {"sid": call.sid, "status": "queued", "to": call.to, "from": call.from_}

    @app.post(account + "/Calls/{sid}.json")
    async def update_call(request: Request, sid: str) -> dict:
        check_auth(request)
        form = {k: str(v) for k, v in (await request.form()).items()}
        call = sim._call(sid)
        if form.get("Twiml"):
            parsed = parse_twiml(form["Twiml"])
            if parsed["dial"]:
                await sim.transfer(sid, parsed["dial"])
        elif form.get("Status") == "completed":
            await sim.hangup(sid, "ended by the platform")
        return {"sid": call.sid, "status": call.status}

    # -- the browser phone
    @app.get("/", response_class=HTMLResponse)
    async def page() -> str:
        return PAGE.replace("__NUMBER__", cfg.number)

    @app.get("/sim/state")
    async def state() -> dict:
        calls = sorted(sim.calls.values(), key=lambda c: c.started, reverse=True)[:8]
        return {"number": cfg.number, "voice_url": sim.voice_url, "platform_url": cfg.platform_url, "calls": [c.public() for c in calls]}

    @app.post("/sim/dial")
    async def dial(request: Request) -> dict:
        body = await request.json()
        call = await sim.dial(str(body.get("to") or cfg.number), str(body.get("from") or "+15550009999"))
        return call.public()

    @app.post("/sim/answer/{sid}")
    async def answer(sid: str) -> dict:
        return (await sim.answer(sid)).public()

    @app.post("/sim/decline/{sid}")
    async def decline(sid: str) -> dict:
        return (await sim.decline(sid)).public()

    @app.post("/sim/hangup/{sid}")
    async def hangup(sid: str) -> dict:
        return (await sim.hangup(sid)).public()

    @app.get("/sim/outbound-options")
    async def outbound_options() -> Any:
        headers = {"X-Tenant-Id": cfg.tenant}
        try:
            agents = (await sim.http.get(cfg.platform_url + "/api/agents", headers=headers)).json()["items"]
            options = []
            for a in agents:
                if a.get("mode") != "outbound" or not a.get("published_version"):
                    continue
                r = await sim.http.get(cfg.platform_url + "/api/outbound/targets", params={"agent_id": a["id"]}, headers=headers)
                if r.status_code == 200:
                    options.append({"agent_id": a["id"], "agent_name": a["name"], "targets": r.json()["items"]})
            return {"options": options}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return JSONResponse({"options": [], "error": f"cannot read the platform: {exc}"})

    @app.post("/sim/outbound")
    async def outbound(request: Request) -> Any:
        body = await request.json()
        r = await sim.http.post(cfg.platform_url + "/api/phone/outbound", headers={"X-Tenant-Id": cfg.tenant},
                                json={"agent_id": body.get("agent_id"), "member_ref": body.get("member_ref"), "to": body.get("to")})
        return JSONResponse(r.json(), status_code=r.status_code)

    @app.websocket("/ws/audio/{sid}")
    async def audio(ws: WebSocket, sid: str) -> None:
        await ws.accept()
        if sid not in sim.calls:
            await ws.close(code=4404)
            return
        call = sim.calls[sid]
        await sim.attach_browser(call, ws)
        try:
            while True:
                message = await ws.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes"):
                    await sim.phone_audio(call, message["bytes"])
                elif message.get("text") and json.loads(message["text"]).get("hangup"):
                    await sim.hangup(sid)
        except WebSocketDisconnect:
            pass
        finally:
            if call.browser is ws:
                call.browser = None
            if call.status == "connected":
                await sim.hangup(sid)

    return app


def config_from_env() -> Config:
    env = os.environ
    return Config(
        platform_url=env.get("SIM_PLATFORM_URL", "http://127.0.0.1:8000"), public_base=env.get("PUBLIC_BASE_URL", ""),
        sid=env.get("TWILIO_ACCOUNT_SID") or "ACsimulator", token=env.get("TWILIO_AUTH_TOKEN") or "simulator-token",
        number=env.get("TWILIO_PHONE_NUMBER") or "+15550001111", tenant=env.get("SIM_TENANT", "evergreen-care"),
    )


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Twilio simulator - browser phone</title>
<style>
:root{--bg:#f3f6fb;--panel:#fff;--ink:#14213d;--muted:#5b6b86;--line:#d8e0ee;--accent:#0b5cad;--ok:#1f7a45;--bad:#b3261e;--warn:#9a6700}
@media (prefers-color-scheme:dark){:root{--bg:#0f1624;--panel:#18223a;--ink:#e8eefc;--muted:#9bb0d3;--line:#2b3957;--accent:#5aa2ff;--ok:#5fd08f;--bad:#ff8a80;--warn:#e3b341}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:20px 16px;display:grid;gap:16px}
h1{font-size:20px;margin:0}h2{font-size:15px;margin:0 0 10px}.muted{color:var(--muted);font-size:13px}
.grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(300px,1fr))}
.card{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:16px}
input,select{width:100%;padding:10px 12px;border:1.5px solid var(--line);border-radius:12px;background:var(--bg);color:var(--ink);font:inherit}
label{display:block;font-size:13px;color:var(--muted);margin:10px 0 4px}
button{padding:10px 18px;border-radius:999px;border:0;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}
button.ghost{background:transparent;color:var(--accent);border:1.5px solid var(--accent)}button.bad{background:var(--bad)}button.ok{background:var(--ok)}
button:disabled{opacity:.5;cursor:not-allowed}.row{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
#status{font-weight:600}.chip{display:inline-block;padding:2px 10px;border-radius:999px;border:1px solid var(--line);font-size:12px}
#incoming{display:none;border-color:var(--ok);background:color-mix(in srgb,var(--ok) 12%,var(--panel))}
table{width:100%;border-collapse:collapse;font-size:13px}td,th{text-align:left;padding:6px 4px;border-top:1px solid var(--line)}
#meter{height:6px;border-radius:3px;background:var(--line);overflow:hidden;margin-top:10px}#meter i{display:block;height:100%;width:0;background:var(--ok)}
</style></head><body><main>
<div><h1>Twilio simulator <span class="chip">browser phone</span></h1>
<div class="muted">Plays Twilio's part towards the platform. Use a headset so the agent does not hear itself. The conversation is on the platform's Calls page.</div></div>
<div class="card" id="incoming"><h2>Incoming call</h2><div id="incomingFrom"></div>
<div class="row"><button class="ok" id="answer">Answer</button><button class="bad" id="decline">Decline</button></div></div>
<div class="grid">
 <div class="card"><h2>Phone</h2>
  <label for="number">Number to dial</label><input id="number" value="__NUMBER__" inputmode="tel">
  <div class="row"><button id="call">Call</button><button id="end" class="bad" disabled>End</button><span id="status">Idle</span></div>
  <div id="meter"><i></i></div></div>
 <div class="card"><h2>Outbound: have the agent call me</h2>
  <label for="agent">Outbound agent</label><select id="agent"></select>
  <label for="target">Who to call</label><select id="target"></select>
  <label for="mine">My phone number</label><input id="mine" value="+15550009999" inputmode="tel">
  <div class="row"><button id="callme" class="ghost">Call me</button><span class="muted" id="outMsg"></span></div></div>
</div>
<div class="card"><h2>Calls</h2><table><thead><tr><th>Direction</th><th>With</th><th>Status</th><th>Note</th></tr></thead><tbody id="calls"></tbody></table></div>
</main>
<script>
const $ = id => document.getElementById(id);
let ctx, mic, node, ws, cur = null, nextT = 0, sources = [], micBuf = [], connectedAt = 0, options = [];
const j = async (path, body) => { const r = await fetch(path, {method: body === undefined ? "GET" : "POST", headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)}); return {ok: r.ok, status: r.status, data: await r.json().catch(() => ({}))}; };
const WORKLET = `class P extends AudioWorkletProcessor{process(i){const c=i[0][0];if(c)this.port.postMessage(c.slice());return true}}registerProcessor('p',P)`;
async function startAudio(sid) {
  ctx = ctx || new AudioContext();
  await ctx.resume();
  mic = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}});
  await ctx.audioWorklet.addModule(URL.createObjectURL(new Blob([WORKLET], {type: "text/javascript"})));
  node = new AudioWorkletNode(ctx, "p");
  ctx.createMediaStreamSource(mic).connect(node);
  const ratio = ctx.sampleRate / 8000; let acc = [];
  node.port.onmessage = e => {
    const f = e.data; let peak = 0;
    for (let i = 0; i < f.length; i++) peak = Math.max(peak, Math.abs(f[i]));
    $("meter").firstElementChild.style.width = Math.min(100, peak * 160) + "%";
    for (let i = 0; i < f.length; i++) acc.push(f[i]);
    while (acc.length >= ratio * 160) {   // average each group of samples down to 8 kHz, 20 ms per frame
      const out = new Int16Array(160);
      for (let k = 0; k < 160; k++) { let s = 0; const a = Math.floor(k * ratio), b = Math.floor((k + 1) * ratio); for (let m = a; m < b; m++) s += acc[m]; out[k] = Math.max(-1, Math.min(1, s / (b - a))) * 32767; }
      acc = acc.slice(Math.floor(160 * ratio));
      if (ws && ws.readyState === 1) ws.send(out.buffer);
    }
  };
  ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws/audio/" + sid);
  ws.binaryType = "arraybuffer";
  nextT = 0;
  ws.onmessage = e => {
    if (typeof e.data === "string") { const m = JSON.parse(e.data); if (m.event === "clear") flush(); else if (m.event) finish(m.event, m.note); return; }
    const pcm = new Int16Array(e.data); if (!pcm.length) return;
    const buf = ctx.createBuffer(1, pcm.length, 8000), ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 32768;
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(ctx.destination);
    nextT = Math.max(nextT, ctx.currentTime + 0.05); src.start(nextT); nextT += buf.duration;
    sources.push(src); src.onended = () => { sources = sources.filter(s => s !== src); };
    window.__bytesFromAgent = (window.__bytesFromAgent || 0) + e.data.byteLength;
  };
  ws.onclose = () => { if (cur) finish("ended"); };
}
function flush() { sources.forEach(s => { try { s.stop() } catch (e) {} }); sources = []; nextT = 0; }
function stopAudio() { flush(); try { node && node.disconnect(); mic && mic.getTracks().forEach(t => t.stop()); ws && ws.close(); } catch (e) {} node = mic = ws = null; $("meter").firstElementChild.style.width = "0"; }
function finish(kind, note) { if (!cur) return; stopAudio(); $("status").textContent = kind === "transferred" ? (note || "Transferred") : "Call ended"; cur = null; $("call").disabled = false; $("end").disabled = true; }
async function connected(call) {
  cur = call.sid; connectedAt = Date.now(); $("call").disabled = true; $("end").disabled = false; $("status").textContent = "Connected";
  try { await startAudio(call.sid); } catch (e) { $("status").textContent = "Microphone unavailable: " + e.message; }
}
$("call").onclick = async () => {
  $("status").textContent = "Calling...";
  const r = await j("/sim/dial", {to: $("number").value.trim()});
  if (r.data.status === "connected") await connected(r.data); else $("status").textContent = r.data.note || "Could not connect";
};
$("end").onclick = async () => { if (cur) { const sid = cur; finish("ended"); await j("/sim/hangup/" + sid, {}); } };
$("answer").onclick = async () => { const sid = $("incoming").dataset.sid; $("incoming").style.display = "none"; const r = await j("/sim/answer/" + sid, {}); if (r.data.status === "connected") await connected(r.data); else $("status").textContent = r.data.note || "Could not connect"; };
$("decline").onclick = async () => { const sid = $("incoming").dataset.sid; $("incoming").style.display = "none"; await j("/sim/decline/" + sid, {}); };
$("agent").onchange = () => { const o = options.find(x => x.agent_id === $("agent").value); $("target").innerHTML = (o ? o.targets : []).map(t => `<option value="${t.member_ref}">${t.first_name} - ${t.summary}</option>`).join(""); };
$("callme").onclick = async () => {
  $("outMsg").textContent = "Calling...";
  const r = await j("/sim/outbound", {agent_id: $("agent").value, member_ref: $("target").value, to: $("mine").value.trim()});
  $("outMsg").textContent = r.ok ? "Ringing - answer above" : (r.data.detail || r.data.error || "Failed");
};
async function loadOptions() {
  const r = await j("/sim/outbound-options"); options = r.data.options || [];
  $("agent").innerHTML = options.map(o => `<option value="${o.agent_id}">${o.agent_name}</option>`).join(""); $("agent").onchange();
  if (!options.length) $("outMsg").textContent = r.data.error || "No outbound agents";
}
async function poll() {
  const r = await j("/sim/state"); if (!r.ok) return;
  $("calls").innerHTML = r.data.calls.map(c => `<tr><td>${c.direction}</td><td>${c.direction === "inbound" ? c.to : c.from}</td><td>${c.status}</td><td>${c.note || ""}</td></tr>`).join("");
  const ringing = r.data.calls.find(c => c.direction === "outbound" && c.status === "ringing");
  if (ringing && !cur) { $("incoming").style.display = "block"; $("incoming").dataset.sid = ringing.sid; $("incomingFrom").textContent = "From " + ringing.from + " (Evergreen Health)"; }
  else if (!ringing) $("incoming").style.display = "none";
  if (cur) { const mine = r.data.calls.find(c => c.sid === cur); if (mine && mine.status !== "connected") finish(mine.status, mine.note); else $("status").textContent = "Connected " + Math.floor((Date.now() - connectedAt) / 1000) + " s"; }
}
loadOptions(); setInterval(poll, 1000);
</script></body></html>
"""


def main() -> None:
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=int(os.environ.get("SIM_PORT", "9200")), log_level="warning")


if __name__ == "__main__":
    main()
