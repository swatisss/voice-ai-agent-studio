"""Live controls of an active voice call: the pipeline's mutable settings, kept in step with its session.

Spec: /architecture/turn-detection.md (Live controls, TD-09), /architecture/personas.md (PER-04)
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from voiceai.voice.turn_detection import TurnSettings


@dataclass
class LiveControls:
    """Mutable settings of one active voice call, read by the pipeline at every decision."""

    turn: TurnSettings
    on_voice: Callable[[str, float], Awaitable[None]] | None = None  # set by the pipeline: change TTS voice/speed
    welcoming: bool = False  # the opening welcome is playing: caller speech is ignored (VO-08); set by the brain


@dataclass(frozen=True)
class SettingsChange:
    """What a session tells its pipeline after a live change (TD-09)."""

    turn: TurnSettings
    voice: tuple[str, float] | None = None  # new TTS voice and speed when the persona changed


LIVE: dict[str, LiveControls] = {}


def follow(session: Any, controls: LiveControls) -> Callable[[], None]:  # noqa: ANN401
    """Keep `controls` in step with the session's live changes; returns the unsubscribe function."""

    async def apply(change: SettingsChange) -> None:
        controls.turn = change.turn
        if change.voice and controls.on_voice:
            await controls.on_voice(*change.voice)

    return session.subscribe(apply)
