"""One look: take the frame, describe it, pin it, and keep the case current.

Spec: /architecture/visual-intake.md, /prompts/vision-observation.md, /prompts/visual-case-draft.md

The discipline this module exists to enforce is that the agent does not claim more than the frame
shows. That lives in two places: the prompt, which is told that withholding confidence is correct,
and here, where a withheld confidence is pinned rather than retried away.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core import prompts
from voiceai.core.framesource import frame_source
from voiceai.core.llm.gateway import LLMError, gateway
from voiceai.modules.evidence import media, repo
from voiceai.modules.evidence.domain import (
    MAX_FRAMES_PER_CALL,
    CaseDraft,
    FrameTooLarge,
    Observation,
    encode_bounded,
    spoken_decline,
)

log = logging.getLogger("voiceai.evidence")

#: Deterministic reporting-intent phrases, so a case can open before the first confirmed look
#: (VI-08). Kept as a phrase list for the same reason the safety screen is: it must be
#: predictable, and a model deciding when a case exists is not.
INTENT_PHRASES = (
    "report a damaged", "report a broken", "report damage", "report a fault", "report a problem",
    "want to report", "need to report", "like to report", "reporting a damaged",
    "reporting a broken", "make a claim", "file a claim", "claim for damage",
)


def states_reporting_intent(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in INTENT_PHRASES)


def case_kind_for(config: dict[str, Any], mode: str) -> str:
    """Which kind of case this agent opens.

    Configuration wins; otherwise an internal agent reports facility faults and a member-facing
    one opens claims, which is what the two visual use cases need
    (/product/use-cases.md, 8 and 9).
    """
    declared = ((config.get("visual") or {}).get("case_kind") or "").strip()
    if declared in ("facility_fault", "claim"):
        return declared
    return "facility_fault" if mode == "internal" else "claim"


@dataclass
class LookResult:
    """What `look_at_camera` hands back to the turn loop."""

    status: str  # "ok" | "declined"
    reason: str = ""
    observation: Observation | None = None
    media_id: str | None = None
    case: dict[str, Any] | None = None

    @property
    def unsafe(self) -> bool:
        return bool(self.observation and self.observation.is_unsafe())

    def for_model(self) -> dict[str, Any]:
        """The tool result the model sees. A declined look carries no observation (VI-04)."""
        if self.status != "ok" or self.observation is None:
            return {"status": "declined", "reason": self.reason, "say": spoken_decline(self.reason)}
        obs = self.observation
        out: dict[str, Any] = {
            "status": "ok",
            "description": obs.description,
            "items": [i.model_dump() for i in obs.items],
            "confidence": obs.confidence,
            "safety_flag": obs.safety_flag,
        }
        if obs.needs_another_look():
            out["asked_for"] = obs.asked_for
            out["guidance"] = (
                "The frame does not settle this. Say what you can see, then ask for the better look "
                "named in asked_for. Do not describe damage the frame does not show, and do not "
                "accuse the caller of being wrong."
            )
        if self.case:
            out["case"] = {k: self.case[k] for k in ("kind", "missing", "routing") if k in self.case}
            out["case_ref"] = self.case.get("id")
        return out


@dataclass
class _Context:
    """Everything a look needs from the call, passed in so this module names no other module."""

    tenant_id: str
    call_id: str
    agent_id: str
    case_kind: str
    caller_words: str = ""
    asset_hint: str = ""
    transcript: str = ""
    caller_verified: bool = False
    entities: dict[str, Any] = field(default_factory=dict)


async def look(session: AsyncSession, ctx: _Context) -> LookResult:
    """Take one frame, describe it, pin it, and update the case."""
    source = frame_source()
    if not source.camera_on(ctx.call_id):
        return LookResult("declined", "camera_off")
    if await repo.frames_stored(session, ctx.tenant_id, ctx.call_id) >= MAX_FRAMES_PER_CALL:
        return LookResult("declined", "cap_reached")  # MS-03
    raw = source.frame_for(ctx.call_id)
    if raw is None:
        return LookResult("declined", "no_frame")
    try:
        frame = encode_bounded(raw.data, raw.width, raw.height, raw.pixel_format)
    except (FrameTooLarge, ValueError, OSError) as exc:
        log.warning("could not encode a frame for call %s: %s", ctx.call_id, exc)
        return LookResult("declined", "failed")

    try:
        observation = await describe(frame.data, ctx)
    except LLMError as exc:
        log.warning("vision role failed on call %s: %s", ctx.call_id, exc)
        return LookResult("declined", "failed")

    stored = await media.store_frame(
        session, tenant_id=ctx.tenant_id, call_id=ctx.call_id, frame=frame, source="camera"
    )
    await repo.add_evidence(
        session, tenant_id=ctx.tenant_id, call_id=ctx.call_id, media_id=stored.id, source="camera",
        description=observation.description, items=[i.model_dump() for i in observation.items],
        confidence=observation.confidence, safety_flag=observation.safety_flag,
        asked_for=observation.asked_for, caller_words=ctx.caller_words,
    )

    case = None
    if observation.confidence == "confirmed":
        case = await _open_and_draft(session, ctx)
    elif await repo.case_for(session, ctx.tenant_id, ctx.call_id) is not None:
        case = await _open_and_draft(session, ctx)  # keep `missing` current after a withheld look
    return LookResult("ok", "", observation, stored.id, case)


async def look_at_sample(session: AsyncSession, ctx: _Context, sample_key: str) -> LookResult:
    """Look at a seeded synthetic image instead of a camera frame (IMG-04).

    It goes through the ordinary path - bounded, stored, described, pinned - and differs in one
    field the whole way down: `source` is `sample`, so nothing here can produce an untagged entry
    that might later pass as camera evidence (IMG-05).
    """
    from voiceai.modules.evidence import assets

    path = assets.sample_path(sample_key)
    if path is None:
        return LookResult("declined", "failed")
    if await repo.frames_stored(session, ctx.tenant_id, ctx.call_id) >= MAX_FRAMES_PER_CALL:
        return LookResult("declined", "cap_reached")
    try:
        from PIL import Image

        image = Image.open(path).convert("RGB")
        frame = encode_bounded(image.tobytes(), image.width, image.height, "RGB")
    except (FrameTooLarge, OSError, ValueError) as exc:
        log.warning("could not read sample %s: %s", sample_key, exc)
        return LookResult("declined", "failed")

    try:
        observation = await describe(frame.data, ctx)
    except LLMError as exc:
        log.warning("vision role failed on sample %s: %s", sample_key, exc)
        return LookResult("declined", "failed")

    stored = await media.store_frame(
        session, tenant_id=ctx.tenant_id, call_id=ctx.call_id, frame=frame, source="sample"
    )
    await repo.add_evidence(
        session, tenant_id=ctx.tenant_id, call_id=ctx.call_id, media_id=stored.id, source="sample",
        description=observation.description, items=[i.model_dump() for i in observation.items],
        confidence=observation.confidence, safety_flag=observation.safety_flag,
        asked_for=observation.asked_for, caller_words=ctx.caller_words,
    )
    case = None
    if observation.confidence == "confirmed" or await repo.case_for(session, ctx.tenant_id, ctx.call_id):
        case = await _open_and_draft(session, ctx)
    return LookResult("ok", "", observation, stored.id, case)


async def note_reference_choice(session: AsyncSession, ctx: _Context, reference_key: str) -> dict[str, Any]:
    """Record that the caller said their fault resembles a reference image (IMG-02, IMG-03).

    A reference is never pinned and never stored - it is already in the repository, and nothing
    was looked at, so there is no confidence to report. It contributes a stated similarity to the
    case, which keeps `missing` honest: a photograph is still outstanding.
    """
    from voiceai.modules.evidence import assets

    label = dict(assets.REFERENCES).get(reference_key)
    similarity = (label[1] if label else reference_key)
    ctx.transcript = f"{ctx.transcript}\nCaller: it resembles \u201c{similarity}\u201d".strip()
    return await _open_and_draft(session, ctx)


async def describe(jpeg: bytes, ctx: _Context) -> Observation:
    """One frame in, one validated observation out (VI-05)."""
    prompt = prompts.render(
        "vision-observation",
        caller_words=ctx.caller_words or "(nothing recorded)",
        asset_hint=ctx.asset_hint or "(not stated)",
    )
    from voiceai.ports.llm import image_part, text_part

    messages = [
        {"role": "user", "content": [text_part(prompt), image_part("image/jpeg", base64.b64encode(jpeg).decode())]}
    ]
    observation, _usage = await gateway().complete_json("vision", messages, Observation)
    if not observation.needs_another_look():
        observation.asked_for = ""  # a confirmed look asks for nothing
    return observation


async def ensure_case(session: AsyncSession, ctx: _Context) -> dict[str, Any]:
    """Open the call's case because the caller said what they are reporting (VI-08)."""
    return await _open_and_draft(session, ctx)


async def _open_and_draft(session: AsyncSession, ctx: _Context) -> dict[str, Any]:
    row = await repo.open_case(
        session, tenant_id=ctx.tenant_id, call_id=ctx.call_id, agent_id=ctx.agent_id, kind=ctx.case_kind
    )
    pinned = await repo.evidence_for(session, ctx.tenant_id, ctx.call_id)
    draft = await draft_case(ctx, pinned)
    if draft is not None:
        row.narrative = draft.narrative
        row.missing = list(draft.missing)
        row.routing = draft.routing
        row.routing_reason = draft.routing_reason
        row.sample_evidence = draft.sample_evidence
        await session.flush()
    return as_dict(row)


PHOTO_OUTSTANDING = "A photograph of the damage"


async def draft_case(ctx: _Context, pinned: list[Any]) -> CaseDraft | None:
    """Draft the narrative, what is missing, and the routing (VI-09).

    A case with no pinned evidence is drafted too - that is the reference-image path, where the
    caller pointed at a picture of a *kind* of fault and nothing was looked at.
    """
    observations = json.dumps(
        [
            {
                "seq": e.seq, "description": e.description, "items": e.items,
                "confidence": e.confidence, "asked_for": e.asked_for or "", "source": e.source,
            }
            for e in pinned
        ],
        indent=2,
    )
    prompt = prompts.render(
        "visual-case-draft",
        kind=ctx.case_kind, observations=observations, transcript=ctx.transcript or "(empty)",
        caller_verified="yes" if ctx.caller_verified else "no",
        entities=json.dumps(ctx.entities or {}),
    )
    try:
        draft, _usage = await gateway().complete_json("drafting", [{"role": "user", "content": prompt}], CaseDraft)
    except LLMError as exc:
        log.warning("case drafting failed on call %s: %s", ctx.call_id, exc)
        return None
    # The model may not decide this: it is a fact about the evidence (IMG-05).
    draft.sample_evidence = bool(pinned) and all(e.source == "sample" for e in pinned)
    if not pinned:
        # Nothing was looked at, so a photograph is still outstanding and the case cannot be
        # ready for review however the draft reads (IMG-02). Enforced here rather than asked of
        # the model, because it is a fact about the case and not a judgement.
        if not any(PHOTO_OUTSTANDING.lower() in item.lower() or "photo" in item.lower() for item in draft.missing):
            draft.missing = [PHOTO_OUTSTANDING, *draft.missing]
        if draft.routing == "ready_for_review":
            draft.routing = "needs_docs"
    return draft


def as_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id, "kind": row.kind, "narrative": row.narrative, "missing": list(row.missing or []),
        "routing": row.routing, "routing_reason": row.routing_reason, "ticket_ref": row.ticket_ref,
        "sample_evidence": bool(row.sample_evidence),
    }


def transcript_of(history: list[dict[str, Any]], limit: int = 30) -> str:
    """The last turns as plain text, for the case draft."""
    lines = []
    for message in history[-limit:]:
        role = message.get("role")
        content = message.get("content")
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            lines.append(f"{'Caller' if role == 'user' else 'Agent'}: {content.strip()}")
    return "\n".join(lines)


def strip_silent_routing(text: str) -> str:
    """Remove anything that would tell the caller the case went to specialist review (VI-10)."""
    return re.sub(r"\b(siu[_ ]?review|special investigations|fraud)\b", "specialist review", text, flags=re.I)
