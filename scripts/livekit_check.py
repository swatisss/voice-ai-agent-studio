#!/usr/bin/env python
"""Connectivity check for the hosted media room: can this machine (or Cloud Run) reach LiveKit and move media?

Spec: /architecture/hosted-media-room.md (LKH-16), /build/runbook-livekit.md

Reads LIVEKIT_URL, LIVEKIT_API_KEY and LIVEKIT_API_SECRET from the environment or apps/api/.env, mints a short-lived token for a
throw-away room, joins it as a participant and reports: signalling OK or failed, the media path (udp, tcp or relay) and the
round-trip time. It never prints the secret or the token and exits non-zero on any failure.

The decision logic (`run`) is unit-tested against a fake prober. The real prober (`LiveKitProber`) uses the LiveKit SDK and
has NOT been run: no LiveKit account existed when it was written. Run it for real as the first step of the runbook.

    python scripts/livekit_check.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))

NAMES = ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET")
OK_MEDIA = ("udp", "tcp", "relay", "connected")  # `connected`: media works, the SDK did not say which path


@dataclass
class Probe:
    signalling_ok: bool
    media: str = "failed"  # udp | tcp | relay | failed | unknown
    rtt_ms: float | None = None
    error: str = ""


class Prober(Protocol):
    async def probe(self, url: str, token: str, room: str) -> Probe: ...


def load_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """The three settings from `env` (default: the process environment) with `apps/api/.env` filling gaps. Values only in memory."""
    values = {k: (env if env is not None else os.environ).get(k, "") for k in NAMES}
    dotenv = ROOT / "apps" / "api" / ".env"
    if env is None and dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            key, _, val = line.partition("=")
            if key.strip() in NAMES and not values[key.strip()]:
                values[key.strip()] = val.strip().strip("'\"")
    return values


def redact(text: str, values: dict[str, str], extra: tuple[str, ...] = ()) -> str:
    for secret in [values.get("LIVEKIT_API_SECRET", ""), values.get("LIVEKIT_API_KEY", ""), *extra]:
        if secret:
            text = text.replace(secret, "***")
    return text


def mint_token(values: dict[str, str], room: str) -> str:
    """A check participant's token, signed with the same code the API uses (`voiceai.media_room.mint`)."""
    from voiceai import media_room
    from voiceai.config import get_settings

    os.environ.update({k: v for k, v in values.items() if v})
    get_settings.cache_clear()
    return media_room.mint("specialist", room, f"check-{uuid.uuid4().hex[:8]}", ttl_s=120)["token"]


async def run(values: dict[str, str], prober: Prober, out: Any = print) -> int:
    """Returns 0 when signalling and media both work, 1 otherwise. Nothing printed contains the secret or the token."""
    missing = [n for n in NAMES if not values.get(n)]
    if missing:
        out(f"FAILED: missing settings {', '.join(missing)} (names only; see /build/runbook-livekit.md)")
        return 1
    room = f"check-{uuid.uuid4().hex[:10]}"
    token = mint_token(values, room)
    out(f"room: {room} (throw-away)")
    started = time.monotonic()
    try:
        result = await prober.probe(values["LIVEKIT_URL"], token, room)
    except Exception as exc:  # noqa: BLE001
        out(f"signalling: FAILED ({redact(type(exc).__name__ + ': ' + str(exc), values, (token,))})")
        return 1
    if not result.signalling_ok:
        out(f"signalling: FAILED ({redact(result.error or 'could not connect', values, (token,))})")
        return 1
    out("signalling: OK")
    out(f"media path: {result.media}")
    rtt = result.rtt_ms if result.rtt_ms is not None else (time.monotonic() - started) * 1000
    out(f"round trip: {rtt:.0f} ms" + ("" if result.rtt_ms is not None else " (connect time; the SDK gave no figure)"))
    if result.media not in OK_MEDIA:
        out("FAILED: signalling works but no media path was established (UDP and TCP both blocked?)")
        return 1
    out("OK")
    return 0


class LiveKitProber:
    """Joins the room with the LiveKit SDK and publishes a short silent audio track: publishing needs the publisher peer connection
    up, so it proves a media path exists. The path type is read from the SDK's stats when they can be parsed; otherwise the media
    is reported as `connected` (path type unknown). UNVERIFIED against a real project."""

    async def probe(self, url: str, token: str, room: str) -> Probe:
        from livekit import rtc

        lk = rtc.Room()
        try:
            await asyncio.wait_for(lk.connect(url, token), 15)
        except Exception as exc:  # noqa: BLE001
            return Probe(False, error=f"{type(exc).__name__}: {exc}")
        try:
            source = rtc.AudioSource(16000, 1)
            track = rtc.LocalAudioTrack.create_audio_track("check", source)
            started = time.monotonic()
            try:
                await asyncio.wait_for(
                    lk.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)), 15)
            except Exception:  # noqa: BLE001
                return Probe(True, "failed", error="publishing a track failed")
            rtt = (time.monotonic() - started) * 1000
            return Probe(True, await self._path(lk), rtt)
        finally:
            await lk.disconnect()

    @staticmethod
    async def _path(lk: Any) -> str:  # noqa: ANN401
        """`udp`, `tcp` or `relay` from the nominated candidate pair's local candidate, else `connected`."""
        try:
            stats = await asyncio.wait_for(lk.get_rtc_stats(), 10)
            reports = list(getattr(stats, "publisher_stats", []) or [])
            locals_ = {r.local_candidate.id: r.local_candidate for r in reports if r.WhichOneof("stats") == "local_candidate"}
            for r in reports:
                if r.WhichOneof("stats") == "candidate_pair" and r.candidate_pair.nominated:
                    cand = locals_.get(r.candidate_pair.local_candidate_id)
                    if cand is None:
                        break
                    if "relay" in str(cand.candidate_type).lower() or cand.candidate_type == 3:
                        return "relay"
                    return "tcp" if "tcp" in str(cand.protocol).lower() else "udp"
        except Exception:  # noqa: BLE001
            pass
        return "connected"


def main() -> int:
    return asyncio.run(run(load_env(), LiveKitProber()))


if __name__ == "__main__":
    sys.exit(main())
