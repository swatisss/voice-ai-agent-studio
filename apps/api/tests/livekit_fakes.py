"""A fake LiveKit for tests: a recording `RoomBackend`, so no account, network or secret is ever used (LKH-14).

Spec: /architecture/hosted-media-room.md
"""
from __future__ import annotations

import asyncio
from typing import Any

from voiceai.media_room import RoomState, RoomUnavailable


class FakeBackend:
    """Records what the hub asks of LiveKit. Tests drive room events by calling `media_room.participant_*` and `transcript`."""

    def __init__(self) -> None:
        self.ai_started: list[str] = []
        self.said: list[tuple[str, str]] = []
        self.ai_stopped: list[str] = []
        self.scribes: list[str] = []
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.closed: list[str] = []
        self.fail_join = False
        self.join_delay = 0.0

    async def start_ai(self, state: RoomState, session: Any) -> None:  # noqa: ANN401
        if self.join_delay:
            await asyncio.sleep(self.join_delay)
        if self.fail_join:
            raise RoomUnavailable("participant limit reached")
        self.ai_started.append(state.call_id)

    async def say(self, call_id: str, text: str) -> None:
        self.said.append((call_id, text))

    async def stop_ai(self, call_id: str) -> None:
        self.ai_stopped.append(call_id)

    async def start_scribe(self, state: RoomState) -> None:
        self.scribes.append(state.call_id)

    async def send(self, room: str, message: dict[str, Any]) -> None:
        self.sent.append((room, message))

    async def close_room(self, room: str) -> None:
        self.closed.append(room)

    def messages(self, type_: str) -> list[dict[str, Any]]:
        return [m for _, m in self.sent if m.get("type") == type_]
