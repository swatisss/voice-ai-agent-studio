"""Seeder: builds the demo database from the demo-data specs.

Spec: /demo-data/index.md, /demo-data/evergreen-health.md, /demo-data/call-history.md
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

import numpy as np
from sqlalchemy import select

from voiceai.agents import publish
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.knowledge import okf
from voiceai.knowledge.embeddings import embed
from voiceai.knowledge.ingest import import_okf
from voiceai.learning.analyze import refresh_stats
from voiceai.models import (
    Agent, Call, CallAnalysis, CallEvent, Cluster, Escalation, EvalScenario, Persona, Skill, Tenant, Tool,
)
from voiceai.schemas import FIXABLE
from voiceai.seed import catalog
from voiceai.seed.history import CLUSTERS, generate

log = logging.getLogger("voiceai.seed")


async def seed(reset: bool = False) -> dict[str, Any]:
    if reset:
        from voiceai.db import init_db

        await init_db(drop=True)
    kb_root = get_settings().specs_dir / "demo-data" / "kb"
    summary: dict[str, Any] = {}
    async with sessionmaker()() as s:
        if await s.scalar(select(Tenant.id).limit(1)):
            return {"skipped": "database already has tenants"}
        for t in catalog.TENANTS:
            s.add(Tenant(**t))
        await s.flush()

        agents: dict[str, Agent] = {}
        for tenant_id, tools_def, skills_def, agent_def, kb_dir in (
            (catalog.MEMBERS_TENANT, catalog.MEMBER_TOOLS, catalog.MEMBER_SKILLS, catalog.MEMBER_AGENT, "member-services"),
            (catalog.PHARMACY_TENANT, catalog.PHARMACY_TOOLS, catalog.PHARMACY_SKILLS, catalog.PHARMACY_AGENT, "pharmacy"),
        ):
            tools = [Tool(tenant_id=tenant_id, **t) for t in tools_def]
            skills = [Skill(tenant_id=tenant_id, **k) for k in skills_def]
            s.add_all(tools + skills)
            await s.flush()
            docs = await import_okf(s, tenant_id, okf.read_dir(kb_root / kb_dir), f"specs/demo-data/kb/{kb_dir}")
            ap = agent_def["persona"]
            library = [Persona(tenant_id=tenant_id, name=ap["name"], description=agent_def["description"], voice=ap["voice"], speed=ap.get("speed", 1.0),
                               greeting=ap["greeting"], disclosure=ap["disclosure"], opening=ap.get("opening", ""), style=ap["style"])]
            library += [Persona(tenant_id=tenant_id, **extra) for extra in catalog.EXTRA_PERSONAS.get(tenant_id, [])]
            s.add_all(library)
            await s.flush()
            cfg = {
                "persona_id": library[0].id,
                "voice": {"turn_detection": catalog.VOICE_DEFAULTS.get(tenant_id, {})},
                "persona": agent_def["persona"],
                "policy": agent_def["policy"],
                "tool_ids": [t.id for t in tools], "skill_ids": [k.id for k in skills],
                "knowledge_doc_ids": [d.id for d in docs], "models": {"realtime": None},
            }
            agent = Agent(tenant_id=tenant_id, name=agent_def["name"], description=agent_def["description"], draft_config=cfg)
            s.add(agent)
            await s.flush()
            version = await publish(s, agent, "Initial version")
            agents[tenant_id] = agent
            summary[tenant_id] = {"agent_id": agent.id, "version_id": version.id, "tools": len(tools), "skills": len(skills), "docs": len(docs)}

        member_agent = agents[catalog.MEMBERS_TENANT]
        for sc in catalog.MEMBER_SCENARIOS:
            s.add(EvalScenario(tenant_id=catalog.MEMBERS_TENANT, agent_id=member_agent.id, **sc))
        summary["history_calls"] = await _seed_history(s, member_agent)
        await s.commit()
    log.info("seeded: %s", summary)
    return summary


async def _seed_history(s, agent: Agent) -> int:  # noqa: ANN001
    calls = generate()
    version_id = agent.published_version_id
    analyses_by_key: dict[str, list[CallAnalysis]] = defaultdict(list)
    for sc in calls:
        turns = sum(1 for k, _, _ in sc.events if k == "user")
        call = Call(
            tenant_id=agent.tenant_id, agent_id=agent.id, agent_version_id=version_id, channel="voice",
            status="ended", outcome=sc.outcome, caller_ref=sc.member_ref, started_at=sc.started_at,
            ended_at=sc.started_at + timedelta(seconds=40 + 25 * turns), end_reason="hangup" if sc.outcome != "resolved" else "end_call",
            turn_count=turns, tokens_in=1800 * max(turns, 1), tokens_out=60 * max(turns, 1), llm_cost_usd=sc.cost,
            latency_p50_ms=sc.latency_ms, is_seed=True,
            meta={"state": {"tools_used": sc.tools_used, "verified_member_ref": sc.member_ref}},
        )
        s.add(call)
        await s.flush()
        for i, (kind, text, data) in enumerate(sc.events, 1):
            s.add(CallEvent(tenant_id=agent.tenant_id, call_id=call.id, seq=i, kind=kind, text=text, data=data,
                            at=sc.started_at + timedelta(seconds=6 * i)))
        if sc.escalation:
            e = sc.escalation
            created = sc.started_at + timedelta(seconds=6 * len(sc.events))
            s.add(Escalation(
                tenant_id=agent.tenant_id, call_id=call.id, agent_id=agent.id, status="resolved", reason_category=e["category"],
                reason_detail=e["detail"], packet=e["packet"], packet_status="ready", assignee=e["assignee"],
                disposition=e["disposition"], resolution_note=e["note"], created_at=created,
                accepted_at=created + timedelta(minutes=2), resolved_at=created + timedelta(minutes=9),
            ))
        a = sc.analysis
        analysis = CallAnalysis(tenant_id=agent.tenant_id, call_id=call.id, agent_id=agent.id, fixable=a["root_cause"] in FIXABLE, source="seed", **a)
        s.add(analysis)
        if sc.cluster_key:
            analyses_by_key[sc.cluster_key].append(analysis)
    await s.flush()

    for key, members in analyses_by_key.items():
        vectors = await embed([m.gap_summary for m in members], "passage")
        for m, v in zip(members, vectors):
            m.embedding = [round(float(x), 6) for x in v]
        centroid = np.mean(vectors, axis=0)
        centroid = centroid / (np.linalg.norm(centroid) or 1.0)
        name, description = CLUSTERS[key]
        root = members[0].root_cause
        cluster = Cluster(tenant_id=agent.tenant_id, agent_id=agent.id, name=name, description=description, root_cause=root,
                          fixable=root in FIXABLE, centroid=[round(float(x), 6) for x in centroid])
        s.add(cluster)
        await s.flush()
        for m in members:
            m.cluster_id = cluster.id
        await s.flush()
        await refresh_stats(s, cluster)
    return len(calls)
