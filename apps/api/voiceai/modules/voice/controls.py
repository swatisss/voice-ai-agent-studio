"""Live voice-call controls: the mutable settings a running pipeline reads at every decision.

Spec: /architecture/turn-detection.md (Live controls), /architecture/personas.md

Process-local by design: these describe calls being served by *this* process. A sticky voice tier
reaches them through the VoiceControl port, which answers "not here" for a call it does not hold.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from voiceai.modules.agentcfg.contract import TurnSettings


@dataclass
class LiveControls:
    """Mutable settings of one active voice call, read by the pipeline at every decision."""

    turn: TurnSettings
    on_voice: Callable[[str, float], Awaitable[None]] | None = None  # set by the pipeline: change TTS voice/speed
    welcoming: bool = False  # the opening welcome is playing: caller speech is ignored (VO-08); set by the brain


LIVE: dict[str, LiveControls] = {}
