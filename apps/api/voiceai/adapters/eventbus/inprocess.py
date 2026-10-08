"""Adapter: an in-process event bus. One instance, one process (ADR-0005).

Spec: /architecture/jobs-and-events.md (Event bus), /decisions/adr-0005-single-service.md

Each subscriber gets a bounded queue; when it is full the oldest event is dropped so publishing
stays non-blocking, as the port requires. Nothing is persisted and nothing is replayed, so this
adapter is correct only while the service runs as a single instance. Scaling out means a new
adapter behind the same port, which is the horizontal-scaling CP ADR-0005 asks for.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

QUEUE_SIZE = 500


@dataclass(eq=False)
class Subscription:
    tenant_id: str
    topics: set[str]
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=lambda: asyncio.Queue(QUEUE_SIZE))

    def matches(self, tenant_id: str, topic: str) -> bool:
        return tenant_id == self.tenant_id and topic in self.topics


class InProcessEventBus:
    def __init__(self) -> None:
        self._subs: set[Subscription] = set()

    def subscribe(self, tenant_id: str, topics: set[str]) -> Subscription:
        sub = Subscription(tenant_id, topics)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    def publish(self, tenant_id: str, topic: str, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        event = {"id": uuid.uuid4().hex, "topic": topic, "type": type_,
                 "at": datetime.now(timezone.utc).isoformat(), "data": data}
        for sub in list(self._subs):
            if not sub.matches(tenant_id, topic):
                continue
            if sub.queue.full():  # drop oldest: publishing must not block a turn
                with contextlib.suppress(asyncio.QueueEmpty):
                    sub.queue.get_nowait()
            sub.queue.put_nowait(event)
        return event


def build() -> InProcessEventBus:
    return InProcessEventBus()
