"""Port: changing voice or turn detection on a call that is already running.

Spec: /architecture/turn-detection.md (Live controls), /architecture/personas.md

A live call is held by whichever process is serving its audio. An HTTP request to change its
persona or turn detection used to reach straight into that process's registry; behind this port it
asks, and gets told when the call is not here. On a sticky voice tier that becomes a routed
request with no change to the route.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class VoiceControl(Protocol):
    async def set_voice(self, call_id: str, voice: str, speed: float) -> bool:
        """Change the speaking voice. False when this call is not being served here."""
        ...

    def set_turn(self, call_id: str, turn: Mapping[str, Any]) -> bool:
        """Change turn detection, as a settings mapping. False when this call is not served here.

        A mapping rather than the configuration value object, because this is the shape that
        survives a process boundary and because a port may not depend on a module (MOD-03).
        """
        ...
