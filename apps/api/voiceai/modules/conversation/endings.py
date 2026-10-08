"""Ways a call ends: end reasons, closing lines and the farewell-phrase rule.

Spec: /architecture/call-ending-and-feedback.md
"""
from __future__ import annotations

import re

END_REASONS = ("end_call", "farewell", "handoff", "idle", "max_duration", "hangup", "error")

GOODBYE = "Thank you for calling. Take care!"
REMINDER_LINE = "Are you still there?"
IDLE_LINE = "I haven't heard anything, so I'll end the call now. Thank you for calling."
MAX_DURATION_LINE = "We've reached the maximum call length, so I'll end the call now. Thank you for calling."

FAREWELL_PHRASES = (
    "goodbye", "bye bye", "bye", "that's all", "that is all", "that's it", "that is it", "that's everything",
    "nothing else", "i'm all set", "i am all set", "have a good day", "talk to you later",
)
# polite filler that may surround a farewell phrase ("No, that's all, thank you so much")
FILLER = frozenset(
    "no nope ok okay yes yeah thanks thank you so well then please all right i just need needed that was now "
    "for your the help today a very much great good take care have day and".split()
)
MAX_FAREWELL_WORDS = 8


def _normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9'\s]", " ", text)
    return " ".join(text.split())


def is_farewell(text: str) -> bool:
    """CE-02: a short caller turn that is a farewell and nothing else but polite filler. A bare "thank you" is not one."""
    if "?" in text:
        return False
    norm = _normalize(text)
    words = norm.split()
    if not words or len(words) > MAX_FAREWELL_WORDS:
        return False
    matched = False
    rest = norm
    for phrase in FAREWELL_PHRASES:  # longer variants come first so "bye bye" is removed as a whole
        pattern = rf"(?<![a-z0-9']){re.escape(phrase)}(?![a-z0-9'])"
        if re.search(pattern, rest):
            matched = True
            rest = re.sub(pattern, " ", rest)
    return matched and all(w in FILLER for w in rest.split())
