"""Evaluation: per-version score summary, scored calls, and reviews of judge verdicts.

Spec: /api/rest-api.md (Evaluation), /architecture/call-scoring.md
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import get_session, utcnow
from voiceai.errors import ApiError
from voiceai.learning import score_report
from voiceai.models import Agent, CallScorecard, CheckReview
from voiceai.tenancy import current_tenant

router = APIRouter(prefix="/api")


class ReviewBody(BaseModel):
    verdict: Literal["pass", "fail", "n/a"]
    note: str | None = Field(default=None, max_length=300)
    reviewer: str = Field(min_length=1, max_length=120)


def _days(days: int) -> int:
    if days not in (7, 28, 90):
        raise ApiError(422, "invalid_days", "days must be 7, 28 or 90")
    return days


async def _agent(s: AsyncSession, tenant_id: str, agent_id: str) -> Agent:
    agent = await s.scalar(select(Agent).where(Agent.id == agent_id, Agent.tenant_id == tenant_id))
    if agent is None:
        raise ApiError(404, "agent_not_found", "Agent not found")
    return agent


@router.get("/evaluation/summary")
async def summary(
    agent_id: str, days: int = 28, include_seed: bool = True,
    tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session),
) -> dict:
    await _agent(s, tenant_id, agent_id)
    return await score_report.summary(s, tenant_id, agent_id, _days(days), include_seed)


@router.get("/evaluation/scorecards")
async def scorecards(
    agent_id: str, version_id: str | None = None, check: str | None = None,
    verdict: Literal["pass", "fail", "n/a", "unknown", "not_judged"] | None = None, hard_fail: bool | None = None,
    reviewed: bool | None = None, days: int = 28, include_seed: bool = True,
    tenant_id: str = Depends(current_tenant), s: AsyncSession = Depends(get_session),
) -> dict:
    await _agent(s, tenant_id, agent_id)
    items = await score_report.list_scorecards(s, tenant_id, agent_id, days=_days(days), include_seed=include_seed, version_id=version_id,
                                               check=check, verdict=verdict, hard_fail=hard_fail, reviewed=reviewed)
    return {"items": items}


@router.put("/scorecards/{scorecard_id}/reviews/{check_key}")
async def review(scorecard_id: str, check_key: str, body: ReviewBody, tenant_id: str = Depends(current_tenant),
                 s: AsyncSession = Depends(get_session)) -> dict:
    """API-08: one review per scorecard and check, replaced on change; the judge's verdict is never touched."""
    card = await s.scalar(select(CallScorecard).where(CallScorecard.id == scorecard_id, CallScorecard.tenant_id == tenant_id))
    if card is None:
        raise ApiError(404, "scorecard_not_found", "Scorecard not found")
    check = next((c for c in card.checks if c["key"] == check_key), None)
    if check is None:
        raise ApiError(404, "check_not_found", f"No check '{check_key}' on this scorecard")
    if check["method"] == "code":
        raise ApiError(409, "code_check", "Checks decided in code are not reviewed")
    row = await s.scalar(select(CheckReview).where(CheckReview.scorecard_id == card.id, CheckReview.check_key == check_key))
    if row is None:
        row = CheckReview(tenant_id=tenant_id, scorecard_id=card.id, call_id=card.call_id, agent_id=card.agent_id, check_key=check_key,
                          judge_verdict=check["verdict"], verdict=body.verdict, reviewer=body.reviewer.strip())
        s.add(row)
    row.judge_verdict, row.verdict, row.reviewer = check["verdict"], body.verdict, body.reviewer.strip()
    row.note = (body.note or "").strip() or None
    row.updated_at = utcnow()
    await s.commit()
    return score_report.review_out(row)
