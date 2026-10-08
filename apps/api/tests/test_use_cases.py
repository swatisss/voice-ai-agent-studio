"""Customer Support & Channels seed data and use-case catalog. Covers: UC-01, UC-02, UC-03, UC-04, UC-05"""
from __future__ import annotations

from sqlalchemy import func, select

from voiceai.core.db import sessionmaker
from voiceai.modules.knowledge.search import search
from voiceai.core.tables import Agent, EvalScenario, KnowledgeDoc, Persona, Tool

H = {"X-Tenant-Id": "evergreen-care"}
SANDBOX = {"X-Tenant-Id": "evergreen-sandbox"}

TITLES = [
    "Policy Inquiry & Status", "Claims Status Tracking", "Document Center & Green Card", "Outbound Renewal Calls",
    "Policyholder Onboarding", "Internal Knowledge Assistant", "Coverage Information Support",
]


async def test_seeded_business_units(client, seeded):
    """Covers: UC-01"""
    agents = (await client.get("/api/agents", headers=H)).json()["items"]
    by_name = {a["name"]: a for a in agents}
    assert {n: a["mode"] for n, a in by_name.items()} == {
        "Customer Care Agent": "inbound", "Renewal Outreach Agent": "outbound",
        "Welcome & Onboarding Agent": "outbound", "Internal Knowledge Assistant": "internal",
    }
    assert all(a["published_version"]["version"] == 1 for a in agents)
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Tool).where(Tool.tenant_id == "evergreen-care")) == 16
        names = {p.name for p in (await s.scalars(select(Persona).where(Persona.tenant_id == "evergreen-care"))).all()}
    assert names == {"Ava", "Grace", "Leo", "Maya", "Sage"}
    expected = {"Customer Care Agent": ("Ava", 10), "Renewal Outreach Agent": ("Leo", 3), "Welcome & Onboarding Agent": ("Maya", 4), "Internal Knowledge Assistant": ("Sage", 2)}
    for name, (persona, tools) in expected.items():
        detail = (await client.get(f"/api/agents/{by_name[name]['id']}/versions", headers=H)).json()["items"][0]
        assert detail["version"] == 1
        draft = (await client.get(f"/api/agents/{by_name[name]['id']}", headers=H)).json()["draft_config"]
        assert len(draft["tool_ids"]) == tools and draft["knowledge_doc_ids"]
        assert (await client.get(f"/api/agents/{by_name[name]['id']}", headers=H)).json()["draft_config"]["persona"]["name"] == persona
    outbound = (await client.get(f"/api/agents/{by_name['Renewal Outreach Agent']['id']}", headers=H)).json()["draft_config"]
    assert outbound["outbound"]["targets_url"] == "/mock/insurance/outreach/renewals"

    assert (await client.get("/api/agents", headers=SANDBOX)).json()["items"] == []
    assert len((await client.get("/api/knowledge", headers=SANDBOX)).json()["items"]) == 1


async def test_use_case_catalog(client, seeded):
    """Covers: UC-02"""
    items = (await client.get("/api/use-cases", headers=H)).json()["items"]
    assert [u["title"] for u in items] == TITLES
    agents = {a["id"]: a for a in (await client.get("/api/agents", headers=H)).json()["items"]}
    for u in items:
        assert u["category"] == "Customer Support & Channels" and u["channels"] == ["voice", "chat"]
        assert u["agent_id"] in agents and u["published"] is True and u["agent_name"] == agents[u["agent_id"]]["name"]
        assert u["mode"] == agents[u["agent_id"]]["mode"]
        assert len(u["sample_utterances"]) >= 2
    renewal = items[3]
    assert renewal["mode"] == "outbound" and renewal["demo_callers"][0]["name"] == "James Carter"
    assert renewal["demo_callers"][0]["member_id"] == "337120" and renewal["demo_callers"][0]["date_of_birth"] == "November 2, 1979"
    assert items[5]["mode"] == "internal" and items[5]["demo_callers"] == []
    assert (await client.get("/api/use-cases", headers=SANDBOX)).json()["items"] == []


async def test_agents_search_only_their_own_knowledge(client, seeded):
    """Covers: UC-03"""
    async with sessionmaker()() as s:
        care = (await s.scalars(select(Agent).where(Agent.tenant_id == "evergreen-care", Agent.name == "Customer Care Agent"))).one()
        internal = (await s.scalars(select(Agent).where(Agent.tenant_id == "evergreen-care", Agent.name == "Internal Knowledge Assistant"))).one()
        care_docs, internal_docs = care.draft_config["knowledge_doc_ids"], internal.draft_config["knowledge_doc_ids"]
        assert not set(care_docs) & set(internal_docs)
        refs = {d.id: d.source_ref for d in (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == "evergreen-care"))).all()}
        assert all("/kb/customer-care" in refs[i] for i in care_docs) and all("/kb/internal" in refs[i] for i in internal_docs)
        titles = {d.id: d.title for d in (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == "evergreen-care"))).all()}

        limits = "authorization limits: what each role may approve for inpatient claims"
        green = "Green Card for driving to Spain"
        limits_for_care = await search(s, "evergreen-care", care_docs, limits)
        limits_for_internal = await search(s, "evergreen-care", internal_docs, limits)
        green_for_internal = await search(s, "evergreen-care", internal_docs, green)
        green_for_care = await search(s, "evergreen-care", care_docs, green)

    def hit_ids(res: dict) -> set[str]:
        return {r["doc_id"] for r in res.get("results", [])}

    assert hit_ids(limits_for_care) <= set(care_docs) and not hit_ids(limits_for_care) & set(internal_docs)
    assert hit_ids(green_for_internal) <= set(internal_docs) and not hit_ids(green_for_internal) & set(care_docs)
    assert titles[limits_for_internal["results"][0]["doc_id"]] == "Authorization limits"
    assert titles[green_for_care["results"][0]["doc_id"]].startswith("Green Card")


async def test_customer_care_regression_scenarios(client, seeded):
    """Covers: UC-04"""
    async with sessionmaker()() as s:
        rows = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == seeded["care"]["agent_id"]))).all()
        others = await s.scalar(select(func.count()).select_from(EvalScenario).where(EvalScenario.agent_id != seeded["care"]["agent_id"]))
    assert {r.name: r.expected for r in rows} == {
        "Policy status": "resolved", "Claim paid": "resolved", "Green Card for Spain": "resolved",
        "Dental coverage": "resolved", "Policy schedule by email": "resolved", "Appeal denied claim": "escalated",
    }
    assert sum(r.expected == "resolved" for r in rows) == 5 and others == 0
    green = next(r for r in rows if r.name == "Green Card for Spain")
    assert green.caller_profile["member_id"] == "337120" and green.caller_profile["destination"] == "Spain"


async def test_seeded_history_and_clusters(client, seeded):
    """Covers: UC-05"""
    t = (await client.get("/api/dashboard/summary", headers=H)).json()["totals"]
    assert (t["calls"], t["resolved"], t["escalated"], t["abandoned"]) == (123, 82, 38, 3)
    clusters = {c["name"]: c for c in (await client.get("/api/insights/clusters", headers=H)).json()["items"]}
    assert clusters["Adding a newborn to coverage"]["escalation_count"] == 14 and clusters["Adding a newborn to coverage"]["ready_for_fix"] is True
    assert clusters["Prior authorization status"]["escalation_count"] == 9 and clusters["Prior authorization status"]["ready_for_fix"] is True
    assert clusters["Claim denial appeals"]["fixable"] is False and clusters["Claim denial appeals"]["label"] == "correct_escalation"
    calls = (await client.get("/api/calls", headers=H)).json()["items"]
    intents = [c["intent"] for c in calls if c["outcome"] == "resolved"]
    counts = {i: intents.count(i) for i in set(intents)}
    assert counts == {"policy_status": 14, "claim_status": 26, "document_request": 16, "coverage_question": 20, "find_provider": 6}
