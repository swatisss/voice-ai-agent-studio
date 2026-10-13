"""The latest camera frame of a live call, behind the FrameSource port.

Spec: /architecture/visual-intake.md, /api/media-protocol.md

The voice module serves the call and holds its frames; the evidence module needs one and must not
name the voice module to get it, or the module graph would cycle
(/architecture/modular-structure.md). So it asks here.

A process that is not serving the call answers None, which is exactly what a sticky voice tier
would answer for a call on another instance.
"""
from __future__ import annotations

from voiceai.ports.framesource import FrameSource, RawFrame

__all__ = ["FrameSource", "RawFrame", "frame_source"]


def frame_source() -> FrameSource:
    from voiceai.modules.voice.frames import InProcessFrameSource

    return InProcessFrameSource()
