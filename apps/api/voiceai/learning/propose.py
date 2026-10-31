"""Fix drafting from cluster evidence, proposal editing, approval and rejection.

Spec: /architecture/fleet-learning.md (4. Fix drafting, 5. Approval), /architecture/self-learning.md (Proposal kinds, Review), /prompts/fix-draft.md
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs, prompts
from voiceai.agents import publish
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.knowledge.ingest import create_doc
from voiceai.knowledge.search import search as kb_search
from voiceai.llm.gateway import gateway
from voiceai.models import (
    Agent, AgentVersion, Call, CallAnalysis, CallFeedback, Cluster, Escalation, EvalRun, EvalScenario, FixProposal, KnowledgeDoc, Skill, Tool,
)
from voiceai.schemas import FixDraft, SkillDef, ToolDef

# Endpoints of the tenant's business API that exist but are not tools yet (fix drafting may target them).
TOOL_CATALOG: dict[str, list[dict[str, Any]]] = {
    "evergreen-care": [
        {"method": "GET", "url": "/mock/healthcare/prior-auths/{auth_id}",
         "description": "Status of a prior authorization by number (e.g. PA-77930) for the verified member.",
         "parameters": {"type": "object", "properties": {"auth_id": {"type": "string", "description": "Authorization number like PA-77930"}}, "required": ["auth_id"]}},
    ],
}


def proposal_summary(p: FixProposal) -> dict[str, Any]:
    return {
        "id": p.id, "agent_id": p.agent_id, "cluster_id": p.cluster_id, "kind": p.kind, "origin": p.origin, "title": p.title,
        "rationale": p.rationale, "payload": p.payload, "draft_doc_id": p.draft_doc_id, "status": p.status,
        "latest_eval_run_id": p.latest_eval_run_id, "resulting_version_id": p.resulting_version_id,
        "decided_by": p.decided_by, "decision_note": p.decision_note,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
    }


async def cluster_evidence(s: AsyncSession, cluster_id: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = (await s.execute(
        select(CallAnalysis, Escalation, Call, CallFeedback)
        .join(Call, Call.id == CallAnalysis.call_id)
        .outerjoin(Escalation, Escalation.call_id == CallAnalysis.call_id)
        .outerjoin(CallFeedback, CallFeedback.call_id == CallAnalysis.call_id)
        .where(CallAnalysis.cluster_id == cluster_id)
        .order_by(Call.started_at.desc())
        .limit(limit)
    )).all()
    return [
        {
            "call_id": a.call_id, "date": c.started_at.isoformat(), "caller_goal": a.caller_goal, "gap_summary": a.gap_summary,
            "resolution_note": (e.resolution_note if e else "") or a.resolution_summary, "caller_ref": c.caller_ref,
            "verified": bool(c.caller_ref), "root_cause": a.root_cause, "outcome": a.outcome,
            "feedback": {"rating": f.rating, "comment": f.comment or ""} if f else None,  # UI-37
        }
        for a, e, c, f in rows
    ]


DERIVED_SCENARIOS = 2


async def _attached_articles(s: AsyncSession, tenant_id: str, cfg: dict[str, Any], cluster: Cluster, evidence: list[dict[str, Any]]) -> list[KnowledgeDoc]:
    """Up to 3 attached articles closest to the cluster's gap (the candidates for a knowledge_edit)."""
    doc_ids = list(cfg.get("knowledge_doc_ids", []))
    if not doc_ids:
        return []
    found: list[str] = []
    for query in [cluster.name, *(e["gap_summary"] for e in evidence[:3] if e["gap_summary"])]:
        result = await kb_search(s, tenant_id, doc_ids, query, top_k=3)
        for r in result.get("results", []):
            if r["doc_id"] not in found:
                found.append(r["doc_id"])
    docs = {d.id: d for d in (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.id.in_(found[:3])))).all()}
    return [docs[i] for i in found[:3] if i in docs]


def derived_scenarios(cluster: Cluster, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """SL-09: up to 2 test scenarios from the evidence calls (verified callers keep their member profile)."""
    from voiceai.learning.evaluate import member_profile

    out = []
    for e in evidence:
        if len(out) >= DERIVED_SCENARIOS:
            break
        if not e["caller_goal"]:
            continue
        out.append({"name": f"{cluster.name[:90]} ({len(out) + 1})", "caller_goal": e["caller_goal"],
                    "caller_profile": member_profile(e["caller_ref"], e["call_id"]) if e["verified"] else {},
                    "persona": "calm", "expected": "resolved", "required_tools": [], "forbidden_tools": [],
                    "expected_results": [], "memory": [], "enabled": True, "source_call_id": e["call_id"]})
    return out


async def draft(s: AsyncSession, tenant_id: str, cluster: Cluster, origin: str = "manual") -> FixProposal:
    """Draft one typed config change for a cluster from its evidence (fleet learning §4, self-learning Proposal kinds)."""
    agent = await s.get(Agent, cluster.agent_id)
    version = await s.get(AgentVersion, agent.published_version_id) if agent and agent.published_version_id else None
    cfg = version.config if version else {}
    evidence = await cluster_evidence(s, cluster.id)  # the drafter sees only these; the rest are held out (SL-08)
    doc_titles = list((await s.scalars(select(KnowledgeDoc.title).where(KnowledgeDoc.id.in_(cfg.get("knowledge_doc_ids", []))))).all())
    attached = await _attached_articles(s, tenant_id, cfg, cluster, evidence)
    own = {t["name"] for t in cfg.get("tools", [])}
    unattached = [t for t in (await s.scalars(select(Tool).where(Tool.tenant_id == tenant_id, Tool.status == "active"))).all() if t.name not in own]
    catalog = TOOL_CATALOG.get(tenant_id, [])
    prompt = prompts.render(
        "fix-draft",
        cluster_name=cluster.name, cluster_description=cluster.description, root_cause=cluster.root_cause,
        evidence="\n".join(f"- Goal: {e['caller_goal']} | Gap: {e['gap_summary']} | Specialist: {e['resolution_note'] or '(no note)'}" for e in evidence),
        attached_articles="\n\n".join(f"[{d.id}] {d.title}\n{d.content[:3000]}" for d in attached) or "(none)",
        existing_tools="\n".join(f"- {t['name']}: {t['description']}" for t in cfg.get("tools", [])) or "- (none)",
        unattached_tools="\n".join(f"- {t.name}: {t.description}" for t in unattached) or "- (none)",
        tool_catalog="\n".join(f"- {c['method']} {c['url']}: {c['description']} params={c['parameters']}" for c in catalog) or "- (none)",
        existing_doc_titles=", ".join(doc_titles) or "(none)",
    )
    out, _ = await gateway().complete_json("drafting", [{"role": "user", "content": prompt}], FixDraft)
    kind = out.kind
    if kind == "knowledge_edit" and out.doc_id not in {d.id for d in attached}:
        kind = "knowledge_article"  # an edit must target an article the drafter was shown
    tool = next((t for t in unattached if t.name == out.tool_name), None) if kind == "tool_attach" else None
    if kind == "tool_attach" and tool is None:
        raise ValueError(f"tool_attach names no unattached tool of the tenant: {out.tool_name!r}")
    proposal = FixProposal(tenant_id=tenant_id, agent_id=cluster.agent_id, cluster_id=cluster.id, kind=kind, origin=origin,
                           title=out.title[:300], rationale=out.rationale)
    if kind in ("knowledge_article", "knowledge_edit"):
        article = out.article or {"title": out.title, "content_markdown": out.rationale}
        art = article if isinstance(article, dict) else article.model_dump()
        doc = await create_doc(s, tenant_id, art["title"], art["content_markdown"], "proposal", f"cluster:{cluster.id}", {"cluster": cluster.name}, status="draft")
        proposal.draft_doc_id = doc.id
        proposal.payload = {"article": art, **({"doc_id": out.doc_id} if kind == "knowledge_edit" else {})}
    elif kind == "tool_attach":
        from voiceai.agents import tool_dict

        proposal.payload = {"tool_name": tool.name, "tool": tool_dict(tool)}
    elif kind == "skill":
        if not out.skill:
            raise ValueError("skill draft missing 'skill'")
        tool_def = ToolDef.model_validate(out.tool).model_dump() if out.tool else None
        proposal.payload = {"skill": out.skill.model_dump(), "tool": tool_def, "existing_tool_name": out.existing_tool_name}
    else:
        proposal.payload = {"rule": out.rule or out.title}
    proposal.payload = {**proposal.payload, "evidence_call_ids": [e["call_id"] for e in evidence],
                        "scenarios": derived_scenarios(cluster, evidence)}
    s.add(proposal)
    cluster.status = "fix_proposed"
    await s.flush()
    return proposal


@jobs.register("draft_fix")
async def draft_fix(tenant_id: str, payload: dict[str, Any]) -> None:
    async with sessionmaker()() as s:
        cluster = await s.scalar(select(Cluster).where(Cluster.id == payload["cluster_id"], Cluster.tenant_id == tenant_id))
        if not cluster or cluster.status != "open":
            return
        proposal = await draft(s, tenant_id, cluster, payload.get("origin", "manual"))
        await s.commit()
        bus.publish(tenant_id, "insights", "proposal.updated", proposal_summary(proposal))


async def get_proposal(s: AsyncSession, tenant_id: str, proposal_id: str) -> FixProposal:
    p = await s.scalar(select(FixProposal).where(FixProposal.id == proposal_id, FixProposal.tenant_id == tenant_id))
    if not p:
        raise ApiError(404, "proposal_not_found", "Proposal not found")
    return p


async def update_proposal(s: AsyncSession, p: FixProposal, title: str | None, payload: dict[str, Any] | None) -> FixProposal:
    if p.status not in ("draft", "ready"):
        raise ApiError(409, "invalid_state", f"Proposal is {p.status}")
    if title:
        p.title = title[:300]
    if payload is not None:
        if p.kind in ("knowledge_article", "knowledge_edit"):
            art = payload.get("article") or {}
            if not art.get("content_markdown"):
                raise ApiError(422, "invalid_payload", "article.content_markdown is required")
            doc = await s.get(KnowledgeDoc, p.draft_doc_id) if p.draft_doc_id else None
            if doc:
                doc.status = "archived"
            new = await create_doc(s, p.tenant_id, art.get("title") or p.title, art["content_markdown"], "proposal", f"cluster:{p.cluster_id}", status="draft")
            p.draft_doc_id = new.id
            payload = {**p.payload, **payload}  # keep doc_id, evidence and derived scenarios
        elif p.kind == "skill":
            SkillDef.model_validate(payload.get("skill") or {})
            if payload.get("tool"):
                ToolDef.model_validate(payload["tool"])
        p.payload = payload
    p.status = "draft"  # edits require re-evaluation
    await s.commit()
    bus.publish(p.tenant_id, "insights", "proposal.updated", proposal_summary(p))
    return p


def candidate_config(base: dict[str, Any], p: FixProposal) -> dict[str, Any]:
    """Apply the proposal in memory to a version snapshot (evaluation candidate arm)."""
    cfg = copy.deepcopy(base)
    if p.kind == "knowledge_article" and p.draft_doc_id:
        cfg["knowledge_doc_ids"] = [*cfg.get("knowledge_doc_ids", []), p.draft_doc_id]
    elif p.kind == "knowledge_edit" and p.draft_doc_id:
        old = p.payload.get("doc_id")
        cfg["knowledge_doc_ids"] = [d for d in cfg.get("knowledge_doc_ids", []) if d != old] + [p.draft_doc_id]
    elif p.kind == "tool_attach" and p.payload.get("tool"):
        if p.payload["tool"]["name"] not in {t["name"] for t in cfg.get("tools", [])}:
            cfg["tools"] = [*cfg.get("tools", []), p.payload["tool"]]
    elif p.kind == "skill":
        skill = dict(p.payload.get("skill") or {})
        tool = p.payload.get("tool")
        if tool and tool["name"] not in {t["name"] for t in cfg.get("tools", [])}:
            cfg["tools"] = [*cfg.get("tools", []), {"id": "candidate", **tool}]
        cfg["skills"] = [*cfg.get("skills", []), {"id": "candidate", **skill}]
    elif p.kind == "policy_rule":
        cfg.setdefault("policy", {}).setdefault("rules", []).append(p.payload.get("rule", ""))
    return cfg


async def approve(s: AsyncSession, p: FixProposal, decided_by: str, note: str | None, force: bool) -> AgentVersion:
    if p.status != "ready":
        raise ApiError(409, "invalid_state", "Run an evaluation before approving")
    run = await s.get(EvalRun, p.latest_eval_run_id) if p.latest_eval_run_id else None
    summary = run.summary if run and run.status == "done" else None
    if not summary:
        raise ApiError(409, "no_evaluation", "No completed evaluation for this proposal")
    gate = summary.get("gate") or {}
    if not gate.get("passed") and not (force and note):  # FL-06, SL-10
        reason = "; ".join(gate.get("reasons") or []) or "the evaluation gate did not pass"
        raise ApiError(409, "evaluation_gate", f"Approval blocked: {reason}. Use force with a note to override.")
    agent = await s.get(Agent, p.agent_id)
    assert agent is not None
    draft = copy.deepcopy(agent.draft_config or {})
    if p.kind in ("knowledge_article", "knowledge_edit") and p.draft_doc_id:
        doc = await s.get(KnowledgeDoc, p.draft_doc_id)
        if doc:
            doc.status = "active"
        ids = list(draft.get("knowledge_doc_ids", []))
        if p.kind == "knowledge_edit":  # SL-06: the revised article replaces the old one, which is archived
            old = await s.get(KnowledgeDoc, p.payload.get("doc_id") or "")
            if old:
                old.status = "archived"
            ids = [d for d in ids if d != p.payload.get("doc_id")]
        draft["knowledge_doc_ids"] = [*ids, p.draft_doc_id]
    elif p.kind == "tool_attach":  # SL-07: an existing tool, attached; no new tool row
        tool = await s.scalar(select(Tool).where(Tool.tenant_id == p.tenant_id, Tool.name == p.payload.get("tool_name")))
        if tool is None:
            raise ApiError(409, "tool_not_found", f"The tool {p.payload.get('tool_name')} no longer exists")
        if tool.id not in draft.get("tool_ids", []):
            draft["tool_ids"] = [*draft.get("tool_ids", []), tool.id]
    elif p.kind == "skill":
        tool_payload = p.payload.get("tool")
        if tool_payload:
            existing = await s.scalar(select(Tool).where(Tool.tenant_id == p.tenant_id, Tool.name == tool_payload["name"]))
            tool = existing or Tool(tenant_id=p.tenant_id, **ToolDef.model_validate(tool_payload).model_dump())
            if not existing:
                s.add(tool)
                await s.flush()
            if tool.id not in draft.get("tool_ids", []):
                draft["tool_ids"] = [*draft.get("tool_ids", []), tool.id]
        skill = Skill(tenant_id=p.tenant_id, **SkillDef.model_validate(p.payload["skill"]).model_dump())
        s.add(skill)
        await s.flush()
        draft["skill_ids"] = [*draft.get("skill_ids", []), skill.id]
    elif p.kind == "policy_rule":
        draft.setdefault("policy", {}).setdefault("rules", []).append(p.payload.get("rule", ""))
    agent.draft_config = draft
    await _add_derived_scenarios(s, p)  # SL-09
    version = await publish(s, agent, change_note=f"Fix: {p.title}", source_proposal_id=p.id)
    p.status, p.decided_by, p.decision_note, p.decided_at, p.resulting_version_id = "approved", decided_by, note, utcnow(), version.id
    cluster = await s.get(Cluster, p.cluster_id)
    if cluster:
        cluster.status = "fixed"
    await s.commit()
    bus.publish(p.tenant_id, "insights", "proposal.approved", {"id": p.id, "version_id": version.id, "version": version.version})
    bus.publish(p.tenant_id, "insights", "proposal.updated", proposal_summary(p))
    return version


async def _add_derived_scenarios(s: AsyncSession, p: FixProposal) -> None:
    taken = set((await s.scalars(select(EvalScenario.name).where(EvalScenario.agent_id == p.agent_id))).all())
    for sc in p.payload.get("scenarios") or []:
        name, n = sc["name"], 2
        while name in taken:
            name, n = f"{sc['name']} #{n}", n + 1
        taken.add(name)
        fields = {k: sc[k] for k in ("caller_goal", "caller_profile", "persona", "expected", "required_tools", "forbidden_tools",
                                     "expected_results", "memory") if k in sc}
        s.add(EvalScenario(tenant_id=p.tenant_id, agent_id=p.agent_id, name=name, enabled=True, **fields))


async def reject(s: AsyncSession, p: FixProposal, decided_by: str, note: str) -> FixProposal:
    if p.status in ("approved", "rejected", "evaluating"):
        raise ApiError(409, "invalid_state", f"Proposal is {p.status}")
    if not (note or "").strip():
        raise ApiError(422, "note_required", "A note is required to reject a proposal")
    p.status, p.decided_by, p.decision_note, p.decided_at = "rejected", decided_by, note, utcnow()
    if p.draft_doc_id:
        doc = await s.get(KnowledgeDoc, p.draft_doc_id)
        if doc:
            doc.status = "archived"
    cluster = await s.get(Cluster, p.cluster_id)
    if cluster and cluster.status == "fix_proposed":
        cluster.status = "open"
    if cluster:  # SL-05: the next nights do not draft the same fix again
        from datetime import timedelta

        from voiceai.schemas import LearningConfig

        agent = await s.get(Agent, p.agent_id)
        days = LearningConfig.model_validate((agent.draft_config or {}).get("learning") or {}).snooze_days if agent else 7
        cluster.snoozed_until = utcnow() + timedelta(days=days)
    await s.commit()
    bus.publish(p.tenant_id, "insights", "proposal.updated", proposal_summary(p))
    return p
