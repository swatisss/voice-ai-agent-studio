"""Raw PCM WebSocket serializer for the browser test-call client.

Spec: /api/voice-protocol.md, /decisions/adr-0002-voice-pipeline.md
"""
from __future__ import annotations

import json

from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputTransportMessageFrame,
    InterruptionFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

IN_RATE = 16000
OUT_RATE = 24000


class RawPCMSerializer(FrameSerializer):
    """binary in: PCM16 LE mono 16 kHz; binary out: PCM16 LE mono 24 kHz; JSON text for control."""

    def __init__(self) -> None:
        super().__init__()
        self.end_reason = "hangup"
        self._resampler = create_stream_resampler()

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            return json.dumps({"type": "interrupt"})
        if isinstance(frame, (EndFrame, CancelFrame)):
            return json.dumps({"type": "end", "reason": self.end_reason})
        if isinstance(frame, AudioRawFrame):
            audio = frame.audio
            if frame.sample_rate != OUT_RATE:
                audio = await self._resampler.resample(audio, frame.sample_rate, OUT_RATE)
            return audio or None
        if isinstance(frame, (OutputTransportMessageFrame, OutputTransportMessageUrgentFrame)):
            if self.should_ignore_frame(frame):
                return None
            return json.dumps(frame.message)
        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        if isinstance(data, (bytes, bytearray)):
            if not data:
                return None
            return InputAudioRawFrame(audio=bytes(data), sample_rate=IN_RATE, num_channels=1)
        try:
            message = json.loads(data)
        except (TypeError, ValueError):
            return None
        return InputTransportMessageFrame(message=message) if isinstance(message, dict) else None
