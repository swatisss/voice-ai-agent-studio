#!/usr/bin/env python
"""Replay a phone call against a running API without a Twilio account.

Spec: /architecture/telephony.md (Local verification), /build/runbook-phone.md

It signs a Twilio voice webhook with TWILIO_AUTH_TOKEN, follows the returned TwiML to the media-stream WebSocket,
plays a WAV file (or a short tone) as mu-law `media` events in real time, prints what comes back and writes the
agent's audio to a WAV file. Run it with the API's environment (it needs httpx and websockets):

    cd apps/api && uv run python ../../scripts/fake_twilio.py --to +15550001111 [--wav your.wav] [--ivr menu=claims]

The API needs TWILIO_AUTH_TOKEN and PUBLIC_BASE_URL (for a local run: http://localhost:8000) in apps/api/.env, the
number mapped to an agent (`uv run voiceai phone add`), and the provider keys the agent's pipeline uses.

Handover mode (/architecture/phone-warm-handover.md, CP-0051) replays Twilio's handover callbacks for an escalated call whose
agent uses `conference` mode, with no network beyond the API itself: the specialist leg ringing, the conference join of the
specialist, a completed two-channel recording and the end of the conference. The `transcribe_handover` job then needs a
recording Twilio actually holds, so against a real server only the events up to the recording row are produced:

    cd apps/api && uv run python ../../scripts/fake_twilio.py --handover <call_id> [--leg CA...]

WhatsApp mode (/architecture/whatsapp-channel.md, CP-0052) posts signed inbound messages and delivery receipts to a running API,
no network beyond the API itself. The reply to the user goes out through Twilio's REST API, so without credentials it is only logged:

    cd apps/api && uv run python ../../scripts/fake_twilio.py --whatsapp "What is my excess?" [--wa-user whatsapp:+447700900123]
    cd apps/api && uv run python ../../scripts/fake_twilio.py --whatsapp-receipt SM... --state delivered
"""
from __future__ import annotations

import argparse
import asyncio
import audioop  # Python 3.12 (the API's version); removed in 3.13
import base64
import hashlib
import hmac
import json
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
import websockets

ROOT = Path(__file__).resolve().parent.parent
FRAME_BYTES = 160  # 20 ms of 8 kHz mu-law


def dotenv(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / "apps" / "api" / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name and value.strip():
                return value.strip().strip("\"'")
    return None


def signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    data = url + "".join(k + v for k, v in sorted(params.items()))
    return base64.b64encode(hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def mulaw_from_wav(path: Path | None) -> bytes:
    """8 kHz mono mu-law from a WAV file; without a file, one second of a 440 Hz tone."""
    if path is None:
        pcm = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * 440 * i / 8000))) for i in range(8000))
        return audioop.lin2ulaw(pcm, 2)
    with wave.open(str(path), "rb") as wav:
        frames, width, channels, rate = wav.readframes(wav.getnframes()), wav.getsampwidth(), wav.getnchannels(), wav.getframerate()
    if channels == 2:
        frames = audioop.tomono(frames, width, 0.5, 0.5)
    if rate != 8000:
        frames, _ = audioop.ratecv(frames, width, 1, rate, 8000, None)
    return audioop.lin2ulaw(frames, width)


async def replay_handover(args: argparse.Namespace, token: str, public: str) -> int:
    """CP-0051: signed handover callbacks for one call: specialist ringing, joined, a two-channel recording, end of conference."""
    steps = [
        ("specialist", {"CallSid": args.leg, "CallStatus": "ringing"}),
        ("conference", {"StatusCallbackEvent": "participant-join", "ParticipantLabel": "specialist", "CallSid": args.leg}),
        ("recording", {"RecordingSid": "REfake" + str(int(time.time())), "RecordingStatus": "completed", "RecordingChannels": "2",
                       "RecordingDuration": "20", "CallSid": args.leg}),
        ("conference", {"StatusCallbackEvent": "conference-end"}),
    ]
    async with httpx.AsyncClient(timeout=20) as client:
        for kind, params in steps:
            path = f"/api/telephony/twilio/handover/{kind}/{args.handover}"
            sig = signature(token, public + path, params)
            r = await client.post(args.base.rstrip("/") + path, data=params, headers={"X-Twilio-Signature": sig})
            print(f"{kind} {params.get('StatusCallbackEvent') or params.get('CallStatus') or params.get('RecordingStatus')} -> HTTP {r.status_code}")
            if r.status_code != 200:
                print(r.text)
                return 1
    print("open the call in the Calls page: Specialist call appears once the recording is transcribed")
    return 0


async def replay_whatsapp(args: argparse.Namespace, token: str, public: str) -> int:
    """CP-0052: one signed inbound WhatsApp message, or one signed delivery receipt (From is the sender, To the user)."""
    if args.whatsapp_receipt:
        path = "/api/channels/twilio/whatsapp/status"
        params = {"MessageSid": args.whatsapp_receipt, "MessageStatus": args.state, "From": args.wa_sender, "To": args.wa_user}
    else:
        path = "/api/channels/twilio/whatsapp/inbound"
        params = {"MessageSid": "SMfake" + str(int(time.time() * 1000)), "From": args.wa_user, "To": args.wa_sender, "Body": args.whatsapp,
                  "NumMedia": "0", "ProfileName": "Fake User"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(args.base.rstrip("/") + path, data=params, headers={"X-Twilio-Signature": signature(token, public + path, params)})
    print(f"{path} -> HTTP {r.status_code}")
    return 0 if r.status_code == 200 else 1


async def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:8000", help="where the API listens")
    p.add_argument("--to", default=None, help="the dialled number, as mapped with `voiceai phone add`")
    p.add_argument("--handover", metavar="CALL_ID", default=None, help="replay the handover callbacks of this call instead of placing a call")
    p.add_argument("--leg", default="CAfakeleg1", help="the specialist leg's CallSid used by --handover")
    p.add_argument("--whatsapp", metavar="TEXT", default=None, help="post this WhatsApp message from --wa-user to --wa-sender")
    p.add_argument("--whatsapp-receipt", metavar="MESSAGE_SID", default=None, help="post a delivery receipt for this message")
    p.add_argument("--state", default="delivered", help="receipt status for --whatsapp-receipt (sent, delivered, read, failed)")
    p.add_argument("--wa-user", default="whatsapp:+447700900123", help="the WhatsApp user (a made-up number)")
    p.add_argument("--wa-sender", default="whatsapp:+14155238886", help="the sender as mapped with `voiceai whatsapp add`")
    p.add_argument("--from", dest="caller", default="+15550009999")
    p.add_argument("--wav", type=Path, default=None, help="caller audio; default: a one second tone")
    p.add_argument("--ivr", action="append", default=[], metavar="NAME=VALUE", help="IVR context, sent as ivr_<name>")
    p.add_argument("--listen", type=float, default=12.0, help="seconds to keep the call open after the audio ends")
    p.add_argument("--out", type=Path, default=Path("fake-twilio-reply.wav"))
    p.add_argument("--auth-token", default=None)
    p.add_argument("--public-base", default=None, help="what PUBLIC_BASE_URL is on the server (signatures are computed over it)")
    args = p.parse_args()

    token = args.auth_token or dotenv("TWILIO_AUTH_TOKEN")
    if not token:
        print("set TWILIO_AUTH_TOKEN in apps/api/.env (any value works locally) or pass --auth-token")
        return 2
    public = (args.public_base or dotenv("PUBLIC_BASE_URL") or args.base).rstrip("/")
    if args.whatsapp or args.whatsapp_receipt:
        return await replay_whatsapp(args, token, public)
    if args.handover:
        return await replay_handover(args, token, public)
    if not args.to:
        print("--to is required (or use --handover CALL_ID)")
        return 2
    path = "/api/telephony/twilio/voice"
    query = "&".join(f"ivr_{kv.split('=', 1)[0]}={kv.split('=', 1)[1]}" for kv in args.ivr if "=" in kv)
    params = {"CallSid": "CAfake" + str(int(time.time())), "From": args.caller, "To": args.to, "CallStatus": "ringing"}
    sig = signature(token, public + path + (f"?{query}" if query else ""), params)
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(args.base.rstrip("/") + path + (f"?{query}" if query else ""), data=params, headers={"X-Twilio-Signature": sig})
    print(f"webhook -> HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text)
        return 1
    root = ElementTree.fromstring(r.text)
    stream = root.find("Connect/Stream")
    if stream is None:
        print("TwiML had no <Stream>:", r.text)
        return 1
    parsed = urlparse(stream.attrib["url"])
    base = urlparse(args.base)
    ws_url = f"{'wss' if base.scheme == 'https' else 'ws'}://{base.netloc}{parsed.path}?{parsed.query}"
    call_sid, stream_sid = params["CallSid"], "MZfake" + str(int(time.time()))
    audio = mulaw_from_wav(args.wav)
    heard = bytearray()

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"event": "connected", "protocol": "Call", "version": "1.0.0"}))
        await ws.send(json.dumps({"event": "start", "streamSid": stream_sid, "start": {
            "streamSid": stream_sid, "callSid": call_sid, "tracks": ["inbound"], "customParameters": {},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1}}}))
        print("stream open; playing caller audio (the agent speaks first)")

        async def listen() -> None:
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("event") == "media":
                        heard.extend(base64.b64decode(msg["media"]["payload"]))
                    else:
                        print("agent event:", msg.get("event"))
            except websockets.ConnectionClosed as exc:
                print(f"stream closed by the server (code {exc.code})")

        listener = asyncio.ensure_future(listen())
        silence = bytes([0xFF]) * FRAME_BYTES
        total = len(audio) // FRAME_BYTES + int(args.listen * 50)
        started = time.monotonic()
        try:
            for i in range(total):
                chunk = audio[i * FRAME_BYTES:(i + 1) * FRAME_BYTES] if i * FRAME_BYTES < len(audio) else silence
                chunk = chunk.ljust(FRAME_BYTES, b"\xff")
                await ws.send(json.dumps({"event": "media", "streamSid": stream_sid, "media": {
                    "track": "inbound", "chunk": str(i + 1), "timestamp": str(i * 20), "payload": base64.b64encode(chunk).decode()}}))
                await asyncio.sleep(max(0.0, started + (i + 1) * 0.02 - time.monotonic()))
                if listener.done():
                    break
            if not listener.done():
                await ws.send(json.dumps({"event": "stop", "streamSid": stream_sid}))
        except websockets.ConnectionClosed:
            pass
        await asyncio.wait([listener], timeout=3)
        listener.cancel()

    pcm = audioop.ulaw2lin(bytes(heard), 2)
    with wave.open(str(args.out), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(pcm)
    print(f"received {len(heard) / 8000:.1f} s of agent audio -> {args.out}")
    print("open the Calls page in the web app to see the transcript, tool calls and the Phone badge")
    return 0 if heard else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
