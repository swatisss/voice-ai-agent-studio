"""Approval publishes what was gated; held-out reserve, case repeats, lift as a pass rate, latency budget.

Covers: SL-17, SL-18, SL-19, SL-20
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select

from tests.test_self_learning import H, _learning, _ready_proposal, fake
from voiceai import jobs
from voiceai.db import sessionmaker
from voiceai.knowledge.ingest import create_doc
from voiceai.learning import gate, propose
from voiceai.models import Agent, AgentVersion, CallAnalysis, Cluster, EvalResult, EvalRun, FixProposal
from voiceai.learning.analyze import refresh_stats


async def test_approval_publishes_the_gated_config_and_keeps_the_draft(client, seeded):
    """Covers: SL-17"""
    agent_id = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    draft["policy"]["rules"] = [*draft["policy"].get("rules", []), "Say the weather."]  # an unpublished builder edit
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})).status_code == 200
    async with sessionmaker()() as s:
        doc = await create_doc(s, "evergreen-care", "Newborns", "# Newborns\nAdd your baby within 60 days.", "proposal", "cluster:x", status="draft")
        await s.commit()
        doc_id = doc.id
    pid = await _ready_proposal(seeded, "knowledge_article", {"article": {"title": "Newborns", "content_markdown": "x"}}, doc_id)
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    assert r.status_code == 200, r.text
    assert r.json()["draft_kept"] is True
    async with sessionmaker()() as s:
        v = await s.get(AgentVersion, r.json()["version"]["id"])
        assert doc_id in v.config["knowledge_doc_ids"]
        assert "Say the weather." not in v.config["policy"]["rules"]  # never gated, never published
        agent = await s.get(Agent, agent_id)
        assert "Say the weather." in agent.draft_config["policy"]["rules"] and doc_id in agent.draft_config["knowledge_doc_ids"]


async def test_draft_not_kept_when_it_matches_the_published_version(client, seeded):
    """Covers: SL-17"""
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the member portal."})
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    assert r.status_code == 200, r.text
    assert r.json()["draft_kept"] is False


async def test_small_cluster_keeps_a_held_out_case_and_cases_repeat(client, seeded, fake_llm):
    """Covers: SL-18"""
    fake_llm(fake())
    await _learning(seeded, case_repeats=2)
    async with sessionmaker()() as s:
        cluster = await s.scalar(select(Cluster).where(Cluster.name == "Adding a newborn to coverage"))
        members = (await s.scalars(select(CallAnalysis).where(CallAnalysis.cluster_id == cluster.id))).all()
        for a in members[5:]:  # leave five member calls
            a.cluster_id = None
        await refresh_stats(s, cluster)
        p = await propose.draft(s, "evergreen-care", cluster)
        await s.commit()
        pid = p.id
    assert len(p.payload["evidence_call_ids"]) == 4 == propose.shown_count(5)
    assert (await client.post(f"/api/proposals/{pid}/evaluate", headers=H)).status_code == 200
    await jobs.drain()
    async with sessionmaker()() as s:
        run = await s.get(EvalRun, (await s.get(FixProposal, pid)).latest_eval_run_id)
        rows = (await s.scalars(select(EvalResult).where(EvalResult.eval_run_id == run.id))).all()
    assert run.summary["held_out_cases"] == 1 and run.summary["cluster_cases"] == 4
    counts: dict[tuple[str, str], int] = {}
    for r in rows:
        if r.case_type in ("cluster", "held_out"):
            counts[(r.case_key, r.arm)] = counts.get((r.case_key, r.arm), 0) + 1
    assert counts and set(counts.values()) == {2}


def _runs(kind: str, arm: str, passed: int, total: int, latency: int = 100) -> list[dict[str, Any]]:
    return [{"key": f"{kind}-{i % 5}", "type": kind, "arm": arm, "repeat": i // 5 + 1, "passed": i < passed, "hard_fail": False,
             "latencies": [latency], "name": f"{kind}-{i % 5}"} for i in range(total)]


def test_lift_is_a_pass_rate():
    """Covers: SL-19"""
    weak = gate.evaluate_gate(_runs("cluster", "baseline", 8, 10) + _runs("cluster", "candidate", 10, 10), repeats=3)
    assert not weak["gate"]["passed"] and weak["gate"]["reasons"][0].startswith("No lift")
    strong = gate.evaluate_gate(_runs("cluster", "baseline", 2, 10) + _runs("cluster", "candidate", 9, 10), repeats=3)
    assert strong["gate"]["passed"], strong["gate"]


def test_slowdown_blocks_only_past_the_budget():
    """Covers: SL-20"""
    noise = gate.evaluate_gate(_runs("cluster", "baseline", 0, 10, 36) + _runs("cluster", "candidate", 10, 10, 264),
                               repeats=3, latency_budget_ms=2000)
    assert noise["gate"]["passed"] and noise["gate"]["warnings"] == ["Slower: p95 264 ms against 36 ms, within the 2000 ms budget"]
    slow = gate.evaluate_gate(_runs("cluster", "baseline", 0, 10, 1200) + _runs("cluster", "candidate", 10, 10, 2600),
                              repeats=3, latency_budget_ms=2000)
    assert not slow["gate"]["passed"] and slow["gate"]["reasons"] == ["Slower: p95 2600 ms against 1200 ms"]
