"""The media room for video calls, behind the VideoRoom port.

Spec: /api/media-protocol.md, /decisions/adr-0009-video-channel.md

Only this accessor and `composition/` know that LiveKit is what serves a video call. The route
that creates a call names the capability and is told when video is unavailable.
"""
from __future__ import annotations

from voiceai.ports.videoroom import RoomGrant, VideoRoom

__all__ = ["RoomGrant", "VideoRoom", "video_room"]


def video_room() -> VideoRoom:
    from voiceai.modules.voice.room import LiveKitVideoRoom

    return LiveKitVideoRoom()
