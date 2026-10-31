"""Nightly self-learning: schedule, signals, re-analysis, drafting under a cap, snooze, new kinds, held-out, derived
scenarios, the run never changing an agent, the report.

Covers: SL-01, SL-02, SL-03, SL-04, SL-05, SL-06, SL-07, SL-08, SL-09, SL-11, SL-12, DM-09
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from voiceai import jobs
from voiceai.db import sessionmaker, utcnow
from voiceai.events import bus
from voiceai.learning import gate, nightly, scoring
from voiceai.llm.gateway import FakeReply
from voiceai.models import (
    Agent, AgentVersion, Call, CallAnalysis, CallEvent, CallScorecard, CheckReview, Cluster, EvalRun, EvalScenario, FixProposal,
    KnowledgeDoc, LearningRun, Tool,
)

H = {"X-Tenant-Id": "evergreen-care"}
ARTICLE = {"kind": "knowledge_article", "title": "Adding a newborn to your coverage", "rationale": "Specialists explained the 60-day rule.",
           "article": {"title": "Adding a newborn to your coverage", "content_markdown": "# Adding a newborn\nAdd your baby within 60 days of birth."}}


def fake(*, search: str | None = None, seen: dict[str, list[str]] | None = None):  # noqa: ANN201
    seen = seen if seen is not None else {}

    def r(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:  # noqa: ANN401
        prompt = messages[-1]["content"] if messages else ""
        seen.setdefault(role, []).append(prompt)
        if role == "realtime":
            if search and not any(m.get("role") == "tool" for m in messages):
                return FakeReply(tool_calls=[("search_knowledge", {"query": search})])
            return FakeReply(text="Okay, I can help with that.")
        if role == "simulator":
            return "[HANGUP]" if "Caller:" in prompt else "Hello, I have a question."
        if role == "analysis":
            return {"outcome": "resolved", "intent": "x", "root_cause": "none", "gap_summary": "", "caller_goal": "You want to know x.",
                    "resolution_summary": "", "sentiment_start": "neutral", "sentiment_end": "neutral"}
        if role == "judge":
            block = prompt.split("Checks:\n", 1)[1].split("\n\nReturn JSON", 1)[0] if "Checks:\n" in prompt else ""
            checks = {line.split(":", 1)[0]: {"verdict": "pass"} for line in block.splitlines() if line and line != "(none)"}
            return {"outcome": "resolved", "goal_met": True, "grounded": True, "policy_violations": [], "notes": "", "checks": checks}
        if role == "drafting":
            if "short descriptions" in prompt:
                return {"name": "Unanswered questions", "description": "Questions the knowledge base does not cover."}
            return ARTICLE
        raise AssertionError(role)

    return r


async def _learning(seeded, **settings: Any) -> None:  # noqa: ANN001
    """Set the published version's learning block and keep the test suite small."""
    async with sessionmaker()() as s:
        v = await s.get(AgentVersion, seeded["care"]["version_id"])
        v.config = {**v.config, "learning": {"nightly": True, "max_proposals_per_night": 3, "regression_repeats": 1, "snooze_days": 7, **settings}}
        for sc in (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == seeded["care"]["agent_id"]))).all():
            sc.enabled = False
        for other in (await s.scalars(select(Agent).where(Agent.tenant_id == "evergreen-care", Agent.id != seeded["care"]["agent_id"]))).all():
            ov = await s.get(AgentVersion, other.published_version_id)
            ov.config = {**ov.config, "learning": {"nightly": False}}
        await s.commit()


async def _run_now(client) -> dict:  # noqa: ANN001
    r = await client.post("/api/learning/run", headers=H)
    assert r.status_code == 200, r.text
    await jobs.drain()
    return (await client.get("/api/learning/runs", headers=H)).json()["items"][0]


async def test_schedule_and_run_now(client, seeded, fake_llm):
    """Covers: SL-01"""
    fake_llm(fake())
    started_late = datetime(2026, 11, 1, 2, 30, tzinfo=timezone.utc)  # a service started after 02:00 does not catch the night up
    assert await nightly.schedule_nightly(datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc), running_since=started_late) == 0
    assert await nightly.schedule_nightly(datetime(2026, 11, 1, 1, 30, tzinfo=timezone.utc)) == 0  # before 02:00 UTC
    assert await nightly.schedule_nightly(datetime(2026, 11, 1, 3, 0, tzinfo=timezone.utc)) == 2  # both tenants
    assert await nightly.schedule_nightly(datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)) == 0  # once a day
    r = await client.post("/api/learning/run", headers=H)
    assert r.status_code == 409 and r.json()["error"] == "run_in_progress"
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(LearningRun).where(LearningRun.trigger == "nightly")) == 2


async def test_signals_reanalyse_a_resolved_call(client, seeded, fake_llm):
    """Covers: SL-02, SL-12"""
    fake_llm(fake(search="quantum lattice gauge chromodynamics"))
    await _learning(seeded, max_proposals_per_night=0)
    call_id = (await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})).json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "Tell me about quantum physics cover"})
    await client.post(f"/api/calls/{call_id}/end", headers=H)
    await jobs.drain()
    async with sessionmaker()() as s:
        before = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
        assert before.root_cause == "none" and before.cluster_id is None
    sub = bus.subscribe("evergreen-care", {"insights"})
    run = await _run_now(client)
    async with sessionmaker()() as s:
        after = await s.scalar(select(CallAnalysis).where(CallAnalysis.call_id == call_id))
        assert after.signals and after.signals[0].startswith("Knowledge search found nothing")
        assert after.root_cause == "missing_knowledge" and after.gap_summary and after.cluster_id is not None
    agent = run["summary"]["agents"][seeded["care"]["agent_id"]]
    assert run["status"] == "done" and agent["reanalysed"] == 1 and agent["signals"]["no_answer"] == 1 and agent["drafted"] == 0
    got = []
    while not sub.queue.empty():
        got.append(sub.queue.get_nowait())
    finished = [e for e in got if e["type"] == "learning.run.finished"]
    assert len(finished) == 1 and finished[0]["data"]["learning_run_id"] == run["id"]


async def test_only_calibrated_judge_failures_count(client, seeded, fake_llm):
    """Covers: SL-03"""
    fake_llm(fake())
    call_id = (await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})).json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "hi"})
    await client.post(f"/api/calls/{call_id}/end", headers=H)
    await jobs.drain()
    async with sessionmaker()() as s:
        card = await s.scalar(select(CallScorecard).where(CallScorecard.call_id == call_id))
        card.checks = [{**c, "verdict": "fail"} if c["key"] == "knowledge.grounded" else c for c in card.checks]
        events = list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id))).all())
        assert nightly.signals_of(events, card, False, False, set()) == []
        for i in range(20):  # 20 reviews that agree with the judge, each on its own scored call
            other = Call(tenant_id="evergreen-care", agent_id=seeded["care"]["agent_id"], agent_version_id=seeded["care"]["version_id"],
                         channel="text", status="ended")
            s.add(other)
            await s.flush()
            sc = CallScorecard(tenant_id="evergreen-care", call_id=other.id, agent_id=seeded["care"]["agent_id"],
                               agent_version_id=seeded["care"]["version_id"], checks=[], measures={})
            s.add(sc)
            await s.flush()
            s.add(CheckReview(tenant_id="evergreen-care", scorecard_id=sc.id, call_id=other.id, agent_id=seeded["care"]["agent_id"],
                              check_key="knowledge.grounded", judge_verdict="fail", verdict="fail", reviewer="r"))
        await s.flush()
        calibrated = await nightly.calibrated_keys(s, seeded["care"]["agent_id"])
        assert "knowledge.grounded" in calibrated
        assert [k for k, _ in nightly.signals_of(events, card, False, False, calibrated)] == ["calibrated_judge_fail"]
        await s.rollback()


async def test_cap_picks_costliest_and_never_changes_the_agent(client, seeded, fake_llm):
    """Covers: SL-04, SL-11"""
    fake_llm(fake())
    await _learning(seeded, max_proposals_per_night=1)
    agent_id = seeded["care"]["agent_id"]
    async with sessionmaker()() as s:
        versions = await s.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent_id))
        draft = (await s.get(Agent, agent_id)).draft_config
    run = await _run_now(client)
    agent = run["summary"]["agents"][agent_id]
    assert agent["ready_clusters"] == 2 and agent["drafted"] == 1  # newborn (14 escalations) before prior auth (9)
    async with sessionmaker()() as s:
        proposals = (await s.scalars(select(FixProposal).where(FixProposal.agent_id == agent_id))).all()
        assert len(proposals) == 1 and proposals[0].origin == "nightly" and proposals[0].status == "ready"
        assert (await s.get(Cluster, proposals[0].cluster_id)).name == "Adding a newborn to coverage"
        assert await s.scalar(select(func.count()).select_from(AgentVersion).where(AgentVersion.agent_id == agent_id)) == versions
        assert (await s.get(Agent, agent_id)).draft_config == draft
        assert await s.scalar(select(func.count()).select_from(FixProposal).where(FixProposal.status == "approved")) == 0
    inbox = (await client.get("/api/insights/inbox", headers=H)).json()["items"]
    assert [p["id"] for p in inbox] == [proposals[0].id] and inbox[0]["eval_summary"]["gate"] is not None


async def test_rejected_cluster_is_snoozed(client, seeded, fake_llm):
    """Covers: SL-05"""
    fake_llm(fake())
    await _learning(seeded, max_proposals_per_night=1, snooze_days=7)
    first = await _run_now(client)
    pid = first["summary"]["agents"][seeded["care"]["agent_id"]]["proposals"][0]["id"]
    r = await client.post(f"/api/proposals/{pid}/reject", headers=H, json={"decided_by": "Dana", "note": "Wrong deadline"})
    assert r.status_code == 200
    async with sessionmaker()() as s:
        cluster = await s.get(Cluster, (await s.get(FixProposal, pid)).cluster_id)
        assert cluster.snoozed_until > utcnow() + timedelta(days=6)
        snoozed_id = cluster.id
    second = await _run_now(client)
    drafted = second["summary"]["agents"][seeded["care"]["agent_id"]]["proposals"]
    async with sessionmaker()() as s:
        for d in drafted:
            assert (await s.get(FixProposal, d["id"])).cluster_id != snoozed_id
        cluster = await s.get(Cluster, snoozed_id)
        cluster.snoozed_until = utcnow() - timedelta(minutes=1)
        await s.commit()
    clusters = (await client.get("/api/insights/clusters", headers=H)).json()["items"]
    assert next(c for c in clusters if c["id"] == snoozed_id)["ready_for_fix"] is True


async def _ready_proposal(seeded, kind: str, payload: dict, draft_doc_id: str | None = None) -> str:  # noqa: ANN001
    async with sessionmaker()() as s:
        cluster = await s.scalar(select(Cluster).where(Cluster.name == "Adding a newborn to coverage"))
        run = EvalRun(tenant_id="evergreen-care", agent_id=seeded["care"]["agent_id"], proposal_id="x",
                      baseline_version_id=seeded["care"]["version_id"], status="done", summary={"gate": {"passed": True, "reasons": []}})
        s.add(run)
        await s.flush()
        p = FixProposal(tenant_id="evergreen-care", agent_id=seeded["care"]["agent_id"], cluster_id=cluster.id, kind=kind, title="t",
                        payload=payload, draft_doc_id=draft_doc_id, status="ready", latest_eval_run_id=run.id)
        s.add(p)
        await s.commit()
        return p.id


async def test_knowledge_edit_replaces_the_article(client, seeded):
    """Covers: SL-06"""
    from voiceai.knowledge.ingest import create_doc

    async with sessionmaker()() as s:
        version = await s.get(AgentVersion, seeded["care"]["version_id"])
        old_id = version.config["knowledge_doc_ids"][0]
        new = await create_doc(s, "evergreen-care", "Revised", "# Revised\nThe new answer.", "proposal", "cluster:x", status="draft")
        await s.commit()
        new_id = new.id
    pid = await _ready_proposal(seeded, "knowledge_edit", {"doc_id": old_id, "article": {"title": "Revised", "content_markdown": "x"}}, new_id)
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    assert r.status_code == 200, r.text
    async with sessionmaker()() as s:
        v = await s.get(AgentVersion, r.json()["version"]["id"])
        assert new_id in v.config["knowledge_doc_ids"] and old_id not in v.config["knowledge_doc_ids"]
        assert (await s.get(KnowledgeDoc, old_id)).status == "archived" and (await s.get(KnowledgeDoc, new_id)).status == "active"


async def test_tool_attach(client, seeded):
    """Covers: SL-07"""
    async with sessionmaker()() as s:
        tools_before = await s.scalar(select(func.count()).select_from(Tool))
        owned = {t["name"] for t in (await s.get(AgentVersion, seeded["care"]["version_id"])).config["tools"]}
        spare = await s.scalar(select(Tool).where(Tool.tenant_id == "evergreen-care", Tool.name.not_in(owned)).limit(1))
    pid = await _ready_proposal(seeded, "tool_attach", {"tool_name": spare.name})
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    assert r.status_code == 200, r.text
    async with sessionmaker()() as s:
        v = await s.get(AgentVersion, r.json()["version"]["id"])
        assert spare.name in {t["name"] for t in v.config["tools"]}
        assert await s.scalar(select(func.count()).select_from(Tool)) == tools_before


async def test_held_out_and_derived(client, seeded, fake_llm):
    """Covers: SL-08, SL-09"""
    seen: dict[str, list[str]] = {}
    fake_llm(fake(seen=seen))
    await _learning(seeded, max_proposals_per_night=1)
    run = await _run_now(client)
    pid = run["summary"]["agents"][seeded["care"]["agent_id"]]["proposals"][0]["id"]
    async with sessionmaker()() as s:
        p = await s.get(FixProposal, pid)
        evidence = set(p.payload["evidence_call_ids"])
        cases = await gate.gather_cases(s, p, (await s.get(AgentVersion, seeded["care"]["version_id"])).config)
        eval_run = await s.get(EvalRun, p.latest_eval_run_id)
    held = [c for c in cases if c["type"] == "held_out"]
    assert held and len(held) <= gate.HELD_OUT
    assert not {c["scenario"]["source_call_id"] for c in held} & evidence  # never shown to the drafter
    assert len(seen["drafting"]) >= 1
    summary = eval_run.summary
    assert summary["held_out_cases"] == len(held)
    # every case ran on both arms
    async with sessionmaker()() as s:
        from voiceai.models import EvalResult

        rows = (await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == eval_run.id))).all()
    by_case = {}
    for r in rows:
        by_case.setdefault(r.case_key, set()).add(r.arm)
    assert all(arms == {"baseline", "candidate"} for arms in by_case.values())
    assert any(k.startswith("held-out") for k in by_case)
    assert len(evidence) == 10  # the drafter saw ten member calls; the cluster has 14
    # the fake judge passes everything, so the derived scenarios pass on the baseline and are dropped (SL-09)
    assert summary["derived_dropped"] == 2 and summary["derived_kept"] == 0 and p.payload["scenarios"] == []


async def test_kept_derived_scenarios_join_the_suite(client, seeded):
    """Covers: SL-09"""
    scenario = {"name": "From newborn (1)", "caller_goal": "You want to add your newborn.", "caller_profile": {}, "persona": "calm",
                "expected": "resolved", "required_tools": [], "forbidden_tools": [], "expected_results": [], "memory": []}
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the portal.", "scenarios": [scenario]})
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    assert r.status_code == 200, r.text
    async with sessionmaker()() as s:
        row = await s.scalar(select(EvalScenario).where(EvalScenario.name == "From newborn (1)"))
        assert row is not None and row.enabled and row.agent_id == seeded["care"]["agent_id"]


async def test_learning_config_validation(client, seeded):
    """Covers: DM-09"""
    agent_id = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    for bad in ({"max_proposals_per_night": 11}, {"regression_repeats": 0}):
        r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**draft, "learning": bad}})
        assert r.status_code == 422, bad
    draft.pop("learning", None)
    saved = (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})).json()["draft_config"]
    assert saved["learning"] == {"nightly": True, "max_proposals_per_night": 3, "regression_repeats": 3, "snooze_days": 7}
    assert scoring  # imported for the scorer the run relies on
