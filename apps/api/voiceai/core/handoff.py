"""The hand-off desk the conversation module announces to, behind the HandoffDesk port.

Spec: /architecture/escalation.md, /architecture/modular-structure.md

One implementation today, in this process. Keeping the lookup here rather than importing the
console module directly is what keeps the module graph acyclic: the console reads calls and
transcripts, so it may name the conversation module, and the conversation module may not name it.
"""
from __future__ import annotations

from voiceai.ports.handoff import HandoffDesk

__all__ = ["HandoffDesk", "handoff_desk"]


def handoff_desk() -> HandoffDesk:
    from voiceai.modules.handoff.desk import InProcessHandoffDesk

    return InProcessHandoffDesk()
