"""The decision model: one optional, Jev-compatible model the supervisor asks in `decision_model` routing mode.

Spec: /architecture/supervisor-routing.md (Routing mode, Decision model)

Configured only by environment (`DECISION_MODEL_*`); nothing here names a vendor. When it is not configured, blocked by
PHI mode, fails or is unsure, the supervisor uses the embedding instead.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from voiceai.config import get_settings

log = logging.getLogger("voiceai.routing.decision")

TIMEOUT_DEFAULT_MS = {"voice": 350, "text": 1500}
TIMEOUT_BOUNDS_MS = (100, 5000)
NONE = "none"
NONE_TEXT = "The request fits none of these, or is too vague to tell."
INSTRUCTIONS = "Pick the assistant that is set up to handle the caller's request."

transport: httpx.AsyncBaseTransport | None = None  # tests install an httpx.MockTransport


@dataclass
class Choice:
    agent_id: str | None          # None = the model chose `none`
    confidence: float
    threshold: float
    ms: int
    model: str
    probabilities: dict[str, float] = field(default_factory=dict)

    def record(self) -> dict[str, Any]:
        return {"target": "decision_model", "model": self.model, "choice": self.agent_id or NONE,
                "confidence": round(self.confidence, 4), "probabilities": self.probabilities, "ms": self.ms}


class Unavailable(Exception):
    """Why the decision model gave no usable answer: not_configured, phi_mode, timeout, http_<code>, invalid_answer."""


def phi_mode() -> bool:
    """On by default when running on Cloud Run (K_SERVICE set); `PHI_MODE=0|1` overrides (RTE-04)."""
    raw = (get_settings().phi_mode or "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return bool(os.environ.get("K_SERVICE"))


def _flag(raw: str | None, default: bool) -> bool:
    value = (raw or "").strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


def configured() -> bool:
    return bool((get_settings().decision_model_url or "").strip())


def hosted() -> bool:
    return _flag(get_settings().decision_model_hosted, True)


def blocked() -> bool:
    """A hosted decision model is never called in PHI mode (healthcare compliance rule 11)."""
    return configured() and hosted() and phi_mode()


def threshold() -> float:
    return float(get_settings().decision_model_threshold)


_warned: set[tuple[str, str]] = set()


def timeout_ms(channel: str) -> int:
    """The time budget for one request (RTE-16, RTE-17): `DECISION_MODEL_TIMEOUT_<VOICE|TEXT>_MS`, clamped to 100-5000."""
    key = "voice" if channel == "voice" else "text"
    s = get_settings()
    raw = (s.decision_model_timeout_voice_ms if key == "voice" else s.decision_model_timeout_text_ms) or ""
    if not raw.strip():
        return TIMEOUT_DEFAULT_MS[key]
    try:
        value = int(raw.strip())
    except ValueError:
        value = TIMEOUT_DEFAULT_MS[key]
    lo, hi = TIMEOUT_BOUNDS_MS
    used = min(max(value, lo), hi)
    if str(used) != raw.strip() and (key, raw) not in _warned:
        _warned.add((key, raw))
        log.warning("DECISION_MODEL_TIMEOUT_%s_MS=%r is not a whole number from %d to %d; using %d ms", key.upper(), raw, lo, hi, used)
    return used


def health() -> dict[str, Any]:
    """RTE-11, RTE-17: configuration only, no network call."""
    return {"configured": configured(), "hosted": hosted(), "blocked": blocked(),
            "timeouts_ms": {"voice": timeout_ms("voice"), "text": timeout_ms("text")}}


async def decide(state: str, options: dict[str, str], *, channel: str) -> Choice:
    """Ask the decision model to pick one option (or `none`); raises Unavailable with the reason (RTE-02, RTE-03)."""
    if not configured():
        raise Unavailable("not_configured")
    if blocked():
        raise Unavailable("phi_mode")
    s = get_settings()
    options = {**options, NONE: NONE_TEXT}
    body: dict[str, Any] = {"state": state, "questions": {"route": {"type": "choice", "instructions": INSTRUCTIONS, "criteria": options}}}
    if s.decision_model_name:
        body["model"] = s.decision_model_name
    headers = {"Content-Type": "application/json"}
    if s.decision_model_api_key:
        headers["Authorization"] = f"Bearer {s.decision_model_api_key}"
    timeout = timeout_ms(channel) / 1000
    url = s.decision_model_url.rstrip("/") + "/v1/systemone"
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(transport=transport, timeout=timeout) as client:
            resp = await asyncio.wait_for(client.post(url, json=body, headers=headers), timeout + 0.05)
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise Unavailable("timeout") from exc
    except httpx.HTTPError as exc:
        raise Unavailable(type(exc).__name__) from exc
    if resp.status_code >= 400:
        raise Unavailable(f"http_{resp.status_code}")
    try:
        payload = resp.json()
        answer = payload["answers"]["route"]
        choice = str(answer["choice"])
        # `x_jev_confidence` when present: some compatible servers report an entropy-based `confidence` on another scale
        confidence = float(answer.get("x_jev_confidence", answer.get("confidence", 0.0)))
    except (KeyError, TypeError, ValueError) as exc:
        raise Unavailable("invalid_answer") from exc
    if choice not in options:
        raise Unavailable("invalid_answer")
    return Choice(None if choice == NONE else choice, confidence, threshold(), int((time.perf_counter() - started) * 1000),
                  str(payload.get("model") or s.decision_model_name or ""),
                  {k: float(v) for k, v in (answer.get("probabilities") or {}).items()})
