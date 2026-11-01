"""Phone transport: Twilio Media Streams events <-> Pipecat frames (Twilio, and any carrier through the public API).

Spec: /architecture/telephony.md (Media stream), /api/voice-protocol.md, /api/public-api.md (Voice connect)
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    AudioRawFrame,
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.twilio import TwilioFrameSerializer

@dataclass
class PhoneStream:
    """What the pipeline needs to know about one Twilio call."""

    call_sid: str
    stream_sid: str
    parameters: dict[str, str] = field(default_factory=dict)
    audio_format: str = "mulaw_8k"  # mulaw_8k | pcm_16k (public-API media streams, PUB-08)
    twilio: bool = True             # a Twilio call: the end-of-call transfer may redirect it (TEL-07)


class PhoneSerializer(TwilioFrameSerializer):
    """Twilio serializer for our pipelines: no automatic hang-up (TwiML `<Hangup/>` and the transfer do that), no browser
    control messages (`ready`, `end`), and a Twilio `stop` event is a hang-up (TEL-06). Interruptions become `clear` events."""

    def __init__(self, stream_sid: str, call_sid: str | None = None) -> None:
        super().__init__(stream_sid=stream_sid, call_sid=call_sid, params=TwilioFrameSerializer.InputParams(auto_hang_up=False))
        self.end_reason = "hangup"

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            return None
        return await super().serialize(frame)

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            event = json.loads(data).get("event")
        except (TypeError, ValueError, AttributeError):
            return None
        if event == "stop":
            return InputTransportMessageFrame(message={"type": "hangup"})
        return await super().deserialize(data)


async def read_start(websocket: WebSocket, max_messages: int = 5) -> dict[str, Any] | None:
    """Read Twilio's `connected` and `start` events; returns the `start` payload (streamSid, callSid, customParameters)."""
    for _ in range(max_messages):
        message = json.loads(await websocket.receive_text())
        if message.get("event") == "start":
            return message.get("start") or {}
        if message.get("event") == "stop":
            return None
    return None


PCM_RATE = 16000


class PcmStreamSerializer(PhoneSerializer):
    """Twilio Media Streams events whose `media.payload` is base64 PCM16 LE mono 16 kHz instead of μ-law (PUB-08)."""

    def __init__(self, stream_sid: str, call_sid: str | None = None) -> None:
        super().__init__(stream_sid, call_sid)
        self._in = create_stream_resampler()
        self._out = create_stream_resampler()

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, AudioRawFrame) and not isinstance(frame, InputAudioRawFrame):
            audio = frame.audio
            if frame.sample_rate != PCM_RATE:
                audio = await self._out.resample(audio, frame.sample_rate, PCM_RATE)
            if not audio:
                return None
            return json.dumps({"event": "media", "streamSid": self._stream_sid, "media": {"payload": base64.b64encode(audio).decode()}})
        return await super().serialize(frame)

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            return None
        if isinstance(message, dict) and message.get("event") == "media":
            audio = base64.b64decode((message.get("media") or {}).get("payload") or "")
            rate = self._sample_rate or PCM_RATE
            if rate != PCM_RATE:
                audio = await self._in.resample(audio, PCM_RATE, rate)
            return InputAudioRawFrame(audio=audio, num_channels=1, sample_rate=rate) if audio else None
        return await super().deserialize(data)


def serializer_for(phone: PhoneStream) -> PhoneSerializer:
    if phone.audio_format == "pcm_16k":
        return PcmStreamSerializer(phone.stream_sid, phone.call_sid)
    return PhoneSerializer(phone.stream_sid, phone.call_sid)
