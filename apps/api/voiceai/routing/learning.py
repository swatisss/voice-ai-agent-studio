"""Learning from misroutes: the nightly `routing_update` proposal, its routing gate and its approval; the routing summary.

Spec: /architecture/self-learning.md (Routing proposals, SL-13), /architecture/agent-transfer.md (Misroutes),
/api/rest-api.md (GET /api/routing/summary)
"""
from __future__ import annotations

import logging
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.events import bus
from voiceai.knowledge.embeddings import embed
from voiceai.models import Agent, Call, CallEvent, CallScorecard, Conversation, EvalResult, EvalRun, FixProposal, RoutingCase, UseCase
from voiceai.routing import catalog

log = logging.getLogger("voiceai.routing.learning")

MIN_MISROUTES = 3
MAX_UTTERANCES = 5
_DIGITS = re.compile(r"\d{3,}")


def clean(text: str) -> str:
    """Caller words without identifiers (long digit runs), for use-case examples."""
    return " ".join(_DIGITS.sub("…", text).split())[:200]


async def misroutes(s: AsyncSession, tenant_id: str, since: datetime) -> dict[str, list[str]]:
    """Target agent → routed utterances of segments that failed `routing.early_transfer` or a calibrated `routing.in_scope`."""
    from voiceai.learning.nightly import calibrated_keys

    rows = (await s.execute(select(Call, CallScorecard).join(CallScorecard, CallScorecard.call_id == Call.id)
                            .where(Call.tenant_id == tenant_id, Call.conversation_id.is_not(None), Call.started_at >= since,
                                   Call.is_seed.is_(False)))).all()
    out: dict[str, list[str]] = defaultdict(list)
    calibrated: dict[str, set[str]] = {}
    for call, card in rows:
        if call.routed_by in (None, "explicit"):
            continue
        verdicts = {c["key"]: c.get("verdict") for c in card.checks or []}
        if call.agent_id not in calibrated:
            calibrated[call.agent_id] = await calibrated_keys(s, call.agent_id)
        missed = verdicts.get("routing.early_transfer") == "fail" or (
            verdicts.get("routing.in_scope") == "fail" and "routing.in_scope" in calibrated[call.agent_id])
        if not missed:
            continue
        final = await s.scalar(select(Call).where(Call.conversation_id == call.conversation_id,
                                                  or_(Call.end_reason.is_(None), Call.end_reason != "transfer"))
                               .order_by(Call.segment.desc()))
        if final is None or final.agent_id == call.agent_id:
            continue
        nxt = await s.scalar(select(Call).where(Call.conversation_id == call.conversation_id, Call.segment == (call.segment or 0) + 1))
        if nxt is None:
            continue
        # the request the next agent handled: the first caller line of the next segment
        first = await s.scalar(select(CallEvent).where(CallEvent.call_id == nxt.id, CallEvent.kind == "user").order_by(CallEvent.seq))
        if first and first.text:
            out[final.agent_id].append(clean(first.text))
    return out


async def _stage_a_top(entries: list[tuple[str, np.ndarray]], text: str) -> str | None:
    if not entries:
        return None
    q = (await embed([text], "query"))[0]
    best = max(entries, key=lambda e: float(e[1] @ q))
    return best[0]


async def gate(s: AsyncSession, tenant_id: str, agent_id: str, scope: str, add: list[str]) -> dict[str, Any]:
    """The routing gate: misrouted requests reach the right agent with the change, and suite accuracy does not drop
    (Stage A, catalog in memory)."""
    agents, mat, _ = await catalog._tenant_matrix(s, tenant_id, scope)
    base = [(a, mat[i]) for i, a in enumerate(agents)]
    extra = [(agent_id, v) for v in await embed(add)] if add else []
    cases = (await s.scalars(select(RoutingCase).where(RoutingCase.tenant_id == tenant_id, RoutingCase.scope == scope, RoutingCase.enabled.is_(True)))).all()
    before = after = 0
    for c in cases:
        before += int(await _stage_a_top(base, c.utterance) == c.expected_agent_id)
        after += int(await _stage_a_top(base + extra, c.utterance) == c.expected_agent_id)
    fixed = [u for u in add if await _stage_a_top(base + extra, u) == agent_id]
    reasons = []
    if len(fixed) < len(add):
        reasons.append(f"{len(add) - len(fixed)} of {len(add)} misrouted requests would still go elsewhere")
    if after < before:
        reasons.append(f"the routing suite would drop from {before} to {after} of {len(cases)}")
    return {"passed": not reasons, "reasons": reasons, "suite_before": before, "suite_after": after, "cases": len(cases),
            "misrouted_fixed": len(fixed), "misrouted": len(add)}


async def draft_proposals(tenant_id: str, since: datetime) -> dict[str, Any]:
    """Once per nightly run: at most one `routing_update` per agent with ≥ 3 misrouted requests (SL-13). Proposes only."""
    report: dict[str, Any] = {"misrouted": 0, "drafted": 0, "passed": 0}
    async with sessionmaker()() as s:
        found = await misroutes(s, tenant_id, since)
        report["misrouted"] = sum(len(v) for v in found.values())
        for agent_id, utterances in found.items():
            if len(utterances) < MIN_MISROUTES:
                continue
            open_one = await s.scalar(select(FixProposal.id).where(FixProposal.agent_id == agent_id, FixProposal.kind == "routing_update",
                                                                  FixProposal.status.in_(("draft", "evaluating", "ready"))))
            if open_one:
                continue
            profile = await s.scalar(select(catalog.CapabilityProfile).where(catalog.CapabilityProfile.agent_id == agent_id))
            cases = (await s.scalars(select(UseCase).where(UseCase.agent_id == agent_id, UseCase.tenant_id == tenant_id).order_by(UseCase.sort))).all()
            agent = await s.get(Agent, agent_id)
            if profile is None or not cases or agent is None:
                continue
            add = list(dict.fromkeys(utterances))[:MAX_UTTERANCES]
            target = cases[0]
            proposal = FixProposal(tenant_id=tenant_id, agent_id=agent_id, cluster_id="", kind="routing_update", origin="nightly",
                                   title=f"Route more requests like these to {agent.name}",
                                   rationale=f"{len(utterances)} callers reached another agent first and were handed on to {agent.name}.",
                                   payload={"use_case_id": target.id, "use_case_title": target.title, "add_utterances": add},
                                   status="evaluating")
            s.add(proposal)
            await s.flush()
            result = await gate(s, tenant_id, agent_id, profile.scope, add)
            run = EvalRun(tenant_id=tenant_id, agent_id=agent_id, kind="routing", trigger="proposal", proposal_id=proposal.id,
                          status="done", repeats=1, summary={"gate": result}, finished_at=utcnow())
            s.add(run)
            await s.flush()
            s.add(EvalResult(tenant_id=tenant_id, eval_run_id=run.id, case_key="routing_gate", case_type="routing", arm="candidate",
                             expected="routing", passed=result["passed"], failures=result["reasons"], judge=result))
            proposal.status, proposal.latest_eval_run_id = "ready", run.id
            report["drafted"] += 1
            report["passed"] += int(result["passed"])
        await s.commit()
    return report


async def approve(s: AsyncSession, p: FixProposal) -> None:
    """A human approved: the use case gains the examples (or the summary); the agent is re-indexed; no version."""
    use_case = await s.scalar(select(UseCase).where(UseCase.id == p.payload.get("use_case_id"), UseCase.tenant_id == p.tenant_id))
    if use_case is None:
        raise ApiError(409, "use_case_not_found", "The use case of this proposal no longer exists")
    if p.payload.get("add_utterances"):
        merged = list(dict.fromkeys([*(use_case.sample_utterances or []), *p.payload["add_utterances"]]))[:20]
        use_case.sample_utterances = merged
    if p.payload.get("summary"):
        use_case.summary = str(p.payload["summary"])[:600]
    await catalog.enqueue_index(s, p.tenant_id, p.agent_id)


async def summary(s: AsyncSession, tenant_id: str, days: int) -> dict[str, Any]:
    """GET /api/routing/summary: decisions, methods, Stage B and fallbacks, clarifications, misroutes, transfers, latency."""
    since = utcnow() - timedelta(days=days)
    convs = (await s.scalars(select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.started_at >= since))).all()
    decisions = [d for c in convs for d in (c.routing or []) if d.get("method") not in (None, "explicit")]
    methods = Counter(d["method"] for d in decisions)
    ms = sorted(int(d.get("stage_a_ms") or 0) + int((d.get("stage_b") or {}).get("ms") or 0) for d in decisions)
    segments = (await s.execute(select(Call, CallScorecard).outerjoin(CallScorecard, CallScorecard.call_id == Call.id)
                                .where(Call.tenant_id == tenant_id, Call.conversation_id.is_not(None), Call.started_at >= since))).all()
    names = {a.id: a.name for a in (await s.scalars(select(Agent).where(Agent.tenant_id == tenant_id))).all()}
    by_agent: dict[str, dict[str, Any]] = {}
    routed = misrouted = 0
    for call, card in segments:
        if call.routed_by in (None, "explicit"):
            continue
        routed += 1
        row = by_agent.setdefault(call.agent_id, {"agent_id": call.agent_id, "agent_name": names.get(call.agent_id), "routed_to": 0,
                                                  "early_transfers": 0, "in_scope_failures": 0})
        row["routed_to"] += 1
        verdicts = {c["key"]: c.get("verdict") for c in (card.checks if card else []) or []}
        early, out_of_scope = verdicts.get("routing.early_transfer") == "fail", verdicts.get("routing.in_scope") == "fail"
        row["early_transfers"] += int(early)
        row["in_scope_failures"] += int(out_of_scope)
        misrouted += int(early or out_of_scope)
    n = len(decisions)
    rate = (lambda k: round(k / n, 4) if n else None)
    return {
        "decisions": n, "by_method": dict(methods),
        "stage_b_rate": rate(sum(1 for d in decisions if d.get("stage_b"))),
        "fallback_rate": rate(sum(1 for d in decisions if any(f.get("error") not in ("not_configured", "phi_mode") for f in d.get("fallbacks") or []))),
        "clarification_rate": rate(methods.get("clarify", 0)),
        "misroute_rate": round(misrouted / routed, 4) if routed else None,
        "transfers_per_conversation": round(statistics.mean(c.transfer_count for c in convs), 3) if convs else None,
        "decision_ms": {"p50": int(statistics.median(ms)) if ms else None, "p95": ms[max(0, int(round(0.95 * len(ms))) - 1)] if ms else None},
        "by_agent": sorted(by_agent.values(), key=lambda r: -r["routed_to"]),
    }


def publish_updated(p: FixProposal) -> None:
    from voiceai.learning.propose import proposal_summary

    bus.publish(p.tenant_id, "insights", "proposal.updated", proposal_summary(p))
