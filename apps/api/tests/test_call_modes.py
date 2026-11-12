"""Inbound, outbound and internal call modes. Covers: OB-01, OB-02, OB-03, OB-04, OB-05, OB-06, DM-04"""
from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from tests.conftest import script
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent
from voiceai.runtime.outbound import render_opening
from voiceai.runtime.session import AgentSession
from voiceai.runtime.tools import ToolExecutor

H = {"X-Tenant-Id": "northgate-health"}
SARAH = {"member_ref": "NGH-410237"}
VERIFY_SARAH = ("verify_member", {"member_id": "410237", "date_of_birth": "1984-03-14"})
POLICY = ("get_policy_details", {"policy_id": "PMI-300101"})
TARGETS_URL = "/mock/insurance/outreach/renewals"
OPENING = "Hello, may I speak with {first_name}? This is Olivia calling from Northgate Health about {purpose}."


async def _make_agent(client, seeded, mode: str, name: str, tools: list[str], **extra: Any) -> str:  # noqa: ANN001
    """The seed has only inbound agents: build an outbound or internal one from Customer Care's config and publish it."""
    care = (await client.get(f"/api/agents/{seeded['care']['agent_id']}", headers=H)).json()["draft_config"]
    tool_ids = {t["name"]: t["id"] for t in (await client.get("/api/tools", headers=H)).json()["items"]}
    cfg = {**care, "mode": mode, "tool_ids": [tool_ids[n] for n in tools], "skill_ids": [], **extra}
    r = await client.post("/api/agents", headers=H, json={"name": name, "draft_config": cfg})
    assert r.status_code == 200, r.text
    agent_id = r.json()["id"]
    pub = await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "test agent"})
    assert pub.status_code == 200, pub.text
    return agent_id


async def _renewals(client, seeded) -> str:  # noqa: ANN001
    """An outbound renewal agent whose persona has an opening line."""
    care = (await client.get(f"/api/agents/{seeded['care']['agent_id']}", headers=H)).json()["draft_config"]
    return await _make_agent(client, seeded, "outbound", "Renewal Calls", ["verify_member", "get_policy_details"],
                             outbound={"targets_url": TARGETS_URL}, persona_id=None,  # an inline persona with an opening
                             persona={**care["persona"], "opening": OPENING})


async def _internal(client, seeded) -> str:  # noqa: ANN001
    """A staff-facing agent with one tool that needs no verification."""
    return await _make_agent(client, seeded, "internal", "Staff Helpdesk", ["find_specialists"])


async def _outbound_call(client, agent_id: str, ref: dict | None = SARAH, channel: str = "text"):  # noqa: ANN001, ANN202
    body = {"agent_id": agent_id, "channel": channel}
    if ref is not None:
        body["context"] = ref
    return await client.post("/api/calls", headers=H, json=body)


async def _events(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


async def test_outbound_call_requires_a_listed_target(client, seeded):
    """Covers: OB-01"""
    agent_id = await _renewals(client, seeded)
    for ref in (None, {}, {"member_ref": "NGH-000000"}, {"member_ref": "NGH-638405"}):  # none, empty, unknown, listed nowhere (no renewal due)
        r = await _outbound_call(client, agent_id, ref)
        assert r.status_code == 422 and r.json()["error"] == "unknown_target", ref
    r = await _outbound_call(client, agent_id)
    assert r.status_code == 200
    async with sessionmaker()() as s:
        ctx = (await s.get(Call, r.json()["call_id"])).meta["context"]
    assert ctx["first_name"] == "Sarah" and ctx["member_ref"] == "NGH-410237" and ctx["member_id"] == "410237"
    assert ctx["policy_id"] == "PMI-300101" and ctx["purpose"] == "your upcoming policy renewal"


async def test_outbound_call_opens_with_persona_opening(client, seeded):
    """Covers: OB-02"""
    r = await _outbound_call(client, await _renewals(client, seeded))
    assert r.json()["greeting"] == "Hello, may I speak with Sarah? This is Olivia calling from Northgate Health about your upcoming policy renewal."
    assert "Thanks for calling" not in r.json()["greeting"]
    async with sessionmaker()() as s:
        call = await s.get(Call, r.json()["call_id"])
        first = (await s.scalars(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.seq))).first()
    assert call.direction == "outbound" and first.kind == "assistant" and first.text == r.json()["greeting"]


def test_default_opening_without_persona_opening():
    """Covers: OB-02"""
    persona = {"name": "Olivia", "disclosure": "I'm a virtual assistant."}
    text = render_opening(persona, {"first_name": "Sarah"}, "Northgate Health · Member & Sales Services")
    assert text == "Hello, may I speak with Sarah? This is Olivia calling from Northgate Health. I'm a virtual assistant."
    assert render_opening({"opening": "Hi {first_name}, about {missing}."}, {"first_name": "Sarah"}, "T") == "Hi Sarah, about ."


async def test_outbound_callee_must_verify_before_account_tools(client, seeded, fake_llm, app, monkeypatch):
    """Covers: OB-03"""
    agent_id = await _renewals(client, seeded)
    seen: list[str] = []

    class Recording(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.inner = httpx.ASGITransport(app=app)

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return await self.inner.handle_async_request(request)

    monkeypatch.setattr(ToolExecutor, "_client", lambda self, absolute: httpx.AsyncClient(transport=Recording(), base_url="http://internal"))
    fake_llm(script(FakeReply(tool_calls=[POLICY]), FakeReply(tool_calls=[VERIFY_SARAH]), FakeReply(tool_calls=[POLICY]),
                    FakeReply(text="Your premium is £187.40 a month.")))
    call_id = (await _outbound_call(client, agent_id)).json()["call_id"]
    out = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "Yes, speaking. It's the 14th of March 1984."})
    assert out.json()["reply"] == "Your premium is £187.40 a month."
    results = [e.data for e in await _events(call_id) if e.kind == "tool_result"]
    assert results[0]["result"]["error"] == "identity_not_verified"
    assert seen == ["/mock/healthcare/verify", "/mock/insurance/policies/PMI-300101"]  # nothing was sent before verification
    assert results[2]["result"]["monthly_premium"] == 187.40


async def test_internal_agent_prompt_and_unverified_tools(client, seeded, fake_llm):
    """Covers: OB-04"""
    agent_id = await _internal(client, seeded)
    prompts: list[str] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        prompts.append(messages[0]["content"])
        if len(prompts) == 1:
            return FakeReply(tool_calls=[("find_specialists", {"specialty": "orthopaedics", "postcode": "LS1 4AP"})])
        return FakeReply(text="Mr James Holloway at Headingley Park Hospital is fee-assured.")

    fake_llm(responder)
    r = await client.post("/api/calls", headers=H, json={"agent_id": agent_id, "channel": "text"})
    assert r.status_code == 200, r.text
    out = await client.post(f"/api/calls/{r.json()['call_id']}/messages", headers=H,
                            json={"text": "Which fee-assured orthopaedic consultants are near Leeds?"})
    assert "Holloway" in out.json()["reply"]
    assert "Northgate Health colleague" in prompts[0] and "do not ask for member IDs" in prompts[0]
    assert "OUTBOUND" not in prompts[0] and "incoming call" not in prompts[0]
    result = next(e.data for e in await _events(r.json()["call_id"]) if e.kind == "tool_result")
    assert result["ok"] is True and result["result"]["specialists"][0]["name"] == "Mr James Holloway"


async def test_outbound_prompt_carries_call_context(client, seeded, fake_llm):
    """Covers: OB-03"""
    agent_id = await _renewals(client, seeded)
    prompts: list[str] = []
    fake_llm(lambda role, messages, tools: prompts.append(messages[0]["content"]) or FakeReply(text="Hello."))
    call_id = (await _outbound_call(client, agent_id)).json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "Hello?"})
    assert "OUTBOUND call" in prompts[0] and "- first_name: Sarah" in prompts[0] and "- policy_id: PMI-300101" in prompts[0]
    assert "member_id: 410237 (never read aloud)" in prompts[0] and "member_ref" not in prompts[0].split("# How you speak")[0]
    session = await AgentSession.open(call_id, "northgate-health")
    assert session.state.verified is False  # the context never marks the call verified


async def test_outbound_targets_endpoint(client, seeded):
    """Covers: OB-05"""
    agent_id = await _renewals(client, seeded)
    items = (await client.get("/api/outbound/targets", headers=H, params={"agent_id": agent_id})).json()["items"]
    assert [t["first_name"] for t in items] == ["Sarah"]
    assert items[0]["member_ref"] == "NGH-410237" and "PMI-300101 renews in" in items[0]["summary"]
    assert items[0]["context"]["policy_id"] == "PMI-300101"
    for other in (seeded["care"]["agent_id"], await _internal(client, seeded)):
        r = await client.get("/api/outbound/targets", headers=H, params={"agent_id": other})
        assert r.status_code == 409 and r.json()["error"] == "not_outbound"
    assert (await client.get("/api/outbound/targets", headers=H, params={"agent_id": "nope"})).status_code == 404


async def test_calls_carry_direction(client, seeded):
    """Covers: OB-06"""
    agents = {"care": seeded["care"]["agent_id"], "renewals": await _renewals(client, seeded), "internal": await _internal(client, seeded)}
    made = {}
    for key, ref in (("care", None), ("renewals", SARAH), ("internal", None)):
        r = await _outbound_call(client, agents[key], ref)
        assert r.status_code == 200, r.text
        made[key] = r.json()["call_id"]
    detail = (await client.get(f"/api/calls/{made['renewals']}", headers=H)).json()
    assert detail["direction"] == "outbound"
    outbound = (await client.get("/api/calls", headers=H, params={"direction": "outbound"})).json()["items"]
    assert [c["id"] for c in outbound] == [made["renewals"]]
    internal = (await client.get("/api/calls", headers=H, params={"direction": "internal"})).json()["items"]
    assert [c["id"] for c in internal] == [made["internal"]]
    inbound = (await client.get("/api/calls", headers=H, params={"direction": "inbound"})).json()["items"]
    assert made["care"] in {c["id"] for c in inbound} and len(inbound) == 124 and {c["direction"] for c in inbound} == {"inbound"}


async def test_outbound_agent_config_needs_targets_url(client, seeded):
    """Covers: DM-04"""
    agent_id = await _renewals(client, seeded)
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    cfg["outbound"] = {"targets_url": ""}
    r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})
    assert r.status_code == 422 and "targets_url" in r.json()["detail"]
    cfg["mode"] = "sideways"
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})).status_code == 422
