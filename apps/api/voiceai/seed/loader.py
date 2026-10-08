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
from voiceai.core.config import get_settings
from voiceai.core.db import sessionmaker
from voiceai.knowledge import okf
from voiceai.core.embeddings import embed
from voiceai.knowledge.ingest import import_okf
from voiceai.learning.analyze import refresh_stats
from voiceai.live import persona_dict
from voiceai.mock import data as mock_data
from voiceai.core.tables import (
    Agent, Call, CallAnalysis, CallEvent, Cluster, Escalation, EvalScenario, Persona, Skill, Tenant, Tool, UseCase,
)
from voiceai.schemas import FIXABLE
from voiceai.seed import catalog
from voiceai.seed.history import CLUSTERS, generate

log = logging.getLogger("voiceai.seed")


async def seed(reset: bool = False) -> dict[str, Any]:
    if reset:
        from voiceai.core.db import init_db

        await init_db(drop=True)
    mock_data.reset()  # date-relative business records restart together with the database
    kb_root = get_settings().specs_dir / "demo-data" / "kb"
    summary: dict[str, Any] = {}
    care = catalog.CARE_TENANT
    async with sessionmaker()() as s:
        if await s.scalar(select(Tenant.id).limit(1)):
            return {"skipped": "database already has tenants"}
        for t in catalog.TENANTS:
            s.add(Tenant(**t))
        await s.flush()

        tools = {t["name"]: Tool(tenant_id=care, **t) for t in catalog.TOOLS}
        personas = {p["name"]: Persona(tenant_id=care, **p) for p in catalog.PERSONAS}
        s.add_all([*tools.values(), *personas.values()])
        await s.flush()

        agents: dict[str, Agent] = {}
        for ad in catalog.AGENTS:
            skills = [Skill(tenant_id=care, **k) for k in ad["skills"]]
            s.add_all(skills)
            await s.flush()
            docs = await import_okf(s, care, okf.read_dir(kb_root / ad["kb"]), f"specs/demo-data/kb/{ad['kb']}")
            persona = personas[ad["persona"]]
            cfg: dict[str, Any] = {
                "mode": ad["mode"],
                "persona_id": persona.id,
                "persona": {k: v for k, v in persona_dict(persona).items() if k != "id"},
                "voice": {"turn_detection": ad["turn_detection"]},
                "policy": ad["policy"],
                "tool_ids": [tools[n].id for n in ad["tools"]], "skill_ids": [k.id for k in skills],
                "knowledge_doc_ids": [d.id for d in docs], "models": {"realtime": None},
            }
            if ad["mode"] == "outbound":
                cfg["outbound"] = {"targets_url": ad["targets_url"]}
            agent = Agent(tenant_id=care, name=ad["name"], description=ad["description"], draft_config=cfg)
            s.add(agent)
            await s.flush()
            version = await publish(s, agent, "Initial version")
            agents[ad["key"]] = agent
            summary[ad["key"]] = {"agent_id": agent.id, "version_id": version.id, "tools": len(ad["tools"]), "skills": len(skills), "docs": len(docs)}
        summary["tools"] = len(tools)

        sandbox_docs = await import_okf(s, catalog.SANDBOX_TENANT, okf.read_dir(kb_root / catalog.SANDBOX_KB), f"specs/demo-data/kb/{catalog.SANDBOX_KB}")
        summary["sandbox_docs"] = len(sandbox_docs)

        care_agent = agents["care"]
        for sc in catalog.SCENARIOS:
            s.add(EvalScenario(tenant_id=care, agent_id=care_agent.id, **sc))
        for i, uc in enumerate(catalog.USE_CASES, 1):
            s.add(UseCase(
                tenant_id=care, agent_id=agents[uc["agent"]].id, category=catalog.CATEGORY, title=uc["title"], summary=uc["summary"],
                channels=["voice", "chat"], sample_utterances=uc["sample_utterances"], demo_callers=uc["demo_callers"], sort=i,
            ))
        summary["use_cases"] = len(catalog.USE_CASES)
        summary["history_calls"] = await _seed_history(s, care_agent)
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
            tenant_id=agent.tenant_id, agent_id=agent.id, agent_version_id=version_id, channel="voice", direction="inbound",
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
