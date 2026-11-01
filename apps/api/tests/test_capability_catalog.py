"""Capability catalog: editable use cases, the snapshot's routing fields, profiles, re-indexing, routing cases.

Covers: CAT-01, CAT-02, CAT-03, CAT-04, CAT-05, CAT-06, CAT-08, DM-11, UC-07, API-11
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from voiceai.db import sessionmaker
from voiceai.models import AgentVersion, CapabilityEntry, CapabilityProfile, Job, RoutingCase
from voiceai.routing import catalog

H = {"X-Tenant-Id": "evergreen-care"}
SANDBOX = {"X-Tenant-Id": "evergreen-sandbox"}


def drafting(calls: list[str] | None = None):  # noqa: ANN201
    """A fake LLM: `drafting` writes 12 index examples or 3 test paraphrases, distinct per prompt."""
    n = {"i": 0}

    def responder(role: str, messages: list[dict[str, Any]], tools: Any) -> Any:
        assert role == "drafting", role
        text = messages[-1]["content"]
        n["i"] += 1
        if calls is not None:
            calls.append(text)
        if "Purpose: test" in text:
            focus = text.split("Focus: ", 1)[1].split(".", 1)[0]
            return {"utterances": [f"test {focus} wording {k} {n['i']}" for k in range(3)]}
        return {"utterances": [f"generated request {k} {n['i']}" for k in range(12)]}

    return responder


async def run_index_jobs() -> int:
    n = 0
    while True:
        async with sessionmaker()() as s:
            job = await s.scalar(select(Job).where(Job.kind == "index_capabilities", Job.status == "queued").order_by(Job.created_at))
            if job is None:
                return n
            job.status = "done"
            await s.commit()
        await catalog.index_capabilities(job.tenant_id, job.payload)
        n += 1


async def test_profiles_for_routable_agents_only(client, seeded, fake_llm):
    """Covers: CAT-01"""
    fake_llm(drafting())
    await run_index_jobs()
    async with sessionmaker()() as s:
        profiles = {p.agent_id: p for p in (await s.scalars(select(CapabilityProfile))).all()}
    assert set(profiles) == {seeded["care"]["agent_id"], seeded["claims"]["agent_id"], seeded["internal"]["agent_id"]}
    claims = profiles[seeded["claims"]["agent_id"]]
    card = claims.card
    assert card["description"] and card["skills"] and all(sk["examples"] for sk in card["skills"])
    assert any(t["name"] == "get_claim_status" for t in card["tools"]) and card["knowledge"]
    assert 10 <= len(card["generated_examples"]) <= 20 and claims.scope == "member" and len(claims.summary) <= 600
    assert profiles[seeded["internal"]["agent_id"]].scope == "staff"
    async with sessionmaker()() as s:
        kinds = set((await s.scalars(select(CapabilityEntry.kind).where(CapabilityEntry.profile_id == claims.id))).all())
        assert {"description", "use_case", "utterance", "generated", "tool"} <= kinds
        assert all(len(e.embedding) > 1 for e in (await s.scalars(select(CapabilityEntry).limit(5))).all())
    # routable: false removes the profile on publish
    agent_id = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": {**draft, "routable": False}})
    assert (await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})).status_code == 200
    await run_index_jobs()
    assert (await client.get(f"/api/agents/{agent_id}/capability", headers=H)).status_code == 404


async def test_new_use_case_reaches_stage_a(client, seeded, fake_llm):
    """Covers: CAT-02, API-11, UC-07"""
    fake_llm(drafting())
    await run_index_jobs()
    care = seeded["care"]["agent_id"]
    r = await client.post("/api/use-cases", headers=H, json={"agent_id": care, "title": "Lost ID card",
                                                             "summary": "Replace a lost member ID card.",
                                                             "sample_utterances": ["I lost my insurance card at the beach", "need a new member card"]})
    assert r.status_code == 201, r.text
    uc = r.json()
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "index_capabilities", Job.status == "queued")) == 1
    await run_index_jobs()
    async with sessionmaker()() as s:
        ranked = await catalog.stage_a(s, "evergreen-care", "member", "I lost my insurance card at the beach")
    assert ranked[0]["agent_id"] == care and ranked[0]["score"] > 0.99
    listed = (await client.get(f"/api/use-cases?agent_id={care}", headers=H)).json()["items"]
    assert "Lost ID card" in [u["title"] for u in listed]
    assert (await client.put(f"/api/use-cases/{uc['id']}", headers=H, json={"summary": "Order a replacement card."})).status_code == 200
    assert (await client.delete(f"/api/use-cases/{uc['id']}", headers=H)).status_code == 204
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "index_capabilities", Job.status == "queued")) == 1
    assert "Lost ID card" not in [u["title"] for u in (await client.get("/api/use-cases", headers=H)).json()["items"]]


async def test_archived_doc_leaves_the_profile(client, seeded, fake_llm):
    """Covers: CAT-03"""
    fake_llm(drafting())
    await run_index_jobs()
    claims = seeded["claims"]["agent_id"]
    before = (await client.get(f"/api/agents/{claims}/capability", headers=H)).json()["knowledge"]
    doc = before[0]
    assert (await client.delete(f"/api/knowledge/{doc['doc_id']}", headers=H)).status_code == 204
    assert await run_index_jobs() == 1
    after = (await client.get(f"/api/agents/{claims}/capability", headers=H)).json()["knowledge"]
    assert doc["title"] not in [k["title"] for k in after]


async def test_tool_edits_wait_for_publish_and_unchanged_inputs_do_nothing(client, seeded, fake_llm):
    """Covers: CAT-04"""
    calls: list[str] = []
    fake_llm(drafting(calls))
    await run_index_jobs()
    claims = seeded["claims"]["agent_id"]
    tools = (await client.get("/api/tools", headers=H)).json()["items"]
    tool = next(t for t in tools if t["name"] == "get_claim_status")
    await client.put(f"/api/tools/{tool['id']}", headers=H, json={**{k: tool[k] for k in ("name", "method", "url", "parameters")}, "description": "CHANGED DESCRIPTION"})
    profile = (await client.get(f"/api/agents/{claims}/capability", headers=H)).json()
    assert "CHANGED DESCRIPTION" not in str(profile["tools"])
    n = len(calls)
    assert (await catalog.index_agent("evergreen-care", claims)).status == "unchanged"
    assert len(calls) == n


async def test_use_case_validation(client, seeded):
    """Covers: CAT-05"""
    care = seeded["care"]["agent_id"]
    assert (await client.post("/api/use-cases", headers=H, json={"agent_id": care, "title": "Empty", "sample_utterances": []})).status_code == 422
    existing = (await client.get(f"/api/use-cases?agent_id={care}", headers=H)).json()["items"][0]["title"]
    dup = await client.post("/api/use-cases", headers=H, json={"agent_id": care, "title": existing, "sample_utterances": ["hello there"]})
    assert dup.status_code == 409 and dup.json()["error"] == "title_taken"
    other = await client.post("/api/use-cases", headers=SANDBOX, json={"agent_id": care, "title": "Nope", "sample_utterances": ["hello there"]})
    assert other.status_code == 404


async def test_snapshot_routing_fields(client, seeded, fake_llm):
    """Covers: CAT-06, DM-11"""
    care = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{care}", headers=H)).json()["draft_config"]
    bad = await client.put(f"/api/agents/{care}", headers=H, json={"draft_config": {**draft, "handoff_intro": "x" * 201}})
    assert bad.status_code == 422
    r = await client.post("/api/agents", headers=H, json={"name": "Fresh agent", "description": "Helps with dental plans"})
    cfg = r.json()["draft_config"]
    assert cfg["routable"] is True and cfg["handoff_intro"] == "You're now with our {agent_name} team."
    await client.put(f"/api/agents/{care}", headers=H, json={"description": "Draft-only description"})
    async with sessionmaker()() as s:
        version = await s.get(AgentVersion, seeded["care"]["version_id"])
        assert version.config["description"] != "Draft-only description" and version.config["routable"] is True
    fake_llm(drafting())
    await run_index_jobs()
    profile = (await client.get(f"/api/agents/{care}/capability", headers=H)).json()
    assert "Draft-only" not in profile["summary"]
    await client.post(f"/api/agents/{care}/publish", headers=H, json={})
    await run_index_jobs()
    assert (await client.get(f"/api/agents/{care}/capability", headers=H)).json()["summary"].startswith("Draft-only description")


async def test_generated_cases_are_held_out_and_one_run_is_queued(client, seeded, fake_llm):
    """Covers: CAT-07, CAT-08"""
    fake_llm(drafting())
    await run_index_jobs()
    async with sessionmaker()() as s:
        cases = (await s.scalars(select(RoutingCase).where(RoutingCase.source == "generated"))).all()
        indexed = {e.lower() for e in (await s.scalars(select(CapabilityEntry.text))).all()}
        assert cases and all(c.utterance.lower() not in indexed for c in cases)
        runs = await s.scalar(select(func.count()).select_from(Job).where(Job.kind == "run_routing_suite", Job.status == "queued"))
    assert runs == 1  # three agents indexed, one run waiting
