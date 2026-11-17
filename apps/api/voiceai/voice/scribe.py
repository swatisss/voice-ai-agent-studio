"""The scribe: a subscribe-only participant that transcribes each human audio track of a room separately.

Spec: /architecture/hosted-media-room.md (Scribe; LKH-09), /architecture/voice-pipeline.md (speech to text)

`TrackTranscriber` is a live Deepgram connection for one track (pure, unit-tested with a fake socket). `Scribe` joins the
room with the LiveKit SDK (imported lazily), watches participants and feeds each `cust-` and `spec-` track to its own
transcriber; results go to `voiceai.media_room.transcript`. Audio is never stored.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlencode

from voiceai import media_room
from voiceai.config import get_settings
from voiceai.media_room import PREFIX, RoomState

log = logging.getLogger("voiceai.scribe")
SAMPLE_RATE = 16000
DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen"
Result = Callable[[str, bool], Awaitable[None]]  # (text, final)


async def _connect(url: str, key: str) -> Any:  # noqa: ANN401
    import websockets

    return await websockets.connect(url, additional_headers={"Authorization": f"Token {key}"})


class TrackTranscriber:
    """One track, one Deepgram live socket. `feed` takes 16 kHz mono 16-bit PCM; results arrive as partials and finals."""

    def __init__(self, key: str, on_result: Result, connect: Callable[[str, str], Awaitable[Any]] = _connect, model: str | None = None) -> None:
        self.key, self.on_result, self._connect = key, on_result, connect
        self.model = model or get_settings().deepgram_stt_model
        self._ws: Any = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: list[str] = []  # finalized segments not yet closed by the end of the utterance

    async def start(self) -> None:
        query = urlencode({"model": self.model, "language": "en-US", "encoding": "linear16", "sample_rate": SAMPLE_RATE,
                           "channels": 1, "interim_results": "true", "punctuate": "true", "smart_format": "true",
                           "endpointing": 300, "utterance_end_ms": 1000})
        self._ws = await self._connect(f"{DEEPGRAM_URL}?{query}", self.key)
        self._reader = asyncio.create_task(self._read())

    async def feed(self, pcm: bytes) -> None:
        if self._ws is not None and pcm:
            await self._ws.send(pcm)

    async def _read(self) -> None:
        try:
            async for raw in self._ws:
                await self.handle(raw)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - a dropped socket must not take the call down
            log.warning("transcriber stopped: %s", type(exc).__name__)
        finally:
            await self._flush()

    async def handle(self, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
        except (TypeError, ValueError):
            return
        if msg.get("type") == "UtteranceEnd":
            await self._flush()
            return
        if msg.get("type") != "Results":
            return
        alts = (msg.get("channel") or {}).get("alternatives") or [{}]
        text = (alts[0].get("transcript") or "").strip()
        if msg.get("is_final"):
            if text:
                self._pending.append(text)
            if msg.get("speech_final"):
                await self._flush()
            elif text:
                await self.on_result(" ".join(self._pending), False)
        elif text:
            await self.on_result(" ".join([*self._pending, text]), False)

    async def _flush(self) -> None:
        if self._pending:
            text, self._pending = " ".join(self._pending), []
            await self.on_result(text, True)

    async def close(self) -> None:
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader


class Scribe:
    """Joins `state.room` as `scribe-<call_id>` (token: subscribe only) and transcribes `cust-` and `spec-` tracks."""

    def __init__(self, state: RoomState, deepgram_key: str) -> None:
        self.state, self.key = state, deepgram_key
        self._room: Any = None
        self._tracks: dict[str, tuple[TrackTranscriber, asyncio.Task[None]]] = {}

    async def start(self) -> None:
        from livekit import rtc

        settings = get_settings()
        token = media_room.mint("scribe", self.state.room, media_room.identity_for("scribe", self.state.call_id))["token"]
        room = rtc.Room()
        self._room = room

        @room.on("participant_connected")
        def _connected(p: Any) -> None:  # noqa: ANN401
            asyncio.ensure_future(media_room.participant_connected(self.state.call_id, p.identity))

        @room.on("participant_disconnected")
        def _disconnected(p: Any) -> None:  # noqa: ANN401
            asyncio.ensure_future(self._drop(p.identity))
            asyncio.ensure_future(media_room.participant_disconnected(self.state.call_id, p.identity))

        @room.on("track_subscribed")
        def _subscribed(track: Any, _pub: Any, p: Any) -> None:  # noqa: ANN401
            if track.kind == rtc.TrackKind.KIND_AUDIO and p.identity.startswith((PREFIX["customer"], PREFIX["specialist"])):
                asyncio.ensure_future(self._listen(track, p.identity))

        await room.connect(settings.livekit_url or "", token)

    async def _listen(self, track: Any, identity: str) -> None:  # noqa: ANN401
        from livekit import rtc

        async def on_result(text: str, final: bool) -> None:
            await media_room.transcript(self.state.call_id, identity, text, final)

        transcriber = TrackTranscriber(self.key, on_result)
        await transcriber.start()
        stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
        pump = asyncio.create_task(self._pump(stream, transcriber))
        self._tracks[identity] = (transcriber, pump)

    @staticmethod
    async def _pump(stream: Any, transcriber: TrackTranscriber) -> None:  # noqa: ANN401
        async for event in stream:
            await transcriber.feed(bytes(event.frame.data))

    async def _drop(self, identity: str) -> None:
        entry = self._tracks.pop(identity, None)
        if entry:
            entry[1].cancel()
            await entry[0].close()

    async def stop(self) -> None:
        for identity in list(self._tracks):
            await self._drop(identity)
        if self._room is not None:
            with contextlib.suppress(Exception):
                await self._room.disconnect()
