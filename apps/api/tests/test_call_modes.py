"""Inbound, outbound and internal call modes. Covers: OB-01, OB-02, OB-03, OB-04, OB-05, OB-06, DM-04"""
from __future__ import annotations

import httpx
from sqlalchemy import select

from tests.conftest import script
from voiceai.core.db import sessionmaker
from voiceai.core.llm.gateway import FakeReply
from voiceai.core.tables import Call, CallEvent
from voiceai.runtime.outbound import render_opening
from voiceai.runtime.session import AgentSession
from voiceai.core.toolcalling import ToolCaller, tool_caller

H = {"X-Tenant-Id": "evergreen-care"}
JAMES = {"member_ref": "EVG-337120"}
VERIFY_JAMES = ("verify_member", {"member_id": "337120", "date_of_birth": "1979-11-02"})
QUOTE = ("get_renewal_quote", {"policy_id": "MP-200415"})


async def _outbound_call(client, seeded, ref: dict | None = JAMES, agent: str = "renewals", channel: str = "text"):  # noqa: ANN001, ANN202
    body = {"agent_id": seeded[agent]["agent_id"], "channel": channel}
    if ref is not None:
        body["context"] = ref
    return await client.post("/api/calls", headers=H, json=body)


async def test_outbound_call_requires_a_listed_target(client, seeded):
    """Covers: OB-01"""
    for ref in (None, {}, {"member_ref": "EVG-000000"}, {"member_ref": "EVG-559804"}):  # none, empty, unknown, listed nowhere (renews in 165 days)
        r = await _outbound_call(client, seeded, ref)
        assert r.status_code == 422 and r.json()["error"] == "unknown_target", ref
    r = await _outbound_call(client, seeded)
    assert r.status_code == 200
    async with sessionmaker()() as s:
        ctx = (await s.get(Call, r.json()["call_id"])).meta["context"]
    assert ctx["first_name"] == "James" and ctx["member_ref"] == "EVG-337120" and ctx["member_id"] == "337120"
    assert ctx["policy_id"] == "MP-200415" and ctx["premium_change_percent"] == 8.0


async def test_outbound_call_opens_with_persona_opening(client, seeded):
    """Covers: OB-02"""
    r = await _outbound_call(client, seeded)
    assert r.json()["greeting"] == "Hello, may I speak with James? This is Leo calling from Evergreen Health about your upcoming policy renewal."
    assert "Thanks for calling" not in r.json()["greeting"]
    async with sessionmaker()() as s:
        call = await s.get(Call, r.json()["call_id"])
        first = (await s.scalars(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.seq))).first()
    assert call.direction == "outbound" and first.kind == "assistant" and first.text == r.json()["greeting"]
    welcome = await _outbound_call(client, seeded, {"member_ref": "EVG-725031"}, agent="onboarding")
    assert welcome.json()["greeting"] == "Hi Aisha, this is Maya from Evergreen Health. I'm calling to welcome you and help you get set up."


def test_default_opening_without_persona_opening():
    """Covers: OB-02"""
    persona = {"name": "Ava", "disclosure": "I'm a virtual assistant."}
    text = render_opening(persona, {"first_name": "Maria"}, "Evergreen Health · Customer Support & Channels")
    assert text == "Hello, may I speak with Maria? This is Ava calling from Evergreen Health. I'm a virtual assistant."
    assert render_opening({"opening": "Hi {first_name}, about {missing}."}, {"first_name": "Maria"}, "T") == "Hi Maria, about ."


async def test_outbound_callee_must_verify_before_account_tools(client, seeded, fake_llm, app, monkeypatch):
    """Covers: OB-03"""
    seen: list[str] = []
    real = tool_caller(app)

    class Recording:  # a ToolCaller that records every request it forwards
        async def request(self, method, url, **kw):  # noqa: ANN001, ANN003, ANN202
            seen.append(url)
            return await real.request(method, url, **kw)

    assert isinstance(Recording(), ToolCaller)
    # the route imported tool_caller by name, so patch it where it is used
    monkeypatch.setattr("voiceai.routes.calls.tool_caller", lambda app=None: Recording())
    fake_llm(script(FakeReply(tool_calls=[QUOTE]), FakeReply(tool_calls=[VERIFY_JAMES]), FakeReply(tool_calls=[QUOTE]), FakeReply(text="It renews at $738.70.")))
    call_id = (await _outbound_call(client, seeded)).json()["call_id"]
    out = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "Yes, speaking. It's November 2nd 1979."})
    assert out.json()["reply"] == "It renews at $738.70."
    results = [e.data for e in await _events(call_id) if e.kind == "tool_result"]
    assert results[0]["result"]["error"] == "identity_not_verified"
    # one port carries every outgoing request now, so the target list fetch is recorded too
    assert seen[0] == "/mock/insurance/outreach/renewals"  # choosing who to call (OB-01)
    # the blocked first quote never left the process: verification precedes any account request
    assert seen[1:] == ["/mock/healthcare/verify", "/mock/insurance/policies/MP-200415/renewal-quote"]
    assert results[2]["result"]["renewal_premium"] == 738.70


async def _events(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


async def test_internal_agent_prompt_and_unverified_tools(client, seeded, fake_llm):
    """Covers: OB-04"""
    prompts: list[str] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        prompts.append(messages[0]["content"])
        if len(prompts) == 1:
            return FakeReply(tool_calls=[("get_authorization_limit", {"role": "claims_handler", "claim_type": "inpatient"})])
        return FakeReply(text="A claims handler can approve up to $5,000 for inpatient claims.")

    fake_llm(responder)
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["internal"]["agent_id"], "channel": "text"})
    assert r.json()["greeting"] == "Evergreen internal knowledge assistant. I'm a virtual assistant. What do you need to know?"
    out = await client.post(f"/api/calls/{r.json()['call_id']}/messages", headers=H, json={"text": "What can a claims handler approve for inpatient?"})
    assert "$5,000" in out.json()["reply"]
    assert "Evergreen Health colleague" in prompts[0] and "do not ask for member IDs" in prompts[0]
    assert "OUTBOUND" not in prompts[0] and "incoming call" not in prompts[0]
    result = next(e.data for e in await _events(r.json()["call_id"]) if e.kind == "tool_result")
    assert result["ok"] is True and result["result"]["limit"] == 5000


async def test_outbound_prompt_carries_call_context(client, seeded, fake_llm):
    """Covers: OB-03"""
    prompts: list[str] = []
    fake_llm(lambda role, messages, tools: prompts.append(messages[0]["content"]) or FakeReply(text="Hello."))
    call_id = (await _outbound_call(client, seeded)).json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "Hello?"})
    assert "OUTBOUND call" in prompts[0] and "- first_name: James" in prompts[0] and "- policy_id: MP-200415" in prompts[0]
    assert "member_id: 337120 (never read aloud)" in prompts[0] and "member_ref" not in prompts[0].split("# How you speak")[0]
    session = await AgentSession.open(call_id, "evergreen-care")
    assert session.state.verified is False  # the context never marks the call verified


async def test_outbound_targets_endpoint(client, seeded):
    """Covers: OB-05"""
    r = await client.get("/api/outbound/targets", headers=H, params={"agent_id": seeded["renewals"]["agent_id"]})
    items = r.json()["items"]
    assert [t["first_name"] for t in items] == ["James", "Maria", "Robert"]
    assert items[0]["member_ref"] == "EVG-337120" and "13 days" in items[0]["summary"] and items[0]["context"]["policy_id"] == "MP-200415"
    onboarding = (await client.get("/api/outbound/targets", headers=H, params={"agent_id": seeded["onboarding"]["agent_id"]})).json()["items"]
    assert [t["first_name"] for t in onboarding] == ["Aisha", "Daniel"]
    for key in ("care", "internal"):
        r = await client.get("/api/outbound/targets", headers=H, params={"agent_id": seeded[key]["agent_id"]})
        assert r.status_code == 409 and r.json()["error"] == "not_outbound"
    assert (await client.get("/api/outbound/targets", headers=H, params={"agent_id": "nope"})).status_code == 404


async def test_calls_carry_direction(client, seeded):
    """Covers: OB-06"""
    made = {}
    for key, ref in (("care", None), ("renewals", JAMES), ("internal", None)):
        r = await _outbound_call(client, seeded, ref, agent=key)
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
    agent_id = seeded["renewals"]["agent_id"]
    cfg = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    cfg["outbound"] = {"targets_url": ""}
    r = await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})
    assert r.status_code == 422 and "targets_url" in r.json()["detail"]
    cfg["mode"] = "sideways"
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": cfg})).status_code == 422
