"""Phone transport: Twilio Media Streams events <-> Pipecat frames.

Spec: /architecture/telephony.md (Media stream), /api/voice-protocol.md
"""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket
from pipecat.frames.frames import (
    Frame,
    InputTransportMessageFrame,
    OutputTransportMessageFrame,
    OutputTransportMessageUrgentFrame,
)
from pipecat.serializers.twilio import TwilioFrameSerializer

OnPhoneEnd = Callable[[Any, str], Awaitable[None]]  # (session, end reason): runs after the closing speech, before the stream closes


@dataclass
class PhoneStream:
    """What the pipeline needs to know about one Twilio call."""

    call_sid: str
    stream_sid: str
    parameters: dict[str, str] = field(default_factory=dict)
    on_end: OnPhoneEnd | None = None


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
