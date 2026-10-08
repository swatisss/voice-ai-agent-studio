"""Port: fan-out of live updates to whoever is watching.

Spec: /architecture/jobs-and-events.md (Event bus), /api/events.md

Publishing is **synchronous, non-blocking and best-effort**, and that is a contract, not an
implementation detail: it happens on the voice latency path and inside open transactions. An
implementation MUST return without awaiting anything and MUST drop rather than wait when a
subscriber cannot keep up. A remote bus therefore buffers locally and ships in the background.

Work that must not be lost does NOT belong here - it goes on the job queue.
"""
from __future__ import annotations

from asyncio import Queue
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Subscription(Protocol):
    """A live reader. The SSE endpoint drains `queue` until the client disconnects."""

    tenant_id: str
    topics: set[str]
    queue: Queue[dict[str, Any]]


@runtime_checkable
class EventBus(Protocol):
    def subscribe(self, tenant_id: str, topics: set[str]) -> Subscription: ...

    def unsubscribe(self, sub: Subscription) -> None: ...

    def publish(self, tenant_id: str, topic: str, type_: str, data: dict[str, Any]) -> dict[str, Any]:
        """Deliver to this tenant's subscribers of `topic`. Never blocks, never raises, never
        awaits. Returns the event it built."""
        ...
