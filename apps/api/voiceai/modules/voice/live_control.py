"""Reaching a live call that this process is serving.

Spec: /architecture/turn-detection.md (Live controls), /architecture/personas.md

Implements `ports/voicecontrol.py` for calls held in this process, and answers False for any other
call - which is exactly what a sticky voice tier would answer for a call on another instance, so
the route above it already handles that case today.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from voiceai.modules.agentcfg.contract import TurnSettings
from voiceai.modules.voice.controls import LIVE


class InProcessVoiceControl:
    async def set_voice(self, call_id: str, voice: str, speed: float) -> bool:
        controls = LIVE.get(call_id)
        if controls is None or controls.on_voice is None:
            return False
        await controls.on_voice(voice, speed)
        return True

    def set_turn(self, call_id: str, turn: Mapping[str, Any]) -> bool:
        controls = LIVE.get(call_id)
        if controls is None:
            return False
        controls.turn = TurnSettings.from_dict(dict(turn))
        return True
