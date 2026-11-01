"""The capability catalog: one profile per published, routable agent, re-indexed automatically; Stage A search.

Spec: /architecture/capability-catalog.md, /architecture/supervisor-routing.md (Decision, step 2), /prompts/capability-utterances.md
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs, prompts
from voiceai.db import sessionmaker, utcnow
from voiceai.events import bus
from voiceai.knowledge import search as kb_search
from voiceai.knowledge.embeddings import embed
from voiceai.llm.gateway import gateway
from voiceai.models import Agent, AgentVersion, CapabilityEntry, CapabilityProfile, Job, KnowledgeDoc, RoutingCase, UseCase

log = logging.getLogger("voiceai.routing.catalog")

SCOPE_OF_MODE = {"inbound": "member", "internal": "staff"}
SUMMARY_MAX = 600
GENERATED_MIN, GENERATED_MAX = 10, 20
TEST_PER_USE_CASE = 3
KNOWLEDGE_WEIGHT = 0.85  # /architecture/supervisor-routing.md (Stage A)
_cache: dict[tuple[str, str], tuple[list[str], np.ndarray, dict[str, list[str]]]] = {}


class Utterances(BaseModel):
    utterances: list[str] = Field(default_factory=list)


def invalidate(tenant_id: str | None = None) -> None:
    for key in [k for k in _cache if tenant_id is None or k[0] == tenant_id]:
        _cache.pop(key, None)


def scope_of(config: dict[str, Any]) -> str | None:
    return SCOPE_OF_MODE.get(config.get("mode", "inbound"))


def routable(config: dict[str, Any]) -> bool:
    """CAT-01: published inbound or internal agents with `routable` on."""
    return scope_of(config) is not None and bool(config.get("routable", True))


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


# ---------------------------------------------------------------- triggers
async def enqueue_index(s: AsyncSession, tenant_id: str, agent_id: str) -> None:
    """Queue a re-index unless one for this agent is already waiting (caller commits)."""
    waiting = await s.scalars(select(Job).where(Job.tenant_id == tenant_id, Job.kind == "index_capabilities", Job.status == "queued"))
    if any(j.payload.get("agent_id") == agent_id for j in waiting):
        return
    await jobs.enqueue(s, tenant_id, "index_capabilities", {"agent_id": agent_id})


async def enqueue_for_doc(s: AsyncSession, tenant_id: str, doc_id: str) -> int:
    """CAT-03: every published agent whose snapshot lists the doc."""
    rows = (await s.execute(select(Agent, AgentVersion).join(AgentVersion, AgentVersion.id == Agent.published_version_id)
                            .where(Agent.tenant_id == tenant_id))).all()
    n = 0
    for agent, version in rows:
        if doc_id in (version.config.get("knowledge_doc_ids") or []):
            await enqueue_index(s, tenant_id, agent.id)
            n += 1
    return n


# ---------------------------------------------------------------- building a profile
async def _use_cases(s: AsyncSession, tenant_id: str, agent_id: str) -> list[UseCase]:
    return list((await s.scalars(select(UseCase).where(UseCase.tenant_id == tenant_id, UseCase.agent_id == agent_id).order_by(UseCase.sort, UseCase.title))).all())


def _card(agent: Agent, config: dict[str, Any], cases: list[UseCase], docs: list[KnowledgeDoc]) -> dict[str, Any]:
    return {
        "name": agent.name,
        "description": (config.get("description") or "").strip(),
        "skills": [{"id": u.id, "title": u.title, "summary": u.summary or "", "examples": list(u.sample_utterances or [])} for u in cases],
        "tools": [{"name": t["name"], "description": t.get("description", "")} for t in config.get("tools", [])],
        "knowledge": [{"doc_id": d.id, "title": d.title} for d in docs],
    }


def summary_of(card: dict[str, Any]) -> str:
    """The text a decision model sees: description, use-case titles, up to 8 tool descriptions, ≤ 600 chars."""
    parts = [card.get("description") or card.get("name", "")]
    if card.get("skills"):
        parts.append("Handles: " + "; ".join(sk["title"] for sk in card["skills"]) + ".")
    tools = [t["description"].strip().rstrip(".") for t in card.get("tools", [])[:8] if t.get("description", "").strip()]
    if tools:
        parts.append("Can: " + "; ".join(tools) + ".")
    return " ".join(p for p in parts if p)[:SUMMARY_MAX]


def profile_text(card: dict[str, Any]) -> str:
    lines = [f"Name: {card['name']}", f"Description: {card.get('description') or '(none)'}", "Use cases:"]
    for sk in card.get("skills", []):
        lines.append(f"- {sk['title']}: {sk['summary']}")
        lines += [f"  e.g. \"{x}\"" for x in sk["examples"][:5]]
    if card.get("tools"):
        lines.append("Tools: " + "; ".join(f"{t['name']} ({t['description']})" for t in card["tools"]))
    if card.get("knowledge"):
        lines.append("Knowledge: " + "; ".join(k["title"] for k in card["knowledge"][:20]))
    return "\n".join(lines)


async def write_utterances(card: dict[str, Any], audience: str, purpose: str, focus: str, count: int) -> list[str]:
    """The capability utterances prompt (role `drafting`); failures give an empty list (the profile is still built)."""
    content = prompts.render("capability-utterances", audience=audience, profile=profile_text(card), purpose=purpose, focus=focus, count=count)
    try:
        out, _ = await gateway().complete_json("drafting", [{"role": "user", "content": content}], Utterances)
    except Exception as exc:  # noqa: BLE001 - the catalog must not depend on the drafting model
        log.warning("capability utterances (%s) failed: %s", purpose, exc)
        return []
    seen: set[str] = set()
    result = []
    for u in out.utterances:
        text = " ".join(str(u).split())[:200]
        if len(text) >= 3 and text.lower() not in seen:
            seen.add(text.lower())
            result.append(text)
    return result[:count]


@dataclass
class IndexResult:
    status: str  # built | unchanged | removed | skipped
    profile_id: str | None = None


async def index_agent(tenant_id: str, agent_id: str) -> IndexResult:
    """Build (or remove) one agent's profile; unchanged inputs do no LLM or embedding work (CAT-04)."""
    async with sessionmaker()() as s:
        agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
        version = await s.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
        existing = await s.scalar(select(CapabilityProfile).where(CapabilityProfile.agent_id == agent_id, CapabilityProfile.tenant_id == tenant_id))
        if agent is None or version is None or not routable(version.config):
            if existing is not None:
                await s.execute(delete(CapabilityEntry).where(CapabilityEntry.profile_id == existing.id))
                await s.delete(existing)
                await s.execute(delete(RoutingCase).where(RoutingCase.expected_agent_id == agent_id, RoutingCase.source == "generated"))
                await s.commit()
                invalidate(tenant_id)
                return IndexResult("removed")
            return IndexResult("skipped")
        config = version.config
        cases = await _use_cases(s, tenant_id, agent_id)
        doc_ids = list(config.get("knowledge_doc_ids") or [])
        docs = list((await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.id.in_(doc_ids),
                                                                KnowledgeDoc.status == "active").order_by(KnowledgeDoc.title))).all())
        card = _card(agent, config, cases, docs)
        input_hash = _hash({"card": card, "version": version.id})
        if existing is not None and existing.input_hash == input_hash and existing.status == "ready":
            return IndexResult("unchanged", existing.id)
        if existing is not None:
            existing.status = "indexing"
            await s.commit()
        scope = scope_of(config) or "member"
        gen_inputs = _hash({k: card[k] for k in ("description", "skills", "tools")})
        prev = (existing.card if existing is not None else {}) or {}
        if prev.get("generated_inputs") == gen_inputs:
            generated = list(prev.get("generated_examples") or [])
        else:
            generated = await write_utterances(card, "members" if scope == "member" else "staff", "index", "(all)", 15)
        card.update(generated_examples=generated, generated_inputs=gen_inputs)

        entries: list[tuple[str, str | None, str]] = []
        if card["description"]:
            entries.append(("description", None, card["description"]))
        for sk in card["skills"]:
            entries.append(("use_case", sk["id"], f"{sk['title']}. {sk['summary']}".strip()))
            entries += [("utterance", sk["id"], x) for x in sk["examples"]]
        entries += [("generated", None, x) for x in generated]
        entries += [("tool", t["name"], t["description"]) for t in card["tools"] if t["description"].strip()]
        try:
            vectors = await embed([e[2] for e in entries]) if entries else np.zeros((0, 1))
        except Exception as exc:  # noqa: BLE001 - CAT: a failed build keeps the previous profile
            if existing is not None:
                existing.status, existing.error = "ready", f"index failed: {exc}"
                await s.commit()
            raise
        if existing is None:
            existing = CapabilityProfile(tenant_id=tenant_id, agent_id=agent_id, agent_version_id=version.id, scope=scope)
            s.add(existing)
            await s.flush()
        await s.execute(delete(CapabilityEntry).where(CapabilityEntry.profile_id == existing.id))
        for (kind, ref, text), vec in zip(entries, vectors):
            s.add(CapabilityEntry(tenant_id=tenant_id, agent_id=agent_id, profile_id=existing.id, kind=kind, ref=ref, text=text,
                                  embedding=[float(x) for x in vec]))
        card["case_hashes"] = await _sync_cases(s, tenant_id, agent_id, scope, card, prev.get("case_hashes") or {},
                                                {e[2].lower() for e in entries})
        existing.card, existing.summary, existing.scope = card, summary_of(card), scope
        existing.agent_version_id, existing.input_hash = version.id, input_hash
        existing.status, existing.error, existing.built_at = "ready", None, utcnow()
        await s.commit()
        profile_id = existing.id
    invalidate(tenant_id)
    bus.publish(tenant_id, "evaluation", "catalog.updated", {"agent_id": agent_id, "status": "ready", "built_at": utcnow().isoformat()})
    return IndexResult("built", profile_id)


async def _sync_cases(s: AsyncSession, tenant_id: str, agent_id: str, scope: str, card: dict[str, Any],
                      previous: dict[str, str], indexed: set[str]) -> dict[str, str]:
    """Generated routing cases: up to 3 held-out paraphrases per use case, never one of the indexed texts (CAT-07)."""
    hashes: dict[str, str] = {}
    current_ids = {sk["id"] for sk in card["skills"]}
    stale = [uid for uid in previous if uid not in current_ids]
    if stale:
        await s.execute(delete(RoutingCase).where(RoutingCase.use_case_id.in_(stale), RoutingCase.source == "generated"))
    for sk in card["skills"]:
        h = _hash(sk)
        hashes[sk["id"]] = h
        if previous.get(sk["id"]) == h:
            continue
        await s.execute(delete(RoutingCase).where(RoutingCase.use_case_id == sk["id"], RoutingCase.source == "generated"))
        focused = {**card, "skills": [sk]}
        for text in await write_utterances(focused, "members" if scope == "member" else "staff", "test", sk["title"], TEST_PER_USE_CASE):
            if text.lower() in indexed:
                continue
            s.add(RoutingCase(tenant_id=tenant_id, utterance=text[:300], expected_agent_id=agent_id, scope=scope, source="generated",
                              use_case_id=sk["id"], enabled=True))
    return hashes


@jobs.register("index_capabilities")
async def index_capabilities(tenant_id: str, payload: dict[str, Any]) -> None:
    result = await index_agent(tenant_id, payload["agent_id"])
    if result.status in ("built", "removed"):
        from voiceai.routing import suite

        async with sessionmaker()() as s:
            await suite.enqueue_run(s, tenant_id, trigger="catalog")  # CAT-08: at most one queued run per tenant
            await s.commit()


# ---------------------------------------------------------------- Stage A
async def _tenant_matrix(s: AsyncSession, tenant_id: str, scope: str) -> tuple[list[str], np.ndarray, dict[str, list[str]]]:
    """(agent id per row, entry matrix, knowledge doc ids per agent) for the scope's profiles; cached until re-index."""
    key = (tenant_id, scope)
    if key in _cache:
        return _cache[key]
    profiles = (await s.scalars(select(CapabilityProfile).where(CapabilityProfile.tenant_id == tenant_id, CapabilityProfile.scope == scope))).all()
    ids = [p.id for p in profiles]
    rows = (await s.scalars(select(CapabilityEntry).where(CapabilityEntry.profile_id.in_(ids)))).all() if ids else []
    agents = [r.agent_id for r in rows]
    mat = np.array([r.embedding for r in rows], dtype=np.float32) if rows else np.zeros((0, 1), dtype=np.float32)
    docs: dict[str, list[str]] = {}
    for p in profiles:
        version = await s.get(AgentVersion, p.agent_version_id)
        docs[p.agent_id] = list((version.config.get("knowledge_doc_ids") if version else []) or [])
    _cache[key] = (agents, mat, docs)
    return agents, mat, docs


async def stage_a(s: AsyncSession, tenant_id: str, scope: str, text: str, candidates: set[str] | None = None) -> list[dict[str, Any]]:
    """Every candidate's best cosine similarity over its entries and (× 0.85) its knowledge chunks, best first."""
    agents, mat, docs = await _tenant_matrix(s, tenant_id, scope)
    pool = set(agents) | set(docs)
    if candidates is not None:
        pool &= candidates
    if not pool or not text.strip():
        return []
    q = (await embed([text], "query"))[0]
    best: dict[str, float] = dict.fromkeys(pool, 0.0)
    if len(agents):
        scores = mat @ q
        for agent_id, score in zip(agents, scores):
            if agent_id in best and score > best[agent_id]:
                best[agent_id] = float(score)
    for agent_id in pool:
        if docs.get(agent_id):
            kmat, _ = await kb_search._matrix(s, tenant_id, docs[agent_id])
            if len(kmat) and kmat.shape[1] == len(q):
                best[agent_id] = max(best[agent_id], float(np.max(kmat @ q)) * KNOWLEDGE_WEIGHT)
    return [{"agent_id": a, "score": round(v, 4)} for a, v in sorted(best.items(), key=lambda kv: -kv[1])]
