"""Fleet learning and evaluation.

Covers: FL-01, FL-02, FL-03, FL-04, FL-05, FL-06, FL-07, FL-08, EV-01, EV-02, EV-03, EV-04, EV-05, EV-06
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from voiceai import jobs
from voiceai.db import sessionmaker
from voiceai.events import bus
from voiceai.learning.analyze import save_analysis
from voiceai.learning.evaluate import passed
from voiceai.llm.gateway import FakeReply
from voiceai.models import Agent, AgentVersion, Call, CallAnalysis, CallEvent, Cluster, EvalResult, Job, KnowledgeDoc
from voiceai.schemas import AnalysisOut, JudgeOut

H = {"X-Tenant-Id": "evergreen-members"}
ARTICLE = {
    "kind": "knowledge_article", "title": "Adding a newborn to your coverage", "rationale": "Specialists consistently explained the 60-day rule.",
    "article": {"title": "Adding a newborn to your coverage",
                "content_markdown": "# Adding a newborn\nAdd your baby within 60 days of birth.\n## How\nMember portal > Coverage > Life events > Add a dependent.\n## Documents\nBirth certificate or hospital birth record within 30 days."},
}


def responder(judge_fail_case: str | None = None, simulator_line: str | None = None):  # noqa: ANN201
    def r(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:
        prompt = messages[-1]["content"] if messages else ""
        if role == "realtime":
            return FakeReply(text="Okay, I can help with that.")
        if role == "simulator":
            if simulator_line:
                return simulator_line
            return "[HANGUP]" if "Agent: Okay" in prompt else "Hi, I have a question."
        if role == "judge":
            fail = judge_fail_case and judge_fail_case in prompt
            outcome = "escalated" if "Expected outcome: escalated" in prompt else "resolved"
            return {"outcome": outcome, "goal_met": not fail, "grounded": True, "policy_violations": [], "notes": "graded"}
        if role == "analysis":
            return {"outcome": "resolved", "intent": "claim_status", "root_cause": "none", "gap_summary": "", "caller_goal": "Check a claim.",
                    "resolution_summary": "Explained claim.", "sentiment_start": "neutral", "sentiment_end": "positive"}
        if role == "drafting":
            if "These are short descriptions" in prompt:
                return {"name": "Address change after moving", "description": "Callers need to update their mailing address."}
            return ARTICLE
        raise AssertionError(role)

    return r


async def _cluster(client, name: str) -> dict:  # noqa: ANN001
    items = (await client.get("/api/insights/clusters", headers=H)).json()["items"]
    return next(c for c in items if c["name"] == name)


async def test_analyze_call_job(client, seeded, fake_llm):
    """Covers: FL-01"""
    fake_llm(responder())
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["evergreen-members"]["agent_id"], "channel": "text"})
    call_id = r.json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "claim status?"})
    await client.post(f"/api/calls/{call_id}/end", headers=H)
    await jobs.drain()
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(CallAnalysis).where(CallAnalysis.call_id == call_id)) == 1
        assert (await s.get(Call, call_id)).outcome == "resolved"


async def test_clustering_join_and_new(client, seeded, fake_llm):
    """Covers: FL-02, FL-03"""
    fake_llm(responder())
    agent_id = seeded["evergreen-members"]["agent_id"]
    async with sessionmaker()() as s:
        newborn = await s.scalar(select(Cluster).where(Cluster.name == "Adding a newborn to coverage"))
        before = newborn.escalation_count
        for gap in ("How to add a newborn to an existing plan", "Updating my mailing address after a move"):
            call = Call(tenant_id="evergreen-members", agent_id=agent_id, agent_version_id=seeded["evergreen-members"]["version_id"], channel="text")
            s.add(call)
            await s.flush()
            a = await save_analysis(s, call, AnalysisOut(outcome="escalated", intent="x", root_cause="missing_knowledge", gap_summary=gap), "llm")
            if "newborn" in gap:
                assert a.cluster_id == newborn.id
            else:
                created = await s.get(Cluster, a.cluster_id)
                assert created.name == "Address change after moving"
        await s.commit()
        assert (await s.get(Cluster, newborn.id)).escalation_count == before + 1


async def test_policy_cluster_not_fixable(client, seeded):
    """Covers: FL-04"""
    appeals = await _cluster(client, "Claim denial appeals")
    assert appeals["fixable"] is False and appeals["label"] == "correct_escalation"
    newborn = await _cluster(client, "Adding a newborn to coverage")
    assert newborn["ready_for_fix"] is True


async def _draft(client, fake_llm, judge_fail_case=None) -> str:  # noqa: ANN001
    fake_llm(responder(judge_fail_case))
    newborn = await _cluster(client, "Adding a newborn to coverage")
    assert (await client.post(f"/api/insights/clusters/{newborn['id']}/draft-fix", headers=H)).status_code == 200
    await jobs.drain()
    detail = (await client.get(f"/api/insights/clusters/{newborn['id']}", headers=H)).json()
    return detail["proposals"][0]["id"]


async def test_draft_fix_creates_draft_article(client, seeded, fake_llm):
    """Covers: FL-05"""
    pid = await _draft(client, fake_llm)
    p = (await client.get(f"/api/proposals/{pid}", headers=H)).json()
    assert p["kind"] == "knowledge_article" and p["draft_doc"]["status"] == "draft"


async def test_eval_then_approve(client, seeded, fake_llm):
    """Covers: EV-01, EV-02, EV-03, EV-06, FL-07, API-04"""
    pid = await _draft(client, fake_llm)
    sub = bus.subscribe("evergreen-members", {"insights"})
    agent_id = seeded["evergreen-members"]["agent_id"]
    async with sessionmaker()() as s:
        versions_before = await s.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent_id))
    assert (await client.post(f"/api/proposals/{pid}/evaluate", headers=H)).status_code == 200
    await jobs.drain()
    p = (await client.get(f"/api/proposals/{pid}", headers=H)).json()
    run = p["eval_run"]
    assert run["status"] == "done", run
    cluster_cases = run["summary"]["cluster_cases"]
    assert sum(1 for r in run["results"] if r["case_type"] == "cluster") == 2 * cluster_cases
    assert sum(1 for r in run["results"] if r["case_type"] == "regression") == 6
    progress = []
    while not sub.queue.empty():
        ev = sub.queue.get_nowait()
        if ev["type"] == "eval.progress":
            progress.append(ev)
    bus.unsubscribe(sub)
    assert len(progress) == 2 * cluster_cases + 6
    async with sessionmaker()() as s:  # EV-02: nothing changed before approval
        assert await s.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent_id)) == versions_before
        assert (await s.get(KnowledgeDoc, p["draft_doc_id"])).status == "draft"
    calls = (await client.get("/api/calls", headers=H)).json()["items"]
    assert all(c["channel"] != "simulation" for c in calls)  # EV-03
    assert (await client.get("/api/dashboard/summary", headers=H)).json()["totals"]["calls"] == 123
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Reviewer"})
    assert r.status_code == 200, r.text
    async with sessionmaker()() as s:
        agent = await s.get(Agent, agent_id)
        version = await s.get(AgentVersion, agent.published_version_id)
        assert p["draft_doc_id"] in version.config["knowledge_doc_ids"] and version.source_proposal_id == pid
        assert (await s.get(KnowledgeDoc, p["draft_doc_id"])).status == "active"
        assert (await s.scalar(select(Cluster).where(Cluster.name == "Adding a newborn to coverage"))).status == "fixed"


async def test_regression_failure_blocks_approval(client, seeded, fake_llm):
    """Covers: FL-06"""
    pid = await _draft(client, fake_llm, judge_fail_case="lost your insurance card")
    await client.post(f"/api/proposals/{pid}/evaluate", headers=H)
    await jobs.drain()
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Reviewer"})
    assert r.status_code == 409 and "regression" in r.json()["detail"]


async def test_simulation_turn_cap(client, seeded, fake_llm):
    """Covers: EV-04"""
    pid = await _draft(client, fake_llm)
    fake_llm(responder(simulator_line="Can you tell me more?"))
    await client.post(f"/api/proposals/{pid}/evaluate", headers=H)
    await jobs.drain()
    async with sessionmaker()() as s:
        result = await s.scalar(select(EvalResult).where(EvalResult.call_id.is_not(None)).limit(1))
        users = await s.scalar(select(func.count()).select_from(CallEvent).where(CallEvent.call_id == result.call_id, CallEvent.kind == "user"))
        assert users == 8


def test_expected_escalation_passes():
    """Covers: EV-05"""
    assert passed("escalated", JudgeOut(outcome="escalated", goal_met=True))
    assert not passed("escalated", JudgeOut(outcome="escalated", policy_violations=["gave medical advice"]))
    assert not passed("resolved", JudgeOut(outcome="resolved", goal_met=True, grounded=False))


async def test_reanalysis_after_resolution(client, seeded, fake_llm):
    """Covers: FL-08"""
    fake_llm(lambda role, m, t: FakeReply(tool_calls=[("escalate_to_human", {"reason_category": "caller_requested", "reason_detail": "person"})])
             if role == "realtime" else responder()(role, m, t))
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["evergreen-members"]["agent_id"], "channel": "text"})
    call_id = r.json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "a person please"})
    await client.post(f"/api/calls/{call_id}/end", headers=H)
    esc = (await client.get(f"/api/calls/{call_id}", headers=H)).json()["escalation"]
    await client.post(f"/api/escalations/{esc['id']}/accept", headers=H, json={"assignee": "Dana"})
    await client.post(f"/api/escalations/{esc['id']}/resolve", headers=H, json={"disposition": "resolved_by_human", "resolution_note": "Helped the caller directly."})
    async with sessionmaker()() as s:
        keys = set((await s.scalars(select(Job.dedupe_key).where(Job.kind == "analyze_call"))).all())
        assert f"analyze_call:{call_id}" in keys and f"analyze_call:{call_id}:2" in keys
