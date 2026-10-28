"""Effective call settings: the one resolution of a call's persona, turn detection, pipeline, voice and key source.

Spec: /architecture/personas.md (effective persona, PER-07), /architecture/turn-detection.md, /architecture/realtime-voice.md (RV-01),
/architecture/call-admission.md

`load` reads a call's agent version and overrides once; the session, the call routes, admission and both voice pipelines
read the result instead of resolving pieces of it themselves.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.models import AgentVersion, Call, Persona
from voiceai.voice.turn_detection import TurnSettings

CASCADE_VOICE_DEFAULT = "aura-2-thalia-en"


def persona_dict(p: Persona) -> dict[str, Any]:
    return {"id": p.id, "name": p.name, "voice": p.voice, "speed": p.speed, "greeting": p.greeting,
            "disclosure": p.disclosure, "opening": p.opening, "style": p.style}


def pipeline_of(config: dict[str, Any]) -> str:
    """RV-01: `cascade` unless the version says `realtime`."""
    return "realtime" if ((config.get("voice") or {}).get("pipeline")) == "realtime" else "cascade"


@dataclass(frozen=True)
class CallSettings:
    """A call's effective settings. `config` is the agent version's config with the effective persona applied."""

    config: dict[str, Any]
    base_persona: dict[str, Any] = field(default_factory=dict)  # the version's own persona, for "reset to default"
    live: dict[str, Any] = field(default_factory=dict)          # persisted overrides: persona_id, turn_detection
    meta: dict[str, Any] = field(default_factory=dict)          # the call's admission plan (and the legacy key source)

    @classmethod
    def of(cls, config: dict[str, Any], live: dict[str, Any] | None = None) -> CallSettings:
        """Settings of a config that has no persona override (a simulated call, a session built in memory)."""
        return cls(config=config, base_persona=dict(config.get("persona") or {}), live=dict(live or {}))

    @property
    def pipeline(self) -> str:
        return pipeline_of(self.config)

    @property
    def turn(self) -> TurnSettings:
        base = ((self.config.get("voice") or {}).get("turn_detection")) or {}
        patch = self.live.get("turn_detection") or {}
        return TurnSettings.from_dict({**base, **patch})

    @property
    def persona(self) -> dict[str, Any]:
        return self.config.get("persona") or {}

    @property
    def cascade_voice(self) -> tuple[str, float]:
        """The TTS voice and speed of a cascade call."""
        return self.persona.get("voice") or CASCADE_VOICE_DEFAULT, float(self.persona.get("speed") or 1.0)

    @property
    def key_source(self) -> str | None:
        """RV-16, ADM-05: which OpenAI key a realtime call uses, known from the moment the call is admitted."""
        if self.pipeline != "realtime":
            return None
        return ((self.meta.get("admission") or {}).get("credential_source")) or self.meta.get("openai_key_source")

    def speech_ref(self) -> str:
        """The realtime speech model: the one the admission plan chose, else the version's choice."""
        from voiceai.llm.gateway import gateway

        planned = (self.meta.get("admission") or {}).get("model_ref")
        return planned or gateway().speech_ref((self.config.get("models") or {}).get("speech"))

    def with_persona(self, persona: dict[str, Any] | None) -> CallSettings:
        """A live persona switch (PER-04); None restores the version's own persona."""
        chosen = persona or self.base_persona
        live = {**self.live, "persona_id": chosen.get("id") if persona else None}
        return replace(self, config={**self.config, "persona": chosen}, live=live)

    def with_turn(self, patch: dict[str, Any]) -> CallSettings:
        live = {**self.live, "turn_detection": {**(self.live.get("turn_detection") or {}), **patch}}
        return replace(self, live=live)

    def with_meta(self, meta: dict[str, Any]) -> CallSettings:
        return replace(self, meta={k: meta[k] for k in ("admission", "openai_key_source") if k in meta})

    def view(self) -> dict[str, Any]:
        """The `settings` of every call response."""
        persona = self.persona
        out: dict[str, Any] = {
            "pipeline": self.pipeline,
            "persona": {"id": persona.get("id"), "name": persona.get("name"), "voice": persona.get("voice"), "speed": persona.get("speed", 1.0)},
            "turn_detection": self.turn.to_dict(),
        }
        if self.key_source:
            out["openai_key_source"] = self.key_source
        return out


async def persona_override(s: AsyncSession, tenant_id: str, live: dict[str, Any] | None) -> dict[str, Any] | None:
    """The persona a call-start or live override names: live override, else call-start override (both stored as
    `live.persona_id`). A deleted persona or one of another tenant is ignored (PER-07)."""
    persona_id = (live or {}).get("persona_id")
    if not persona_id:
        return None
    row = await s.get(Persona, persona_id)
    return persona_dict(row) if row is not None and row.tenant_id == tenant_id else None


async def load(s: AsyncSession, call: Call, config: dict[str, Any] | None = None) -> CallSettings:
    """A call's effective settings: its version config (or `config`), the persona override, live changes and plan."""
    if config is None:
        version = await s.get(AgentVersion, call.agent_version_id)
        config = version.config if version else {}
    meta = call.meta or {}
    live = dict(meta.get("live") or {})
    override = await persona_override(s, call.tenant_id, live)
    settings = CallSettings(config={**config, "persona": override} if override else config,
                            base_persona=dict(config.get("persona") or {}), live=live)
    return settings.with_meta(meta)


async def effective_settings(s: AsyncSession, call: Call) -> dict[str, Any]:
    """The effective settings of a call without opening its session (PER-07: the same view the session reports)."""
    return (await load(s, call)).view()
