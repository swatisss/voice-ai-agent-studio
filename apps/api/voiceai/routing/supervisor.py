"""The supervisor: picks the agent for a conversation at the start and on transfer, in two stages, with clarification.

Spec: /architecture/supervisor-routing.md (Decision, Routing mode, Routing record), /architecture/agent-transfer.md (Flow), /prompts/router-clarify.md
"""
from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import prompts
from voiceai.db import sessionmaker, utcnow
from voiceai.llm.gateway import gateway
from voiceai.models import Agent, AgentVersion, CapabilityProfile
from voiceai.routing import catalog, decision, front_desk

log = logging.getLogger("voiceai.routing.supervisor")

SHORTLIST = 5
FLOOR = 0.35


class Question(BaseModel):
    question: str


async def candidates(s: AsyncSession, tenant_id: str, scope: str, exclude: set[str] | None = None) -> dict[str, CapabilityProfile]:
    """Routable published agents of the scope that have a profile, minus exclusions (RTE-06, XFR-05)."""
    rows = (await s.execute(select(CapabilityProfile, Agent).join(Agent, Agent.id == CapabilityProfile.agent_id)
                            .where(CapabilityProfile.tenant_id == tenant_id, CapabilityProfile.scope == scope))).all()
    out: dict[str, CapabilityProfile] = {}
    for profile, agent in rows:
        if exclude and agent.id in exclude:
            continue
        version = await s.get(AgentVersion, agent.published_version_id) if agent.published_version_id else None
        if version is not None and catalog.routable(version.config) and catalog.scope_of(version.config) == scope:
            out[agent.id] = profile
    return out


def _state(text: str, reason: str | None) -> str:
    lines = [f"Caller: {text.strip()}"]
    if reason:
        lines.append(f"Previous assistant could not help because: {reason.strip()}")
    return "\n".join(lines)


async def clarifying_question(text: str, profiles: list[CapabilityProfile], channel: str) -> str:
    """The front desk's one short question (/prompts/router-clarify.md); a plain fallback when the model fails."""
    titles = [[sk["title"] for sk in (p.card or {}).get("skills", [])][:4] or [(p.card or {}).get("name", "")] for p in profiles]
    areas = "\n".join("- " + ", ".join(t) for t in titles)
    try:
        content = prompts.render("router-clarify", request=text, areas=areas, channel=channel)
        out, _ = await gateway().complete_json("router", [{"role": "user", "content": content}], Question)
        if out.question.strip():
            return out.question.strip()[:160]
    except Exception as exc:  # noqa: BLE001
        log.warning("clarifying question failed: %s", exc)
    plain = [t[0] for t in titles if t and t[0]][:3]
    return f"Happy to help. Is this about {', '.join(plain[:-1])} or {plain[-1]}?" if len(plain) > 1 else "Could you tell me a little more about what you need?"


def clear_winner(ranked: list[dict[str, Any]], fd: front_desk.FrontDesk) -> dict[str, Any] | None:
    """Stage A's clear win under the front desk's thresholds (RTE-14)."""
    if not ranked:
        return None
    top, second = ranked[0], ranked[1]["score"] if len(ranked) > 1 else 0.0
    return top if top["score"] >= fd.clear_win and top["score"] - second >= fd.clear_margin else None


def shortlist_of(ranked: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in ranked if r["score"] >= FLOOR][:SHORTLIST] or ranked[:SHORTLIST]


async def ask_model(text: str, reason: str | None, ranked: list[dict[str, Any]], pool: dict[str, CapabilityProfile],
                    channel: str, fd: front_desk.FrontDesk) -> tuple[decision.Choice | None, str | None]:
    """(the model's choice, why it gave no usable answer): `not_configured`, `phi_mode`, `timeout`, …, or `unsure`."""
    options = {r["agent_id"]: pool[r["agent_id"]].summary or (pool[r["agent_id"]].card or {}).get("name", "") for r in shortlist_of(ranked)}
    try:
        choice = await decision.decide(_state(text, reason), options, channel=channel)
    except decision.Unavailable as exc:
        return None, str(exc)
    needed = fd.min_confidence if fd.min_confidence is not None else choice.threshold
    if choice.agent_id is None or choice.confidence < needed:
        return choice, "unsure"
    return choice, None


async def route(tenant_id: str, scope: str, text: str, *, channel: str, trigger: str = "start", exclude: set[str] | None = None,
                reason: str | None = None, clarifications_used: int = 0, allow_clarify: bool = True,
                mode: str | None = None) -> dict[str, Any]:
    """One routing decision record (/architecture/supervisor-routing.md, Decision and Routing mode). `agent_id` None with
    `clarification` set means: ask the caller, then route again; `agent_id` None without it means no candidate at all."""
    started = time.perf_counter()
    async with sessionmaker()() as s:
        fd = await front_desk.load(s, tenant_id)
        mode = mode or fd.routing_mode
        pool = await candidates(s, tenant_id, scope, exclude)
        default = await front_desk.default_agent(s, tenant_id, fd, scope)
        if default in (exclude or set()):
            default = None
        record: dict[str, Any] = {"at": utcnow().isoformat(), "trigger": trigger, "input": text, "scope": scope, "mode": mode,
                                  "excluded": sorted(exclude or []), "candidates": [], "stage_a_ms": 0, "stage_b": None,
                                  "fallbacks": [], "method": None, "agent_id": None, "confidence": None, "reason": "",
                                  "clarification": None, "unsure": False}
        if not pool:
            record.update(method="none", reason="No agent can take this request")
            return record
        if len(pool) == 1:
            only = next(iter(pool))
            record.update(method="single", agent_id=only, confidence=1.0, reason="The only agent for this audience")
            return record
        t0 = time.perf_counter()
        ranked = await catalog.stage_a(s, tenant_id, scope, text, set(pool))
        record["stage_a_ms"] = int((time.perf_counter() - t0) * 1000)
        record["candidates"] = ranked[:SHORTLIST]
        if mode == "decision_model":  # RTE-02, RTE-03, RTE-04, RTE-13: the model first, the embedding as fallback
            choice, why = await ask_model(text, reason, ranked, pool, channel, fd)
            if choice is not None:
                record["stage_b"] = choice.record()
            if why is None and choice is not None:
                record.update(method="decision", agent_id=choice.agent_id, confidence=round(choice.confidence, 4),
                              reason="Chosen by the decision model")
                return record
            record["fallbacks"] = [{"target": "decision_model", "error": why or "unsure"}]
        win = clear_winner(ranked, fd)
        if win is not None:  # RTE-01, RTE-12, RTE-14
            record.update(method="embedding", agent_id=win["agent_id"], confidence=win["score"], reason="Clear match on what this agent handles")
            return record
        record["unsure"] = True
        top = ranked[0] if ranked else None
        if allow_clarify and clarifications_used < fd.max_clarifications:  # RTE-05
            profiles = [pool[r["agent_id"]] for r in shortlist_of(ranked)[:3]]
            record.update(method="clarify", reason="Not sure which area this is",
                          clarification=await clarifying_question(text, profiles, channel))
            return record
        fallback = default or (top["agent_id"] if top else next(iter(pool)))
        record.update(method="default", agent_id=fallback, confidence=top["score"] if top else None,
                      reason="Routed to the default agent" if default else "Routed to the closest match")
        record["ms"] = int((time.perf_counter() - started) * 1000)
        return record


async def decide_for_suite(tenant_id: str, scope: str, text: str, mode: str | None = None) -> dict[str, Any]:
    """The routing suite: the live decision, text timeouts, no clarification (CAT-07)."""
    started = time.perf_counter()
    record = await route(tenant_id, scope, text, channel="text", allow_clarify=False, mode=mode)
    record["latency_ms"] = int((time.perf_counter() - started) * 1000)
    return record
