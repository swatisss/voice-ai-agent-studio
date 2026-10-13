"""The frame tap: one frame per call, replaced as frames arrive.

Spec: /architecture/visual-intake.md, /api/media-protocol.md, /decisions/adr-0009-video-channel.md

Pipecat 1.12.0's LiveKit transport has no way to ask for a single frame - `video_in_enabled`
starts a task that pushes every inbound frame into the pipeline. So the tap sits directly after
`transport.input()`, keeps the newest frame, and **consumes** the rest: nothing downstream (VAD,
STT, the brain) ever sees video.

A queue here would hand the model a stale frame and grow without bound, which is why the holder
is exactly one frame deep (VI-03). The frame leaves this module only as decoded pixels through the
`FrameSource` port, never as a Pipecat object, which is what keeps MOD-04 true.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from voiceai.ports.framesource import RawFrame

log = logging.getLogger("voiceai.voice")


@dataclass
class FrameHolder:
    """One call's latest frame, and whether its camera is publishing at all."""

    camera_on: bool = False
    frame: RawFrame | None = None

    def put(self, frame: RawFrame) -> None:
        self.camera_on = True
        self.frame = frame  # replaced, never queued

    def camera_off(self) -> None:
        """The caller unpublished the track: drop the frame so a later look cannot use a stale one."""
        self.camera_on = False
        self.frame = None


#: Process-local, like the live-controls registry beside it. ADR-0005 keeps this service to one
#: instance; a sticky voice tier would make this the tier's state rather than the service's.
TAPS: dict[str, FrameHolder] = {}


def register(call_id: str) -> FrameHolder:
    holder = FrameHolder()
    TAPS[call_id] = holder
    return holder


def release(call_id: str) -> None:
    TAPS.pop(call_id, None)


class InProcessFrameSource:
    """Implements `ports/framesource.py` for calls this process is serving."""

    def frame_for(self, call_id: str) -> RawFrame | None:
        holder = TAPS.get(call_id)
        if holder is None or not holder.camera_on:
            return None
        return holder.frame

    def camera_on(self, call_id: str) -> bool:
        holder = TAPS.get(call_id)
        return bool(holder and holder.camera_on)
