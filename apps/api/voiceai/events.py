"""In-process event bus, tenant-scoped, streamed to browsers as SSE.

Spec: /architecture/jobs-and-events.md (Event bus), /api/events.md
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from typing import Any

from voiceai.db import new_id, utcnow

QUEUE_SIZE = 500


@dataclass(eq=False)
class Subscription:
    tenant_id: str
    topics: set[str]
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))

    def matches(self, tenant_id: str, topic: str) -> bool:
        return tenant_id == self.tenant_id and topic in self.topics


class EventBus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()

    def subscribe(self, tenant_id: str, topics: set[str]) -> Subscription:
        sub = Subscription(tenant_id, topics)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def publish(self, tenant_id: str, topic: str, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {"id": new_id(), "topic": topic, "type": type_, "at": utcnow().isoformat(), "data": data}
        for sub in list(self._subs):
            if not sub.matches(tenant_id, topic):
                continue
            if sub.queue.full():  # drop oldest
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            sub.queue.put_nowait(event)
        return event


bus = EventBus()


def caller_partial(session: Any, text: str, listening: bool = False) -> None:  # noqa: ANN401
    """VO-09, RV-17: what the caller is saying right now, never stored. Published on the call's topic and, for a routed
    conversation (where the front desk has no call yet), on the conversation's topic too."""
    tenant_id = getattr(session, "tenant_id", None)
    if not tenant_id:
        return
    call_id = getattr(session, "call_id", None)
    conversation_id = getattr(session, "conversation_id", None)
    data: dict[str, Any] = {"call_id": call_id, "text": text}
    if listening:
        data["listening"] = True
    if call_id and call_id != conversation_id:
        bus.publish(tenant_id, f"call:{call_id}", "call.partial", data)
    if conversation_id:
        bus.publish(tenant_id, f"conversation:{conversation_id}", "call.partial", {**data, "conversation_id": conversation_id})
