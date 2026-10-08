"""The safety screen: emergency and self-harm language short-circuits a turn.

Spec: /architecture/escalation.md (Triggers), /product/healthcare-compliance.md

This runs before any model request (ES-01), inside the turn loop, which is why it belongs to the
conversation module rather than to the hand-off console it escalates to.
"""
from __future__ import annotations

SAFETY_PHRASES = (
    "suicide", "kill myself", "end my life", "hurt myself", "want to die", "overdose", "chest pain",
    "can't breathe", "cannot breathe", "stroke", "unconscious", "severe bleeding", "heart attack",
)
SAFETY_MESSAGE = (
    "If this is a medical emergency, please hang up and call 911. If you are thinking about harming yourself, "
    "you can call or text 988 at any time. I'm connecting you with a nurse right now."
)


def safety_match(text: str) -> bool:
    t = text.lower().replace("’", "'")
    return any(p in t for p in SAFETY_PHRASES)
