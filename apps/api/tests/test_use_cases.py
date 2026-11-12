"""Northgate Health seed data and use-case catalog. Covers: UC-04, UC-05, UC-08, UC-09, UC-10, UC-11, CLM-04, CLM-05"""
from __future__ import annotations

from sqlalchemy import func, select

from voiceai.db import sessionmaker
from voiceai.knowledge.search import search
from voiceai.models import Agent, AgentVersion, EvalScenario, KnowledgeDoc, Persona, TenantSettings, Tool

H = {"X-Tenant-Id": "northgate-health"}
SANDBOX = {"X-Tenant-Id": "northgate-sandbox"}

CARE_TITLES = [
    "Policy & Cover Questions", "Payments & Direct Debit", "Update My Details", "Documents & Membership Card",
    "Book a Digital GP Appointment", "Cash Plan Cover & Claims", "Renewal, Cancellation, Complaints & Bereavement",
]
SALES_TITLES = ["Get a Health Insurance Quote", "Choose & Customise Cover", "Underwriting & Join by Phone"]
CLAIMS_TITLES = [
    "Get Treatment Approved (Pre-authorisation)", "Find a Consultant or Hospital", "Claim & Pre-authorisation Status", "Excess, Shortfalls & Invoices",
]
TITLES = CARE_TITLES + SALES_TITLES + CLAIMS_TITLES

CLAIMS_TOOLS = {"verify_member", "get_member_policies", "check_treatment_cover", "find_specialists", "create_pre_authorisation",
                "get_pre_authorisation", "get_member_claims", "get_claim_status"}


async def _agents(client) -> dict[str, dict]:  # noqa: ANN001
    return {a["name"]: a for a in (await client.get("/api/agents", headers=H)).json()["items"]}


async def test_seeded_business_units(client, seeded):
    """Covers: UC-08"""
    by_name = await _agents(client)
    assert {n: a["mode"] for n, a in by_name.items()} == {
        "Customer Care": "inbound", "Health Cover Sales": "inbound", "Claims & Pre-authorisation": "inbound",
    }
    assert all(a["published_version"]["version"] == 1 for a in by_name.values())
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Tool).where(Tool.tenant_id == "northgate-health")) == 25
        names = {p.name for p in (await s.scalars(select(Persona).where(Persona.tenant_id == "northgate-health"))).all()}
        versions = (await s.scalars(select(AgentVersion).where(AgentVersion.tenant_id == "northgate-health"))).all()
    assert names == {"Olivia", "James", "Hannah"}
    assert len(versions) == 3 and all(v.config["voice"].get("pipeline", "cascade") == "cascade" for v in versions)
    expected = {"Customer Care": ("Olivia", 15, 9), "Health Cover Sales": ("James", 4, 4), "Claims & Pre-authorisation": ("Hannah", 8, 5)}
    for name, (persona, tools, skills) in expected.items():
        detail = (await client.get(f"/api/agents/{by_name[name]['id']}/versions", headers=H)).json()["items"][0]
        assert detail["version"] == 1
        draft = (await client.get(f"/api/agents/{by_name[name]['id']}", headers=H)).json()["draft_config"]
        assert len(draft["tool_ids"]) == tools and len(draft["skill_ids"]) == skills and draft["knowledge_doc_ids"]
        assert draft["persona"]["name"] == persona

    assert (await client.get("/api/agents", headers=SANDBOX)).json()["items"] == []
    assert len((await client.get("/api/knowledge", headers=SANDBOX)).json()["items"]) == 1


async def test_use_case_catalog(client, seeded):
    """Covers: UC-11"""
    items = (await client.get("/api/use-cases", headers=H)).json()["items"]
    assert [u["title"] for u in items] == TITLES
    agents = {a["id"]: a for a in (await client.get("/api/agents", headers=H)).json()["items"]}
    for u in items:
        assert u["category"] == "Member & Sales Services" and u["channels"] == ["voice", "chat"]
        assert u["agent_id"] in agents and u["published"] is True and u["agent_name"] == agents[u["agent_id"]]["name"]
        assert u["mode"] == agents[u["agent_id"]]["mode"] == "inbound"
        assert len(u["sample_utterances"]) >= 3
    per_agent = [u["agent_name"] for u in items]
    assert per_agent.count("Customer Care") == 7 and per_agent.count("Health Cover Sales") == 3 and per_agent.count("Claims & Pre-authorisation") == 4
    first = items[0]["demo_callers"][0]
    assert (first["name"], first["member_id"], first["date_of_birth"]) == ("Sarah Mitchell", "410237", "14 March 1984")
    assert all(c["member_id"] == "" for u in items[7:10] for c in u["demo_callers"])  # prospects have no membership number
    assert (await client.get("/api/use-cases", headers=SANDBOX)).json()["items"] == []


async def test_agents_search_only_their_own_knowledge(client, seeded):
    """Covers: UC-09"""
    async with sessionmaker()() as s:
        agents = {a.name: a for a in (await s.scalars(select(Agent).where(Agent.tenant_id == "northgate-health"))).all()}
        docs = {k: agents[n].draft_config["knowledge_doc_ids"] for k, n in
                (("care", "Customer Care"), ("sales", "Health Cover Sales"), ("claims", "Claims & Pre-authorisation"))}
        all_docs = (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == "northgate-health"))).all()
        refs = {d.id: d.source_ref for d in all_docs}
        titles = {d.id: d.title for d in all_docs}
        under = "what is moratorium underwriting"
        shortfall = "what is a shortfall"
        under_sales = await search(s, "northgate-health", docs["sales"], under)
        under_care = await search(s, "northgate-health", docs["care"], under)
        short_claims = await search(s, "northgate-health", docs["claims"], shortfall)
        short_care = await search(s, "northgate-health", docs["care"], shortfall)
        short_sales = await search(s, "northgate-health", docs["sales"], shortfall)

    def hit_ids(res: dict) -> set[str]:
        return {r["doc_id"] for r in res.get("results", [])}

    assert not set(docs["care"]) & set(docs["sales"]) and not set(docs["care"]) & set(docs["claims"]) and not set(docs["sales"]) & set(docs["claims"])
    for key, folder in (("care", "kb/customer-care"), ("sales", "kb/sales"), ("claims", "kb/claims")):
        assert all(folder in refs[i] for i in docs[key])
    assert titles[under_sales["results"][0]["doc_id"]].startswith("Underwriting")
    assert all("kb/sales" not in refs[i] for i in hit_ids(under_care))
    assert titles[short_claims["results"][0]["doc_id"]] == "Excess and shortfalls"
    assert all(titles[i] != "Excess and shortfalls" for i in hit_ids(short_care) | hit_ids(short_sales))


async def test_customer_care_regression_scenarios(client, seeded):
    """Covers: UC-04"""
    async with sessionmaker()() as s:
        rows = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == seeded["care"]["agent_id"]))).all()
    assert {r.name: r.expected for r in rows} == {
        "Policy cover by text": "resolved", "Missed payment": "resolved", "Digital GP for my daughter": "resolved",
        "Cash plan optical limit": "resolved", "Membership certificate by email": "resolved", "Complaint": "escalated",
        "Wrong date of birth first": "resolved", "Remembers email preference": "resolved",
    }
    assert sum(r.expected == "resolved" for r in rows) == 7
    by = {r.name: r for r in rows}
    assert all(r.enabled for r in rows)
    assert {r.name: r.persona for r in rows if r.persona != "calm"} == {
        "Digital GP for my daughter": "impatient", "Cash plan optical limit": "confused", "Wrong date of birth first": "adversarial"}
    assert by["Policy cover by text"].caller_profile["name"] == "Sarah Mitchell" and by["Complaint"].caller_profile["name"] == "Raj Patel"
    assert by["Missed payment"].required_tools == [
        {"name": "get_payments", "args": {"policy_id": "PMI-300214"}}, {"name": "retry_missed_payment", "args": {"policy_id": "PMI-300214"}}]
    assert by["Cash plan optical limit"].required_tools == [{"name": "get_cash_plan_benefits", "args": {"policy_id": "CSH-400118"}}]
    assert by["Membership certificate by email"].required_tools == [
        {"name": "request_document", "args": {"document_type": "membership_certificate", "delivery": "email"}}]
    assert by["Membership certificate by email"].expected_results == [{"tool": "request_document", "field": "status", "equals": "queued"}]
    assert by["Remembers email preference"].memory == ["Prefers documents by email"]
    assert by["Remembers email preference"].required_tools == [
        {"name": "request_document", "args": {"document_type": "membership_card", "delivery": "email"}}]


async def test_seeded_history_and_clusters(client, seeded):
    """Covers: UC-05"""
    t = (await client.get("/api/dashboard/summary", headers=H)).json()["totals"]
    assert (t["calls"], t["resolved"], t["escalated"], t["abandoned"]) == (123, 82, 38, 3)
    clusters = {c["name"]: c for c in (await client.get("/api/insights/clusters", headers=H)).json()["items"]}
    assert clusters["Adding a newborn to the policy"]["escalation_count"] == 14 and clusters["Adding a newborn to the policy"]["ready_for_fix"] is True
    assert clusters["Pre-authorisation status"]["escalation_count"] == 9 and clusters["Pre-authorisation status"]["ready_for_fix"] is True
    assert clusters["Complaints"]["fixable"] is False and clusters["Complaints"]["label"] == "correct_escalation"
    calls = (await client.get("/api/calls", headers=H)).json()["items"]
    intents = [c["intent"] for c in calls if c["outcome"] == "resolved"]
    counts = {i: intents.count(i) for i in set(intents)}
    assert counts == {"policy_status": 14, "payment_question": 26, "document_request": 16, "coverage_question": 20, "gp_booking": 6}


async def test_front_desk_and_other_scenarios(client, seeded):
    """Covers: UC-10"""
    by_name = await _agents(client)
    async with sessionmaker()() as s:
        fd = (await s.get(TenantSettings, "northgate-health")).front_desk
        olivia = (await s.scalars(select(Persona).where(Persona.tenant_id == "northgate-health", Persona.name == "Olivia"))).one()
        sales = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == by_name["Health Cover Sales"]["id"]))).all()
        claims = (await s.scalars(select(EvalScenario).where(EvalScenario.agent_id == by_name["Claims & Pre-authorisation"]["id"]))).all()
        sales_agent = await s.get(Agent, by_name["Health Cover Sales"]["id"])
        sales_tools = (await s.scalars(select(Tool).where(Tool.id.in_(sales_agent.draft_config["tool_ids"])))).all()
    assert fd["persona_id"] == olivia.id and fd["default_agents"]["member"] == by_name["Customer Care"]["id"]
    assert fd["connecting_message"] == "One moment while I connect you to the right team."
    assert sorted(sc.expected for sc in sales) == ["escalated", "resolved", "resolved"]
    assert {sc.name for sc in sales} == {"Couple quote and join", "Smoker asks the price", "Asks for advice"}
    assert sorted(sc.expected for sc in claims) == ["escalated", "resolved", "resolved", "resolved"]
    assert {sc.name for sc in claims} == {"Knee pain, Direct Access", "Pre-authorisation status", "Shortfall explained", "Excluded back treatment"}
    assert len(sales_tools) == 4 and not any(t.requires_verification for t in sales_tools)


async def test_claims_agent_seed(client, seeded):
    """Covers: CLM-04"""
    agents = await _agents(client)
    claims = agents["Claims & Pre-authorisation"]
    assert claims["published_version"]["version"] == 1 and claims["mode"] == "inbound"
    async with sessionmaker()() as s:
        cfg = (await s.get(AgentVersion, claims["published_version"]["id"])).config
        care_cfg = (await s.get(AgentVersion, agents["Customer Care"]["published_version"]["id"])).config
        refs = {d.id: d.source_ref for d in (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.tenant_id == "northgate-health"))).all()}
    assert cfg["persona"]["name"] == "Hannah" and cfg["voice"].get("pipeline", "cascade") == "cascade"
    assert {t["name"] for t in cfg["tools"]} == CLAIMS_TOOLS
    assert [k["name"] for k in cfg["skills"]] == [
        "Identity verification", "Get treatment approved (pre-authorisation)", "Find a consultant or hospital",
        "Pre-authorisation and claim status", "Excess, shortfalls and invoices"]
    assert len(cfg["knowledge_doc_ids"]) == 8 and all("kb/claims" in refs[i] for i in cfg["knowledge_doc_ids"])
    care_tools = {t["name"] for t in care_cfg["tools"]}
    assert not care_tools & {"check_treatment_cover", "find_specialists", "create_pre_authorisation", "get_pre_authorisation",
                             "get_member_claims", "get_claim_status"}


async def test_claims_and_sales_use_cases(client, seeded):
    """Covers: CLM-05"""
    agents = await _agents(client)
    items = (await client.get("/api/use-cases", headers=H)).json()["items"]
    assert [u["title"] for u in items[10:14]] == CLAIMS_TITLES
    assert all(u["agent_id"] == agents["Claims & Pre-authorisation"]["id"] for u in items[10:14])
    assert [u["title"] for u in items[7:10]] == SALES_TITLES
    assert all(u["agent_id"] == agents["Health Cover Sales"]["id"] for u in items[7:10])
    assert all(len(u["sample_utterances"]) >= 3 for u in items[7:14])
