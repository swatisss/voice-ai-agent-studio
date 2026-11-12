"""English and Hindi: the bilingual setting, the language of a caller turn, and the normalisation of tool arguments.

Spec: /architecture/languages.md, /prompts/agent-system-prompt.md (Language block)
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from voiceai import prompts

ENGLISH = "en"
HINDI = "hi"
BILINGUAL = [ENGLISH, HINDI]

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
# Hindi month names → English (/architecture/languages.md, Identifiers and tool arguments); longest first so that
# spelling variants never match inside each other.
_MONTHS = {
    "जनवरी": "January", "फ़रवरी": "February", "फरवरी": "February", "मार्च": "March", "अप्रैल": "April", "मई": "May",
    "जून": "June", "जुलाई": "July", "अगस्त": "August", "सितंबर": "September", "सितम्बर": "September",
    "अक्टूबर": "October", "अक्तूबर": "October", "नवंबर": "November", "नवम्बर": "November", "दिसंबर": "December",
    "दिसम्बर": "December",
}
_MONTH_RE = re.compile("|".join(sorted((re.escape(unicodedata.normalize("NFC", k)) for k in _MONTHS), key=len, reverse=True)))
_MONTHS_NFC = {unicodedata.normalize("NFC", k): v for k, v in _MONTHS.items()}


def languages_of(config: dict[str, Any]) -> list[str]:
    """The agent's languages; a snapshot published before CP-0037 has none and is English-only."""
    return list(config.get("languages") or [ENGLISH])


def is_bilingual(config: dict[str, Any]) -> bool:
    return HINDI in languages_of(config)


def has_devanagari(text: str) -> bool:
    return bool(_DEVANAGARI.search(text or ""))


def turn_language(text: str) -> str:
    """LANG-05: `hi` when the text holds a Devanagari letter, else `en` (Hindi in Latin letters counts as `en`)."""
    return HINDI if has_devanagari(text) else ENGLISH


def normalise_text(text: str) -> str:
    """LANG-06: Devanagari digits to ASCII and Hindi month names to English."""
    text = unicodedata.normalize("NFC", text).translate(_DIGITS)
    return _MONTH_RE.sub(lambda m: _MONTHS_NFC[m.group(0)], text)


def _walk(value: Any) -> Any:  # noqa: ANN401
    if isinstance(value, str):
        return normalise_text(value)
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v) for k, v in value.items()}
    return value


def normalise_args(raw_args: str) -> str:
    """Every string argument of a tool call, normalised; arguments that are not JSON are left for the tool to refuse."""
    if not raw_args:
        return raw_args
    try:
        parsed = json.loads(raw_args)  # Devanagari may arrive as JSON escapes, so look at the parsed values
    except json.JSONDecodeError:
        return raw_args
    walked = _walk(parsed)
    return raw_args if walked == parsed else json.dumps(walked, ensure_ascii=False)


QUERY_NOT_ENGLISH = {
    "error": "query_not_english",
    "message": "Search knowledge in English: translate the caller's question and search again.",
}


def language_instructions(config: dict[str, Any]) -> str:
    """LANG-04: the Language block of the system prompt for a bilingual agent; empty for an English-only one."""
    return prompts.fragment("agent-system-prompt", "Language block (bilingual agents):") if is_bilingual(config) else ""
