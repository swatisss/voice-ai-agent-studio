"""Turn detection: settings, expected-slot inference, heuristic and LLM end-of-turn evaluators.

Spec: /architecture/turn-detection.md, /prompts/turn-end-check.md, /decisions/adr-0006-turn-detection.md
Pure Python (no Pipecat import) so routes and tests can use it.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, fields

LLM_TIMEOUT_S = 0.9
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


@dataclass
class Verdict:
    complete: bool
    reason: str
    source: str = "heuristic"


# ---------------------------------------------------------------- heuristic evaluator
DIGIT_WORDS = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
HOLD_WORDS = frozenset(
    "and but so because or if that which who the a an my our your is are was were to of for with about um uh umm er hmm like also "
    "then when while since as at in on by from i i'm i'd it's".split()
)
DIGITS_NEEDED = {"member_id": 6, "policy_number": 6, "claim_number": 5, "zip": 5}
SLOT_PHRASES = (
    ("member id", "member_id"), ("policy number", "policy_number"), ("claim number", "claim_number"),
    ("zip", "zip"), ("date of birth", "date_of_birth"), ("birthday", "date_of_birth"),
)
_NUMERIC_DATE = re.compile(r"\b\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{2,4}\b")
_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_SPOKEN_YEAR = re.compile(r"\b(nineteen|twenty)\s+[a-z]+")
_MONTH_WORD = re.compile(r"\b(" + "|".join(MONTHS) + r")\b")


def expected_slots(agent_text: str | None) -> list[str]:
    """What the agent's last message asked the caller to provide."""
    t = (agent_text or "").lower()
    found: list[str] = []
    for phrase, slot in SLOT_PHRASES:
        if phrase in t and slot not in found:
            found.append(slot)
    return found


def count_digits(text: str) -> int:
    n = 0
    for tok in re.findall(r"[a-z]+|\d+", text.lower()):
        if tok.isdigit():
            n += len(tok)
        elif tok in DIGIT_WORDS:
            n += 1
    return n


def _date_given(text: str) -> bool:
    t = text.lower()
    has_day_month = bool(_MONTH_WORD.search(t)) or bool(_NUMERIC_DATE.search(t))
    has_year = bool(_YEAR.search(t)) or bool(_SPOKEN_YEAR.search(t)) or bool(re.search(r"\b\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{4}\b", t))
    return has_day_month and has_year


def _digit_text(text: str, dob_expected: bool) -> str:
    """Text whose digits count toward an ID: drop the date-of-birth part when one is also expected."""
    t = text.lower()
    if not dob_expected:
        return t
    m = _MONTH_WORD.search(t)
    if m:
        return t[: m.start()]
    return _NUMERIC_DATE.sub(" ", t)


def heuristic_verdict(text: str, expecting: list[str] | None = None) -> Verdict:
    """Has the caller finished? Rules in /architecture/turn-detection.md (Heuristic evaluator)."""
    raw = text.strip()
    t = raw.lower()
    expecting = expecting or []
    dob_expected = "date_of_birth" in expecting
    for slot in expecting:  # rules 2 and 3: slot completeness
        if slot in DIGITS_NEEDED and count_digits(_digit_text(t, dob_expected)) < DIGITS_NEEDED[slot]:
            return Verdict(False, f"waiting for more digits ({slot})")
        if slot == "date_of_birth" and not _date_given(t):
            return Verdict(False, "waiting for the full date of birth")
    if raw.endswith((",", "...", "-")):
        return Verdict(False, "trailing punctuation")
    if raw.endswith((".", "?", "!")):
        return Verdict(True, "sentence-final punctuation")
    words = re.findall(r"[a-z']+", t)
    if words and words[-1] in HOLD_WORDS:
        return Verdict(False, f"ends on '{words[-1]}'")
    return Verdict(True, "looks complete")


# ---------------------------------------------------------------- evaluator (heuristic + optional LLM)
LlmCheck = Callable[[str, str], Awaitable[bool]]


async def llm_turn_check(last_agent: str, caller_text: str) -> bool:
    """Ask the fast `turn` model whether the caller is done. Raises on any failure."""
    from voiceai.core import prompts
    from voiceai.core.llm.gateway import gateway
    from voiceai.schemas import TurnVerdictOut

    prompt = prompts.render("turn-end-check", last_agent_message=last_agent or "(none)", caller_text=caller_text)
    out, _ = await gateway().complete_json("turn", [{"role": "user", "content": prompt}], TurnVerdictOut)
    return out.complete


class TurnEvaluator:
    def __init__(self, llm_check: LlmCheck | None = llm_turn_check) -> None:
        self.llm_check = llm_check

    async def is_complete(self, text: str, last_agent: str | None, settings: TurnSettings) -> Verdict:
        heuristic = heuristic_verdict(text, expected_slots(last_agent))
        if settings.evaluator != "llm" or self.llm_check is None:
            return heuristic
        try:  # TD-05: any failure falls back to the heuristic for this turn
            complete = await asyncio.wait_for(self.llm_check(last_agent or "", text), LLM_TIMEOUT_S)
            return Verdict(bool(complete), "llm verdict", "llm")
        except Exception:  # noqa: BLE001 - timeout, provider error, invalid JSON
            return heuristic
