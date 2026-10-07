"""Agents, versions, config validation and tenant isolation.

Covers: DM-01, DM-02, DM-03, DM-04, DM-05, MT-01, MT-02, MT-03, MT-04, TS-07
"""
from __future__ import annotations

from sqlalchemy import func, inspect, select

from voiceai.db import engine, sessionmaker
from voiceai.knowledge.ingest import create_doc
from voiceai.models import AgentVersion, KnowledgeChunk, KnowledgeDoc

M = {"X-Tenant-Id": "evergreen-members"}
P = {"X-Tenant-Id": "evergreen-pharmacy"}


async def test_all_tables_exist(database):
    """Covers: DM-01"""
    async with engine().connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert len(names) == 18


async def test_versions_and_snapshots(client, seeded):
    """Covers: DM-02, DM-05"""
    agent_id = seeded["evergreen-members"]["agent_id"]
    tools = (await client.get("/api/tools", headers=M)).json()["items"]
    tool = next(t for t in tools if t["name"] == "find_providers")
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=M, json={"change_note": "second"})
    assert r.json()["version"] == 2
    await client.put(f"/api/tools/{tool['id']}", headers=M, json={**{k: tool[k] for k in ("name", "method", "url", "parameters")}, "description": "CHANGED"})
    async with sessionmaker()() as s:
        versions = (await s.scalars(select(AgentVersion).where(AgentVersion.agent_id == agent_id).order_by(AgentVersion.version))).all()
        assert [v.version for v in versions] == [1, 2]
        snap = next(t for t in versions[1].config["tools"] if t["name"] == "find_providers")
        assert snap["description"] != "CHANGED"


async def test_chunks_deleted_with_doc(database):
    """Covers: DM-03"""
    from voiceai.models import Tenant

    async with sessionmaker()() as s:
        s.add(Tenant(id="t1", name="T1"))
        await s.flush()
        doc = await create_doc(s, "t1", "Doc", "## A\nSome content here for chunking.", "text")
        await s.commit()
        await s.delete(await s.get(KnowledgeDoc, doc.id))
        await s.commit()
        assert await s.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id)) == 0


async def test_config_validation(client, seeded):
    """Covers: DM-04"""
    agent_id = seeded["evergreen-members"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=M)).json()["draft_config"]
    cfg["policy"]["max_turns"] = 2
    r = await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": cfg})
    assert r.status_code == 422


async def test_cross_tenant_isolation(client, seeded):
    """Covers: MT-01, MT-02, MT-03"""
    agent_id = seeded["evergreen-members"]["agent_id"]
    assert (await client.get(f"/api/agents/{agent_id}", headers=P)).status_code == 404
    assert (await client.get("/api/agents")).json()["error"] == "tenant_required"
    pharmacy_doc = (await client.get("/api/knowledge", headers=P)).json()["items"][0]["id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=M)).json()["draft_config"]
    cfg["knowledge_doc_ids"].append(pharmacy_doc)
    await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": cfg})
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=M, json={})
    assert r.status_code == 422


async def test_dashboard_is_tenant_scoped(client, seeded):
    """Covers: MT-04"""
    members = (await client.get("/api/dashboard/summary", headers=M)).json()["totals"]["calls"]
    pharmacy = (await client.get("/api/dashboard/summary", headers=P)).json()["totals"]["calls"]
    assert members == 123 and pharmacy == 0


async def test_publish_requires_skill_tools(client, seeded):
    """Covers: TS-07"""
    agent_id = seeded["evergreen-members"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=M)).json()["draft_config"]
    tools = {t["id"]: t["name"] for t in (await client.get("/api/tools", headers=M)).json()["items"]}
    cfg["tool_ids"] = [i for i in cfg["tool_ids"] if tools[i] != "request_id_card"]
    await client.put(f"/api/agents/{agent_id}", headers=M, json={"draft_config": cfg})
    r = await client.post(f"/api/agents/{agent_id}/publish", headers=M, json={})
    assert r.status_code == 422 and "request_id_card" in r.json()["detail"]
