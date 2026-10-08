"""Insights: clusters, fix proposals, evaluation, approval.

Spec: /api/rest-api.md (Insights), /architecture/fleet-learning.md, /architecture/evaluation.md
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.core.db import get_session, utcnow
from voiceai.core.errors import ApiError
from voiceai.modules.learning import evaluate, propose
from voiceai.modules.learning.service import cluster_card, cluster_cards, readiness
from voiceai.core.tables import Call, CallAnalysis, CallFeedback, Cluster, EvalResult, EvalRun, FixProposal, KnowledgeDoc
from voiceai.core.tenancy import current_tenant

router = APIRouter(prefix="/api")

@router.get("/insights/clusters")
async def clusters(agent_id: str | None = None, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    return {"items": await cluster_cards(s, tenant_id, agent_id)}


async def _cluster(s: AsyncSession, tenant_id: str, cluster_id: str) -> Cluster:
    c = await s.scalar(select(Cluster).where(Cluster.id == cluster_id, Cluster.tenant_id == tenant_id))
    if not c:
        raise ApiError(404, "cluster_not_found", "Cluster not found")
    return c


@router.get("/insights/clusters/{cluster_id}")
async def cluster_detail(cluster_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    c = await _cluster(s, tenant_id, cluster_id)
    card = await cluster_card(s, tenant_id, c)
    evidence = await propose.cluster_evidence(s, c.id, limit=50)
    proposals = (await s.scalars(select(FixProposal).where(FixProposal.cluster_id == c.id).order_by(FixProposal.created_at.desc()))).all()
    return {**card, "calls": evidence, "proposals": [propose.proposal_summary(p) for p in proposals]}


@router.post("/insights/clusters/{cluster_id}/draft-fix")
async def draft_fix(cluster_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    c = await _cluster(s, tenant_id, cluster_id)
    if not await readiness(s, tenant_id, c):
        raise ApiError(409, "cluster_not_ready", "Cluster is not fixable, below threshold, or already has a proposal")
    from voiceai.core import jobs

    job = await jobs.enqueue(s, tenant_id, "draft_fix", {"cluster_id": cluster_id})
    await s.commit()
    return {"job_id": job.id}


@router.post("/insights/clusters/{cluster_id}/ignore")
async def ignore(cluster_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    c = await _cluster(s, tenant_id, cluster_id)
    c.status = "ignored"
    await s.commit()
    return await cluster_card(s, tenant_id, c)


class ProposalUpdate(BaseModel):
    title: str | None = None
    payload: dict[str, Any] | None = None


class Decision(BaseModel):
    decided_by: str = "Reviewer"
    note: str | None = None
    force: bool = False


async def _proposal_out(s: AsyncSession, p: FixProposal) -> dict[str, Any]:
    doc = await s.get(KnowledgeDoc, p.draft_doc_id) if p.draft_doc_id else None
    run = await s.get(EvalRun, p.latest_eval_run_id) if p.latest_eval_run_id else None
    results = []
    if run:
        results = [{"case_key": r.case_key, "case_type": r.case_type, "arm": r.arm, "passed": r.passed, "expected": r.expected,
                    "judge": r.judge, "call_id": r.call_id}
                   for r in (await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == run.id).order_by(EvalResult.created_at))).all()]
    return {
        **propose.proposal_summary(p),
        "draft_doc": {"id": doc.id, "title": doc.title, "content": doc.content, "status": doc.status} if doc else None,
        "eval_run": {"id": run.id, "status": run.status, "summary": run.summary, "error": run.error, "results": results} if run else None,
    }


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    return await _proposal_out(s, await propose.get_proposal(s, tenant_id, proposal_id))


@router.put("/proposals/{proposal_id}")
async def update_proposal(proposal_id: str, body: ProposalUpdate, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    p = await propose.update_proposal(s, await propose.get_proposal(s, tenant_id, proposal_id), body.title, body.payload)
    return await _proposal_out(s, p)


@router.post("/proposals/{proposal_id}/evaluate")
async def evaluate_proposal(proposal_id: str, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    run = await evaluate.start_eval(s, tenant_id, await propose.get_proposal(s, tenant_id, proposal_id))
    return {"eval_run_id": run.id}


@router.post("/proposals/{proposal_id}/approve")
async def approve(proposal_id: str, body: Decision, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    p = await propose.get_proposal(s, tenant_id, proposal_id)
    version = await propose.approve(s, p, body.decided_by, body.note, body.force)
    return {"proposal": await _proposal_out(s, p), "version": {"id": version.id, "version": version.version}}


@router.post("/proposals/{proposal_id}/reject")
async def reject(proposal_id: str, body: Decision, tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session)) -> dict:
    p = await propose.reject(s, await propose.get_proposal(s, tenant_id, proposal_id), body.decided_by, body.note or "")
    return await _proposal_out(s, p)
