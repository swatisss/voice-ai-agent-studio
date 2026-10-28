"""Effective call settings: the one resolution of a call's persona, turn detection, pipeline and key source.

Spec: /architecture/personas.md (effective persona, PER-07), /architecture/turn-detection.md, /architecture/realtime-voice.md (RV-01),
/architecture/call-admission.md
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.models import AgentVersion, Call, Persona
from voiceai.voice.turn_detection import TurnSettings


def persona_dict(p: Persona) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "voice": p.voice, "speed": p.speed, "greeting": p.greeting,
            "disclosure": p.disclosure, "opening": p.opening, "style": p.style}


def pipeline_of(config: dict[str, Any]) -> str:
    """RV-01: `cascade` unless the version says `realtime`."""
    return "realtime" if ((config.get("voice") or {}).get("pipeline")) == "realtime" else "cascade"


def effective_turn(config: dict[str, Any], live: dict[str, Any] | None) -> TurnSettings:
    base = ((config.get("voice") or {}).get("turn_detection")) or {}
    patch = (live or {}).get("turn_detection") or {}
    return TurnSettings.from_dict({**base, **patch})


def key_source(meta: dict[str, Any], pipeline: str) -> str | None:
    """RV-16, ADM-05: which OpenAI key a realtime call uses, known from the moment the call is admitted."""
    if pipeline != "realtime":
        return None
    return ((meta.get("admission") or {}).get("credential_source")) or meta.get("openai_key_source")


async def persona_override(s: AsyncSession, tenant_id: str, live: dict[str, Any] | None) -> dict[str, Any] | None:
    """The persona a call-start or live override names: live override, else call-start override (both stored as
    `live.persona_id`). A deleted persona or one of another tenant is ignored (PER-07)."""
    persona_id = (live or {}).get("persona_id")
    if not persona_id:
        return None
    row = await s.get(Persona, persona_id)
    return persona_dict(row) if row is not None and row.tenant_id == tenant_id else None


def view(config: dict[str, Any], live: dict[str, Any] | None, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """The `settings` of every call response, from a config whose persona is already the effective one."""
    persona = config.get("persona") or {}
    pipeline = pipeline_of(config)
    out: dict[str, Any] = {
        "pipeline": pipeline,
        "persona": {"id": persona.get("id"), "name": persona.get("name"), "voice": persona.get("voice"), "speed": persona.get("speed", 1.0)},
        "turn_detection": effective_turn(config, live).to_dict(),
    }
    source = key_source(meta or {}, pipeline)
    if source:
        out["openai_key_source"] = source
    return out


async def effective_config(s: AsyncSession, call: Call) -> dict[str, Any]:
    """The call's version config with the effective persona applied."""
    version = await s.get(AgentVersion, call.agent_version_id)
    config = version.config if version else {}
    override = await persona_override(s, call.tenant_id, (call.meta or {}).get("live"))
    return {**config, "persona": override} if override else config


async def effective_settings(s: AsyncSession, call: Call) -> dict[str, Any]:
    """The effective settings of a call without opening its session (PER-07: the same view the session reports)."""
    meta = call.meta or {}
    return view(await effective_config(s, call), meta.get("live"), meta)
