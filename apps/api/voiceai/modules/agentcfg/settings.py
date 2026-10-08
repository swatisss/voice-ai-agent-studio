"""Persona and turn-detection settings as they apply to a call.

Spec: /architecture/personas.md, /architecture/turn-detection.md (Live controls)

A call's effective settings are its version snapshot's, with any live override applied. This is
agent configuration being read, so it lives here rather than in the runtime that acts on it.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.tables import AgentVersion, Call, Persona
from voiceai.modules.agentcfg.domain import TurnSettings


def persona_dict(p: Persona) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "voice": p.voice, "speed": p.speed, "greeting": p.greeting,
            "disclosure": p.disclosure, "opening": p.opening, "style": p.style}


def effective_turn(config: dict[str, Any], live: dict[str, Any] | None) -> TurnSettings:
    base = ((config.get("voice") or {}).get("turn_detection")) or {}
    patch = (live or {}).get("turn_detection") or {}
    return TurnSettings.from_dict({**base, **patch})


def settings_view(persona: dict[str, Any], turn: TurnSettings) -> dict[str, Any]:
    return {
        "persona": {"id": persona.get("id"), "name": persona.get("name"), "voice": persona.get("voice"), "speed": persona.get("speed", 1.0)},
        "turn_detection": turn.to_dict(),
    }


async def effective_settings(s: AsyncSession, call: Call) -> dict[str, Any]:
    """Effective persona and turn detection of a call without opening a session."""
    version = await s.get(AgentVersion, call.agent_version_id)
    config = version.config if version else {}
    live = (call.meta or {}).get("live") or {}
    persona = config.get("persona") or {}
    if live.get("persona_id"):
        row = await s.get(Persona, live["persona_id"])
        if row is not None and row.tenant_id == call.tenant_id:
            persona = persona_dict(row)
    return settings_view(persona, effective_turn(config, live))
