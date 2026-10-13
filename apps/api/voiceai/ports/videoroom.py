"""Port: opening the media room a video call runs in.

Spec: /api/media-protocol.md, /decisions/adr-0009-video-channel.md

`POST /api/calls` has to hand the browser a room and a token, and start the agent in that room.
Both belong to the voice module, which already names the conversation module to run the brain - so
the conversation module may not name it back (MOD-01). It asks here instead.

The same shape also answers the degradation question: a deployment with no media service, or an
image without the LiveKit extra, answers False to `available()` and the call is created as a voice
call with a reason (VI-01).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RoomGrant:
    """What the browser needs to join, and nothing more. The API secret stays on the server."""

    url: str
    room: str
    token: str
    identity: str

    def as_dict(self) -> dict[str, str]:
        return {"url": self.url, "room": self.room, "token": self.token, "identity": self.identity}


@runtime_checkable
class VideoRoom(Protocol):
    def available(self) -> bool:
        """Whether a video call can be served at all: configured, and the SDK present."""
        ...

    def unavailable_reason(self) -> str | None:
        """Why `available()` is false, in words an operator can act on, or None when it is true."""
        ...

    def avatar_enabled(self) -> bool:
        """Whether the agent will publish a face on this deployment's video calls (AV-01).

        Separate from `available()`: a video call without an avatar is a normal video call, so an
        absent avatar is never a reason to refuse or degrade one.
        """
        ...

    def grant(self, call_id: str, max_call_seconds: int) -> RoomGrant:
        """Mint the caller's room token, scoped to this call's room and no other (VI-13)."""
        ...

    def start_agent(self, call_id: str, tenant_id: str) -> None:
        """Join the room and run the brain, without blocking the request that created the call."""
        ...
