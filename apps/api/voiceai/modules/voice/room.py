"""The LiveKit room a video call runs in: naming, tokens, and starting the agent.

Spec: /api/media-protocol.md, /decisions/adr-0009-video-channel.md

Implements `ports/videoroom.py`. The API key and secret never leave this process; the browser
receives only a minted token, scoped to one room, with a lifetime no longer than the call.

`livekit` is imported lazily, like the LLM wire adapters, so a deployment without it - or without
the three `LIVEKIT_*` settings - still starts and simply reports video as unavailable (VI-01).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from voiceai.core.config import get_settings
from voiceai.ports.videoroom import RoomGrant

log = logging.getLogger("voiceai.voice")

#: A token outlives the call by a small margin and no more, so it cannot be kept and replayed.
TOKEN_GRACE = timedelta(minutes=5)
CALLER_IDENTITY = "caller"
AGENT_IDENTITY = "agent"
#: If nobody joins, end the call rather than leave a room and a pipeline running for nobody.
JOIN_TIMEOUT_S = 60.0


def room_name(call_id: str) -> str:
    """One room per call, derivable, never reused across calls."""
    return f"call-{call_id}"


def configured() -> bool:
    s = get_settings()
    return bool(s.livekit_url and s.livekit_api_key and s.livekit_api_secret)


def _mint(room: str, identity: str, ttl: timedelta) -> str:
    """A token for one room and one identity.

    `can_publish_data` is deliberately not granted: the control surface is the REST API and SSE,
    and a second one would be a second thing to secure ([/api/media-protocol.md]).
    """
    from livekit import api

    settings = get_settings()
    grants = api.VideoGrants(
        room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=False
    )
    return (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_grants(grants)
        .with_ttl(ttl)
        .to_jwt()
    )


class LiveKitVideoRoom:
    """Implements `ports/videoroom.py` against LiveKit Cloud."""

    def unavailable_reason(self) -> str | None:
        s = get_settings()
        missing = [n for n, v in (("LIVEKIT_URL", s.livekit_url), ("LIVEKIT_API_KEY", s.livekit_api_key),
                                  ("LIVEKIT_API_SECRET", s.livekit_api_secret)) if not v]
        if missing:
            return f"{', '.join(missing)} not set in apps/api/.env (restart the API after editing it)."
        try:
            import livekit.api  # noqa: F401
            import livekit.rtc  # noqa: F401
        except ImportError:  # the extra is not installed in this image
            return "the livekit package is not installed in the API environment (run `uv sync` in apps/api)."
        return None

    def available(self) -> bool:
        return self.unavailable_reason() is None

    def avatar_enabled(self) -> bool:
        from voiceai.modules.voice.avatar import avatar_available

        return avatar_available()

    def grant(self, call_id: str, max_call_seconds: int) -> RoomGrant:
        settings = get_settings()
        room = room_name(call_id)
        ttl = timedelta(seconds=max_call_seconds) + TOKEN_GRACE
        return RoomGrant(
            url=str(settings.livekit_url), room=room,
            token=_mint(room, CALLER_IDENTITY, ttl), identity=CALLER_IDENTITY,
        )

    def agent_token(self, call_id: str, max_call_seconds: int) -> str:
        return _mint(room_name(call_id), AGENT_IDENTITY, timedelta(seconds=max_call_seconds) + TOKEN_GRACE)

    def start_agent(self, call_id: str, tenant_id: str) -> None:
        """Join the room and run the brain, as a background task.

        `POST /api/calls` must not block on a media connection, so the pipeline starts detached -
        the same shape the voice WebSocket has, where the socket handler owns the pipeline's life.
        """
        task = asyncio.create_task(_run_agent(call_id, tenant_id))
        _AGENT_TASKS.add(task)
        task.add_done_callback(_AGENT_TASKS.discard)


_AGENT_TASKS: set[asyncio.Task[None]] = set()


async def _run_agent(call_id: str, tenant_id: str) -> None:
    from voiceai.modules.voice import pipeline

    try:
        await pipeline.run_room(call_id, tenant_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - a failed video call must not take the process down
        log.error("video call %s ended in error: %s", call_id, exc, exc_info=True)


async def wait_agents() -> None:
    """Await in-flight video pipelines (tests, shutdown)."""
    while _AGENT_TASKS:
        await asyncio.gather(*list(_AGENT_TASKS), return_exceptions=True)


async def close_avatars() -> None:
    """Close any avatar vendor sessions still open, so none outlives the process (AV-12)."""
    from voiceai.modules.voice.avatar import close_all_avatars

    await close_all_avatars()
