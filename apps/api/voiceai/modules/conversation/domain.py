"""Pure conversation rules and the transcript view of a call.

Spec: /architecture/agent-runtime.md, /architecture/call-ending-and-feedback.md

Nothing here touches the database, the clock or the network. `transcript_lines` lives here rather
than with the hand-off that first needed it, because a call's events are this module's data.
"""
from __future__ import annotations

from voiceai.core.tables import CallEvent


def transcript_lines(events: list[CallEvent]) -> str:
    lines = []
    for ev in events:
        if ev.kind == "user":
            lines.append(f"Caller: {ev.text}")
        elif ev.kind == "assistant" and ev.text:
            lines.append(f"Agent: {ev.text}")
        elif ev.kind == "tool_result":
            lines.append(f"Tool {ev.data.get('name')} -> {str(ev.data.get('result'))[:400]}")
    return "\n".join(lines)
