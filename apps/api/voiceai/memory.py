"""Member memory: what one agent remembers about one verified member, maintained by the agent itself after each call.

Spec: /architecture/agent-memory.md, /prompts/memory-extract.md, /prompts/memory-update.md, /decisions/adr-0009-agent-memory.md
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs, prompts
from voiceai.db import sessionmaker, utcnow
from voiceai.knowledge.embeddings import embed_one
from voiceai.llm.gateway import gateway
from voiceai.models import Agent, AgentVersion, Call, CallEvent, MemberMemory, MemoryEvent, Tenant
from voiceai.schemas import MemoryConfig, MemoryDecisionOut, MemoryExtractOut

log = logging.getLogger("voiceai.memory")

PROMPT_VERSION = "cp-0019"
FACT_LIMIT = 10      # facts loaded into a call
EPISODE_LIMIT = 3    # recent episodes loaded into a call
SIMILAR = 5          # remembered facts shown to the update decision

# Fixed exclusions (not configurable): applied in code after the model, whatever it proposed (MEM-04).
_EXCLUDED = [
    re.compile(r"\b(diagnos\w*|symptom\w*|medication\w*|medicine\w*|prescri\w*|treatment\w*|therap(y|ies|ist)|surgery|"
               r"chemo\w*|insulin|dosage|dose|mg|pain|painful|cancer|diabet\w*|asthma|depress\w*|anxiety|pregnan\w*|"
               r"illness|disease|infection|injur\w*|allerg\w*)\b", re.I),
    re.compile(r"\b(card|bank|account|routing|iban|sort code|cvv|credit|debit)\b.{0,20}\d|\d.{0,20}\b(card|bank|account)\b", re.I),
    re.compile(r"\b(?:\d[ -]?){12,19}\b"),              # card-like digit runs
    re.compile(r"\bEVG-?\s?\d{4,}\b|\b\d{6,}\b", re.I),  # member IDs and other long identifiers
    re.compile(r"\b(date of birth|born on|birthday|dob)\b", re.I),
    re.compile(r"\+?\d[\d\s().-]{8,}\d"),                # phone numbers
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),              # email addresses
]


def settings_of(config: dict[str, Any]) -> MemoryConfig:
    """The version's memory settings; a snapshot from before memory existed gets the defaults."""
    return MemoryConfig.model_validate(config.get("memory") or {})


def allowed(text: str) -> bool:
    return bool(text.strip()) and not any(p.search(text) for p in _EXCLUDED)


def clean_episode(text: str) -> str:
    """An episode keeps only the sentences that break no exclusion."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(s for s in sentences if allowed(s)).strip()


def item_dict(m: MemberMemory) -> dict[str, Any]:
    return {
        "id": m.id, "agent_id": m.agent_id, "member_ref": m.member_ref, "kind": m.kind, "category": m.category, "text": m.text,
        "status": m.status, "valid_at": _iso(m.valid_at), "invalid_at": _iso(m.invalid_at), "superseded_by": m.superseded_by,
        "expires_at": _iso(m.expires_at), "source_call_id": m.source_call_id, "source_seq": m.source_seq,
        "created_at": _iso(m.created_at), "updated_at": _iso(m.updated_at),
    }


def event_dict(e: MemoryEvent) -> dict[str, Any]:
    return {
        "id": e.id, "agent_id": e.agent_id, "member_ref": e.member_ref, "memory_id": e.memory_id, "action": e.action,
        "actor": e.actor, "call_id": e.call_id, "text_before": e.text_before, "text_after": e.text_after, "reason": e.reason,
        "at": _iso(e.at),
    }


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ---------------------------------------------------------------- reading (MEM-05, MEM-06)
def _scope(tenant_id: str, agent_id: str, member_ref: str) -> list[Any]:
    return [MemberMemory.tenant_id == tenant_id, MemberMemory.agent_id == agent_id, MemberMemory.member_ref == member_ref]


async def load(s: AsyncSession, tenant_id: str, agent_id: str, member_ref: str) -> tuple[list[MemberMemory], list[MemberMemory]]:
    """Active, unexpired facts (newest confirmed first) and the most recent episodes of one scope."""
    live = [*_scope(tenant_id, agent_id, member_ref), MemberMemory.status == "active", MemberMemory.expires_at > utcnow()]
    facts = (await s.scalars(select(MemberMemory).where(*live, MemberMemory.kind == "fact")
                             .order_by(MemberMemory.updated_at.desc()).limit(FACT_LIMIT))).all()
    episodes = (await s.scalars(select(MemberMemory).where(*live, MemberMemory.kind == "episode")
                                .order_by(MemberMemory.created_at.desc()).limit(EPISODE_LIMIT))).all()
    return list(facts), list(episodes)


def render(facts: list[MemberMemory], episodes: list[MemberMemory]) -> str:
    """`member_memory` in the system prompt."""
    if not facts and not episodes:
        return "- (nothing remembered yet)"
    lines = ["Facts:", *(f"- {m.text}" for m in facts)] if facts else []
    if episodes:
        lines += ["Earlier calls:", *(f"- ({m.created_at:%b} {m.created_at.day}) {m.text}" for m in episodes)]
    return "\n".join(lines)


# ---------------------------------------------------------------- maintenance after a call (MEM-01..MEM-04)
def applies(call: Call, config: dict[str, Any]) -> bool:
    """MEM-01: a verified, real call on a version with memory enabled."""
    return bool(call.caller_ref) and not call.is_eval and call.channel != "simulation" and settings_of(config).enabled


def _transcript(events: list[CallEvent]) -> str:
    lines = []
    for e in events:
        if e.kind == "user":
            lines.append(f"[{e.seq}] Member: {e.text}")
        elif e.kind == "assistant" and e.text:
            lines.append(f"[{e.seq}] Agent: {e.text}")
        elif e.kind == "tool_result":  # what a business system returned is looked up fresh: only that the lookup happened
            ok = "ok" if (e.data or {}).get("ok") else "an error"
            lines.append(f"[{e.seq}] Tool {(e.data or {}).get('name')} returned {ok}")
    return "\n".join(lines)


def _cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / denom) if denom else 0.0


def _event(m: MemberMemory, action: str, actor: str, call_id: str | None, before: str | None, after: str | None,
           reason: str | None = None) -> MemoryEvent:
    return MemoryEvent(tenant_id=m.tenant_id, agent_id=m.agent_id, member_ref=m.member_ref, memory_id=m.id, action=action,
                       actor=actor, call_id=call_id, text_before=before, text_after=after, reason=reason)


@jobs.register("extract_memory")
async def extract_memory(tenant_id: str, payload: dict[str, Any]) -> None:
    call_id = payload["call_id"]
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == call_id, Call.tenant_id == tenant_id))
        version = await s.get(AgentVersion, call.agent_version_id) if call else None
        config = version.config if version else {}
        if call is None or not applies(call, config):
            return
        cfg = settings_of(config)
        agent = await s.get(Agent, call.agent_id)
        events = list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())
        member = call.caller_ref
        facts, episodes = await load(s, tenant_id, call.agent_id, member)
        known = [f"- [{m.id}] {m.text}" for m in (*facts, *episodes)]
        prompt = prompts.render(
            "memory-extract", agent_name=agent.name if agent else "the agent", remember=cfg.remember,
            never_remember=cfg.never_remember, existing_memory="\n".join(known) or "- (none)", transcript=_transcript(events) or "(empty)",
        )
        out, _ = await gateway().complete_json("analysis", [{"role": "user", "content": prompt}], MemoryExtractOut)
        now = utcnow()

        episode = clean_episode(out.episode)
        if episode:  # one episode per call
            ep = MemberMemory(tenant_id=tenant_id, agent_id=call.agent_id, member_ref=member, kind="episode", category="outcome",
                              text=episode[:300], valid_at=now, expires_at=now + timedelta(days=cfg.episode_days),
                              source_call_id=call_id, prompt_version=PROMPT_VERSION)
            s.add(ep)
            await s.flush()
            s.add(_event(ep, "added", "agent", call_id, None, ep.text))

        seqs = {e.seq for e in events}
        for fact in out.facts[:5]:
            text = fact.text.strip()
            if not allowed(text):  # MEM-04: dropped whatever the model said
                log.info("memory candidate dropped by the exclusions on call %s", call_id)
                continue
            await _decide(s, tenant_id, call, text, fact.category, fact.seq if fact.seq in seqs else None, cfg)
        await s.commit()


async def _decide(s: AsyncSession, tenant_id: str, call: Call, text: str, category: str, seq: int | None, cfg: MemoryConfig) -> None:
    vector = await embed_one(text)
    active = (await s.scalars(select(MemberMemory).where(
        *_scope(tenant_id, call.agent_id, call.caller_ref or ""), MemberMemory.kind == "fact", MemberMemory.status == "active",
        MemberMemory.expires_at > utcnow(),
    ))).all()
    similar = sorted((m for m in active if m.embedding), key=lambda m: _cosine(vector, m.embedding), reverse=True)[:SIMILAR]
    lines = [f"- [{m.id}] ({m.updated_at:%Y-%m-%d}) {m.text}" for m in similar]
    prompt = prompts.render("memory-update", candidate=text, similar="\n".join(lines) or "- (none)")
    decision, _ = await gateway().complete_json("analysis", [{"role": "user", "content": prompt}], MemoryDecisionOut)
    target = next((m for m in similar if m.id == decision.target_id), None)
    action = decision.action
    if action in ("SUPERSEDE", "CONFIRM") and target is None:  # a target the model invented
        action = "ADD" if action == "SUPERSEDE" else "NOOP"
    now = utcnow()
    if action == "NOOP":
        return
    if action == "CONFIRM":
        target.expires_at = now + timedelta(days=cfg.fact_days)
        target.updated_at = now
        s.add(_event(target, "confirmed", "agent", call.id, target.text, target.text, decision.reason))
        return
    new = MemberMemory(tenant_id=tenant_id, agent_id=call.agent_id, member_ref=call.caller_ref, kind="fact", category=category,
                       text=text, valid_at=now, expires_at=now + timedelta(days=cfg.fact_days), source_call_id=call.id,
                       source_seq=seq, embedding=vector, prompt_version=PROMPT_VERSION)
    s.add(new)
    await s.flush()
    if action == "SUPERSEDE":  # MEM-03: retired, never deleted
        target.status, target.invalid_at, target.superseded_by = "retired", now, new.id
        s.add(_event(target, "superseded", "agent", call.id, target.text, new.text, decision.reason))
    s.add(_event(new, "added", "agent", call.id, None, new.text, decision.reason or None))


async def enqueue_extraction(s: AsyncSession, call: Call, config: dict[str, Any]) -> None:
    """Called when a session ends (MEM-01); the caller commits."""
    if applies(call, config):
        await jobs.enqueue(s, call.tenant_id, "extract_memory", {"call_id": call.id}, dedupe_key=f"extract_memory:{call.id}")


# ---------------------------------------------------------------- expiry (MEM-07)
@jobs.register("purge_memory")
async def purge_memory(tenant_id: str, payload: dict[str, Any]) -> None:
    async with sessionmaker()() as s:
        await purge(s, tenant_id)
        await s.commit()


async def purge(s: AsyncSession, tenant_id: str) -> int:
    expired = (await s.scalars(select(MemberMemory).where(MemberMemory.tenant_id == tenant_id, MemberMemory.expires_at <= utcnow()))).all()
    if not expired:
        return 0
    ids = [m.id for m in expired]
    await s.execute(update(MemoryEvent).where(MemoryEvent.tenant_id == tenant_id, MemoryEvent.memory_id.in_(ids))
                    .values(text_before=None, text_after=None, reason=None))
    for m in expired:
        s.add(_event(m, "expired", "system", None, None, None))
    await s.execute(delete(MemberMemory).where(MemberMemory.id.in_(ids)))
    return len(ids)


async def schedule_purges() -> None:
    """Once a day per tenant (dedupe key per date): the worker calls this when it is idle."""
    today = utcnow().date().isoformat()
    async with sessionmaker()() as s:
        for tenant_id in (await s.scalars(select(Tenant.id))).all():
            await jobs.enqueue(s, tenant_id, "purge_memory", {}, dedupe_key=f"purge_memory:{tenant_id}:{today}")
        await s.commit()


# ---------------------------------------------------------------- Studio actions (MEM-08, MEM-09, MEM-11)
async def member_view(s: AsyncSession, tenant_id: str, member_ref: str, agent_id: str | None) -> dict[str, Any] | None:
    rows = (await s.scalars(select(MemberMemory).where(MemberMemory.tenant_id == tenant_id, MemberMemory.member_ref == member_ref,
                                                       MemberMemory.expires_at > utcnow()))).all()
    events = (await s.scalars(select(MemoryEvent).where(MemoryEvent.tenant_id == tenant_id, MemoryEvent.member_ref == member_ref)
                              .order_by(MemoryEvent.at))).all()
    if not rows and not events:
        return None
    agent_ids = sorted({m.agent_id for m in rows} | {e.agent_id for e in events if e.agent_id})
    agents = (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id, Agent.id.in_(agent_ids)))).all() if agent_ids else []
    chosen = agent_id or (agents[0].id if agents else None)
    mine = [m for m in rows if m.agent_id == chosen]
    return {
        "member_ref": member_ref, "first_name": None,
        "agents": [{"id": a.id, "name": a.name} for a in sorted(agents, key=lambda a: a.name)],
        "facts": [item_dict(m) for m in sorted(mine, key=lambda m: m.updated_at, reverse=True) if m.kind == "fact" and m.status == "active"],
        "episodes": [item_dict(m) for m in sorted(mine, key=lambda m: m.created_at, reverse=True) if m.kind == "episode" and m.status == "active"],
        "retired": [item_dict(m) for m in sorted(mine, key=lambda m: m.invalid_at or m.updated_at, reverse=True) if m.status == "retired"],
        "events": [event_dict(e) for e in events if e.agent_id in (chosen, None)],
    }


async def restore(s: AsyncSession, tenant_id: str, member_ref: str, memory_id: str) -> MemberMemory | None:
    m = await s.scalar(select(MemberMemory).where(MemberMemory.id == memory_id, MemberMemory.tenant_id == tenant_id,
                                                  MemberMemory.member_ref == member_ref))
    if m is None:
        return None
    if m.status != "retired":
        raise ValueError("not_retired")
    m.status, m.invalid_at = "active", None
    m.updated_at = utcnow()
    s.add(_event(m, "restored", "studio", None, None, m.text))
    return m


async def erase(s: AsyncSession, tenant_id: str, member_ref: str) -> int:
    """MEM-08: everything every agent of the tenant remembers about the member; one content-free record remains."""
    count = len((await s.scalars(select(MemberMemory.id).where(MemberMemory.tenant_id == tenant_id, MemberMemory.member_ref == member_ref))).all())
    await s.execute(delete(MemberMemory).where(MemberMemory.tenant_id == tenant_id, MemberMemory.member_ref == member_ref))
    await s.execute(delete(MemoryEvent).where(MemoryEvent.tenant_id == tenant_id, MemoryEvent.member_ref == member_ref))
    s.add(MemoryEvent(tenant_id=tenant_id, agent_id=None, member_ref=member_ref, action="erased", actor="studio"))
    return count


async def export(s: AsyncSession, tenant_id: str, member_ref: str) -> dict[str, Any]:
    rows = (await s.scalars(select(MemberMemory).where(MemberMemory.tenant_id == tenant_id, MemberMemory.member_ref == member_ref)
                            .order_by(MemberMemory.created_at))).all()
    events = (await s.scalars(select(MemoryEvent).where(MemoryEvent.tenant_id == tenant_id, MemoryEvent.member_ref == member_ref)
                              .order_by(MemoryEvent.at))).all()
    return {"member_ref": member_ref, "exported_at": utcnow().isoformat(), "memories": [item_dict(m) for m in rows],
            "events": [event_dict(e) for e in events]}


async def for_call(s: AsyncSession, call: Call, events: list[CallEvent]) -> dict[str, Any] | None:
    """`memory` on a call's detail (API-06): what was loaded at verification and what the agent changed after the call."""
    used_ids: list[str] = []
    for e in events:
        if e.kind == "system" and "memory_used" in (e.data or {}):
            used_ids = list(e.data["memory_used"])
    changes = (await s.scalars(select(MemoryEvent).where(MemoryEvent.tenant_id == call.tenant_id, MemoryEvent.call_id == call.id,
                                                         MemoryEvent.actor == "agent").order_by(MemoryEvent.at))).all()
    if not used_ids and not changes and not any(e.kind == "system" and "memory_used" in (e.data or {}) for e in events):
        return None
    used = (await s.scalars(select(MemberMemory).where(MemberMemory.tenant_id == call.tenant_id, MemberMemory.id.in_(used_ids)))).all() if used_ids else []
    order = {i: n for n, i in enumerate(used_ids)}
    return {"used": [item_dict(m) for m in sorted(used, key=lambda m: order[m.id])], "updated": [event_dict(e) for e in changes]}
