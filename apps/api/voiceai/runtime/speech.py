"""Plain speech for voice channels.

Spec: /architecture/agent-runtime.md (Spoken text, QA-07)
"""
from __future__ import annotations

import re

_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_BULLET = re.compile(r"(?m)^\s*(?:[-*•]|\d+[.)])\s+")


def plain(text: str) -> str:
    """Drop markdown a text-to-speech voice would read aloud. Works on a streamed chunk: it only removes whole
    tokens (`**`, backticks, heading hashes, bullets, link targets), never needs the text around it."""
    text = _LINK.sub(r"\1", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    return text.replace("**", "").replace("__", "").replace("`", "").replace("*", "")
