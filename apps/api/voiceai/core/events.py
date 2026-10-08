"""The event bus every module publishes to, behind the EventBus port.

Spec: /architecture/jobs-and-events.md (Event bus), /api/events.md

Modules import `bus` and call `publish`; none of them names an implementation. There is one
adapter today because v1 runs one instance ([/decisions/adr-0005-single-service.md]); swapping it
is this one line plus the horizontal-scaling change proposal that ADR demands. The port's
contract holds whichever adapter is in use: publishing never blocks and never awaits.
"""
from __future__ import annotations

from voiceai.adapters.eventbus.inprocess import build as _build
from voiceai.ports.eventbus import EventBus, Subscription

__all__ = ["EventBus", "Subscription", "bus"]

bus: EventBus = _build()
