"""The hand-off vocabulary and the groundwork packet a human reads.

Spec: /architecture/escalation.md, /prompts/escalation-packet.md

Pure declarations. The conversation module reaches the category list through this module's
contract, because it has to categorise an escalation it raises from inside the turn loop.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from voiceai.ports.handoff import HANDOFF_CATEGORIES

ESCALATION_CATEGORIES = HANDOFF_CATEGORIES

DISPOSITIONS = ("resolved_by_human", "appeal_filed", "callback_scheduled", "transferred_department", "no_action_needed", "other")

ShortText = Field(default="", max_length=300)


# ------------------------------------------------------------------ agent config

SENTIMENTS = ("positive", "neutral", "frustrated", "angry", "distressed")


class Sentiment(BaseModel):
    start: str = "neutral"
    end: str = "neutral"
    trend: str = "stable"


class EscalationReason(BaseModel):
    category: str
    detail: str = ""


class Packet(BaseModel):
    summary: str
    intent: str = "unknown"
    entities: dict[str, Any] = Field(default_factory=dict)
    already_tried: list[str] = Field(default_factory=list)
    escalation_reason: EscalationReason
    sentiment: Sentiment = Field(default_factory=Sentiment)
    suggested_next_action: str = ""
    caller_verified: bool = False
