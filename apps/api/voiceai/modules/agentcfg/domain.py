"""Agent configuration value objects.

Spec: /data/agent-config.md, /architecture/turn-detection.md (Settings), /architecture/personas.md

These belong to the agent's configuration, not to the voice pipeline that happens to act on them:
the builder edits them, a version snapshot stores them, and routes return them. Keeping them here
is what stops agent configuration from depending on the voice module.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

FIRST_STAGE_FLOOR_MS = 50
VAD_STOP_MS = 200


@dataclass
class TurnSettings:
    mode: str = "vad"                 # "vad" (normal) | "semantic"
    min_silence_ms: int = 700
    max_extra_wait_ms: int = 1500
    evaluator: str = "heuristic"      # "heuristic" | "llm"
    allow_interruptions: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "TurnSettings":
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in known and v is not None})

    def to_dict(self) -> dict:
        return asdict(self)

    def first_delay_s(self, vad_stop_ms: int = VAD_STOP_MS) -> float:
        """Silence still to wait after the acoustic VAD stop event (TD-01)."""
        return max(FIRST_STAGE_FLOOR_MS, self.min_silence_ms - vad_stop_ms) / 1000


# ---------------------------------------------------------------- configuration schema
BUILTIN_TOOLS = {"search_knowledge", "escalate_to_human", "end_call"}


VOICE_RE = re.compile(r"aura-2-[a-z]+-en")


def _voice(v: str) -> str:
    if not VOICE_RE.fullmatch(v):
        raise ValueError("voice must look like aura-2-<name>-en")
    return v


class Persona(BaseModel):
    id: str | None = None  # set when resolved from the library (snapshot)
    name: str = Field(default="Ava", min_length=1, max_length=40)
    voice: str = "aura-2-thalia-en"
    speed: float = Field(default=1.0, ge=0.7, le=1.5)
    greeting: str = Field(default="Thanks for calling, this is Ava.", min_length=1, max_length=300)
    disclosure: str = Field(default="I'm a virtual assistant, and this call may be recorded for quality.", min_length=1, max_length=300)
    opening: str = Field(default="", max_length=400)
    style: str = Field(default="Warm, calm and concise. One question at a time.", max_length=500)

    @field_validator("voice")
    @classmethod
    def _v(cls, v: str) -> str:
        return _voice(v)


class PersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=200)
    voice: str = "aura-2-thalia-en"
    speed: float = Field(default=1.0, ge=0.7, le=1.5)
    greeting: str = Field(min_length=1, max_length=300)
    disclosure: str = Field(min_length=1, max_length=300)
    opening: str = Field(default="", max_length=400)
    style: str = Field(default="", max_length=500)

    @field_validator("voice")
    @classmethod
    def _v(cls, v: str) -> str:
        return _voice(v)


class TurnDetection(BaseModel):
    mode: Literal["vad", "semantic"] = "vad"
    min_silence_ms: int = Field(default=700, ge=200, le=2000)
    max_extra_wait_ms: int = Field(default=1500, ge=0, le=4000)
    evaluator: Literal["heuristic", "llm"] = "heuristic"
    allow_interruptions: bool = True


class TurnDetectionPatch(BaseModel):
    """Any subset of the turn-detection fields (call-start and live overrides)."""

    mode: Literal["vad", "semantic"] | None = None
    min_silence_ms: int | None = Field(default=None, ge=200, le=2000)
    max_extra_wait_ms: int | None = Field(default=None, ge=0, le=4000)
    evaluator: Literal["heuristic", "llm"] | None = None
    allow_interruptions: bool | None = None


class VoiceConfig(BaseModel):
    turn_detection: TurnDetection = Field(default_factory=TurnDetection)


class Policy(BaseModel):
    rules: list[str] = Field(default_factory=list, max_length=30)
    escalate_when: list[str] = Field(default_factory=list, max_length=30)
    never: list[str] = Field(default_factory=list, max_length=30)
    max_turns: int = Field(default=16, ge=4, le=40)
    handoff_message: str = Field(
        default="I'm connecting you with a specialist who will have all the details, so you won't need to repeat yourself.",
        max_length=300,
    )
    holding_message: str = Field(default="A specialist will be with you shortly. Thanks for your patience.", max_length=300)
    safety_screen: bool = True
    voice_filler: bool = True
    silence_reminder_s: int = Field(default=10, ge=5, le=60)   # voice: "Are you still there?" after this much silence (CE-04)
    silence_end_s: int = Field(default=30, ge=10, le=300)      # voice: end the call after this much silence
    max_call_seconds: int = Field(default=600, ge=60, le=3600)  # voice: hard limit (CE-05)

    @model_validator(mode="after")
    def _silence_order(self) -> Policy:  # CE-07
        if self.silence_end_s <= self.silence_reminder_s:
            raise ValueError("silence_end_s must be greater than silence_reminder_s")
        return self

    @field_validator("rules", "escalate_when", "never")
    @classmethod
    def _short_items(cls, v: list[str]) -> list[str]:
        for item in v:
            if len(item) > 300:
                raise ValueError("list items must be 300 characters or fewer")
        return [i.strip() for i in v if i.strip()]


class ModelChoice(BaseModel):
    realtime: str | None = None


class OutboundConfig(BaseModel):
    targets_url: str = Field(default="", max_length=500)


class AgentConfig(BaseModel):
    mode: Literal["inbound", "outbound", "internal"] = "inbound"
    outbound: OutboundConfig = Field(default_factory=OutboundConfig)
    persona_id: str | None = None
    persona: Persona = Field(default_factory=Persona)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    policy: Policy = Field(default_factory=Policy)
    tool_ids: list[str] = Field(default_factory=list)
    skill_ids: list[str] = Field(default_factory=list)
    knowledge_doc_ids: list[str] = Field(default_factory=list)
    models: ModelChoice = Field(default_factory=ModelChoice)

    @model_validator(mode="after")
    def _outbound_needs_targets(self) -> AgentConfig:
        if self.mode == "outbound" and not self.outbound.targets_url.strip():
            raise ValueError("outbound agents need outbound.targets_url")
        return self


class ToolDef(BaseModel):
    name: str
    description: str = Field(default="", max_length=1000)
    method: Literal["GET", "POST"] = "GET"
    url: str = Field(min_length=1, max_length=500)
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})
    requires_verification: bool = False
    is_verification: bool = False
    timeout_s: int = Field(default=8, ge=1, le=30)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,40}", v):
            raise ValueError("name must be snake_case, 3-41 characters, starting with a letter")
        if v in BUILTIN_TOOLS:
            raise ValueError(f"'{v}' is a built-in tool name")
        return v

    @field_validator("parameters")
    @classmethod
    def _params(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") != "object":
            raise ValueError("parameters must be a JSON Schema object with type: object")
        v.setdefault("properties", {})
        return v


class SkillDef(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=4000)
    required_tools: list[str] = Field(default_factory=list)
    escalate_when: str = Field(default="", max_length=500)


# ------------------------------------------------------------------ LLM outputs
