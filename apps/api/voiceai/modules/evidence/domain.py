"""Pure rules of visual intake: the observation shape, the case shape, and frame bounds.

Spec: /architecture/visual-intake.md, /architecture/media-storage.md

No database, no network, no clock.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

Confidence = Literal["confirmed", "unclear", "not_confirmed"]
SafetyFlag = Literal["none", "injury", "unsafe_premises"]
CaseKind = Literal["facility_fault", "claim"]
Routing = Literal["needs_docs", "ready_for_review", "siu_review", "escalate"]
Source = Literal["camera", "sample"]

# /architecture/media-storage.md, "Frames are bounded on the way in"
MAX_EDGE_PX = 1280
MAX_ENCODED_BYTES = 1_000_000
MAX_FRAMES_PER_CALL = 12
JPEG_QUALITY = 82
JPEG_QUALITY_RETRY = 60

#: Routing values the caller is never told about (VI-10).
SILENT_ROUTING: frozenset[str] = frozenset({"siu_review"})


class ObservedItem(BaseModel):
    label: str = ""
    detail: str = ""


class Observation(BaseModel):
    """One look's structured output, validated against the `vision` role's response."""

    description: str = ""
    items: list[ObservedItem] = Field(default_factory=list)
    confidence: Confidence = "unclear"
    safety_flag: SafetyFlag = "none"
    asked_for: str = ""

    def needs_another_look(self) -> bool:
        return self.confidence != "confirmed"

    def is_unsafe(self) -> bool:
        """Whether this observation must hand off immediately, whatever the case state (VI-11)."""
        return self.safety_flag in ("injury", "unsafe_premises")


class CaseDraft(BaseModel):
    """The drafted case: narrative, what is still missing, and where it routes."""

    narrative: str = ""
    missing: list[str] = Field(default_factory=list)
    routing: Routing = "needs_docs"
    routing_reason: str = ""
    sample_evidence: bool = False


@dataclass(frozen=True)
class EncodedFrame:
    data: bytes
    width: int
    height: int
    content_type: str = "image/jpeg"


class FrameTooLarge(Exception):
    """A frame that will not fit the bounds even after one lower-quality re-encode (MS-02)."""


def encode_bounded(data: bytes, width: int, height: int, pixel_format: str = "RGB") -> EncodedFrame:
    """Re-encode a decoded frame as JPEG within the bounds (MS-02).

    The browser's capture resolution is a hint, not a guarantee, so the bounds are applied here
    rather than trusted from the client. A frame over the size limit is re-encoded once at lower
    quality and then rejected - it is never written at whatever size it happened to be.
    """
    image = Image.frombytes(pixel_format, (width, height), data) if pixel_format in ("RGB", "RGBA", "L") else Image.open(io.BytesIO(data))
    if image.mode != "RGB":
        image = image.convert("RGB")
    if max(image.size) > MAX_EDGE_PX:
        scale = MAX_EDGE_PX / max(image.size)
        image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
    for quality in (JPEG_QUALITY, JPEG_QUALITY_RETRY):
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= MAX_ENCODED_BYTES:
            return EncodedFrame(encoded, image.width, image.height)
    raise FrameTooLarge(f"frame still {len(encoded)} bytes after a lower-quality re-encode")


def spoken_decline(reason: str) -> str:
    """What the tool tells the model when there was no frame to look at.

    The wording matters: the model must ask for what it needs rather than describe anything
    (VI-04), so each reason says what to ask for.
    """
    return {
        "camera_off": "The caller's camera is off. Ask them to turn it on before describing anything.",
        "no_frame": "No frame has arrived from the camera yet. Ask the caller to hold steady for a moment.",
        "cap_reached": "Enough frames have been captured for this report. Move on to confirming the details.",
        "unavailable": "Looking is not available on this call. Ask the caller to describe what they see.",
        "failed": "The frame could not be read. Ask the caller to try again.",
    }.get(reason, "There was nothing to look at. Ask the caller what they can see.")
