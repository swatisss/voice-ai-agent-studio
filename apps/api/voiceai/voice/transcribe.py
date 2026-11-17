"""Batch transcription of a recorded channel: the `Transcriber` interface, Deepgram pre-recorded, a fake for tests.

Spec: /architecture/phone-warm-handover.md (Recording and transcription), /changes/cp-0051-twilio-phone-warm-handover.md (ADR note)

A new vendor (Sarvam for code-mixed Hindi and English) is one more class behind `Transcriber`, but needs its own ADR first.
"""
from __future__ import annotations

import array
import io
import logging
import wave
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from voiceai.config import get_settings

log = logging.getLogger("voiceai.transcribe")


@dataclass(frozen=True)
class Segment:
    start_s: float
    end_s: float
    text: str
    language: str | None = None


class Transcriber(Protocol):
    async def transcribe(self, wav_mono: bytes, languages: list[str]) -> list[Segment]:
        """Mono WAV and the agent's language hints in, timed segments out. Raises on a provider failure."""


# ---------------------------------------------------------------- WAV helpers
def wav_channels(wav: bytes) -> int:
    with wave.open(io.BytesIO(wav), "rb") as w:
        return w.getnchannels()


def split_channels(wav: bytes) -> list[bytes]:
    """A 16-bit PCM WAV split into one mono WAV per channel (a mono file comes back as a single item)."""
    with wave.open(io.BytesIO(wav), "rb") as w:
        n, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        if width != 2:
            raise ValueError(f"unsupported WAV sample width {width * 8} bit (16 bit PCM expected)")
        frames = w.readframes(w.getnframes())
    if n == 1:
        return [wav]
    samples = array.array("h")
    samples.frombytes(frames)
    out = []
    for ch in range(n):
        mono = array.array("h", samples[ch::n])
        buf = io.BytesIO()
        with wave.open(buf, "wb") as o:
            o.setnchannels(1)
            o.setsampwidth(2)
            o.setframerate(rate)
            o.writeframes(mono.tobytes())
        out.append(buf.getvalue())
    return out


def make_wav(channels: list[list[int]], rate: int = 8000) -> bytes:
    """A PCM WAV from per-channel sample lists (tests and the fake Twilio script)."""
    n = len(channels)
    frames = array.array("h")
    for i in range(max(len(c) for c in channels)):
        for c in channels:
            frames.append(c[i] if i < len(c) else 0)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as o:
        o.setnchannels(n)
        o.setsampwidth(2)
        o.setframerate(rate)
        o.writeframes(frames.tobytes())
    return buf.getvalue()


# ---------------------------------------------------------------- Deepgram pre-recorded
class DeepgramTranscriber:
    """`POST /v1/listen` with the audio as the body; one request per channel keeps the speakers apart."""

    def __init__(self, api_key: str, base: str = "https://api.deepgram.com", client: httpx.AsyncClient | None = None) -> None:
        self.api_key, self.base, self.client = api_key, base.rstrip("/"), client

    def _params(self, languages: list[str]) -> dict[str, str]:
        s = get_settings()
        params = {"model": s.deepgram_stt_model, "punctuate": "true", "smart_format": "true", "utterances": "true"}
        choice = (s.handover_stt_language or "auto").strip().lower()
        if choice != "auto":
            params["language"] = choice
        elif "hi" in languages:
            params["language"] = "multi"  # English and Hindi in one call: Deepgram's code-switching mode
        elif languages:
            params["language"] = languages[0]
        else:
            params["detect_language"] = "true"
        return params

    async def transcribe(self, wav_mono: bytes, languages: list[str]) -> list[Segment]:
        own = self.client is None
        client = self.client or httpx.AsyncClient(timeout=120)
        try:
            resp = await client.post(f"{self.base}/v1/listen", params=self._params(languages), content=wav_mono,
                                     headers={"Authorization": f"Token {self.api_key}", "Content-Type": "audio/wav"})
            if resp.status_code >= 300:
                raise RuntimeError(f"Deepgram pre-recorded request failed: HTTP {resp.status_code}")  # never the key or the body
            return parse_deepgram(resp.json())
        finally:
            if own:
                await client.aclose()


def parse_deepgram(body: dict[str, Any]) -> list[Segment]:
    results = body.get("results") or {}
    lang = ((results.get("channels") or [{}])[0]).get("detected_language")
    out = [Segment(float(u.get("start", 0)), float(u.get("end", 0)), str(u.get("transcript", "")).strip(), u.get("language") or lang)
           for u in results.get("utterances") or [] if str(u.get("transcript", "")).strip()]
    if out:
        return out
    alt = (((results.get("channels") or [{}])[0].get("alternatives")) or [{}])[0]
    words = alt.get("words") or []
    if words:
        return [Segment(float(words[0].get("start", 0)), float(words[-1].get("end", 0)), str(alt.get("transcript", "")).strip(), lang)]
    return []


# ---------------------------------------------------------------- fake and registry
class FakeTranscriber:
    """Tests: returns scripted segments per call, in order (one list per `transcribe` call), recording what it was asked."""

    def __init__(self, *scripts: list[Segment], fail: bool = False) -> None:
        self.scripts = list(scripts)
        self.fail = fail
        self.calls: list[tuple[int, list[str]]] = []

    async def transcribe(self, wav_mono: bytes, languages: list[str]) -> list[Segment]:
        self.calls.append((len(wav_mono), list(languages)))
        if self.fail:
            raise RuntimeError("fake transcription failure")
        return self.scripts.pop(0) if self.scripts else []


_override: Transcriber | None = None
PROVIDERS: dict[str, Callable[[], Transcriber]] = {}


def set_transcriber(t: Transcriber | None) -> None:
    """Tests install a fake here."""
    global _override
    _override = t


def get_transcriber() -> Transcriber | None:
    """The configured transcriber, or None when its key is missing."""
    if _override is not None:
        return _override
    s = get_settings()
    if s.handover_stt_provider == "deepgram" and s.deepgram_api_key:
        return DeepgramTranscriber(s.deepgram_api_key)
    return None
