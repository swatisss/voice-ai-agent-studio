"""Port: the most recent camera frame of a call that is running now.

Spec: /architecture/visual-intake.md, /api/media-protocol.md

This has to invert. The turn loop calls `evidence` through its contract, and `voice` already names
`conversation` to run the brain - so if `evidence` named `voice` back to fetch a frame, the module
graph would close into `conversation -> evidence -> voice -> conversation` and MOD-01 would fail,
correctly, because the cycle is real.

So `evidence` names the capability "give me this call's latest frame" and `voice` implements it.
What comes back is decoded pixels, never a Pipecat object, which is also what keeps Pipecat inside
the voice module (MOD-04).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawFrame:
    """One decoded video frame: raw pixel bytes plus what is needed to read them."""

    data: bytes
    width: int
    height: int
    pixel_format: str = "RGB"  # as PIL names it


@runtime_checkable
class FrameSource(Protocol):
    def frame_for(self, call_id: str) -> RawFrame | None:
        """The call's latest frame, or None when the camera is off, no frame has arrived yet, or
        this process is not serving the call.

        Reading does not consume: two looks in quick succession may see the same frame, which is
        correct - the agent asked twice about the same moment.
        """
        ...

    def camera_on(self, call_id: str) -> bool:
        """Whether a camera track is currently published, so a declined look can say why."""
        ...
