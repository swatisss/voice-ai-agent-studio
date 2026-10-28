"""Caller verification: a registered number identifies, the date of birth verifies; attempts, attestation and playground calls.

Spec: /architecture/caller-verification.md
Covers: IDV-01, IDV-02, IDV-03, IDV-04, IDV-05, IDV-06, IDV-07, TS-09, ES-09, API-05
"""
from __future__ import annotations

import json

import httpx
from fastapi import FastAPI, Header, Request
from sqlalchemy import select

from tests.conftest import script
from tests.test_telephony import CALLER, call_params, phone, rows, signed_post, stream_of  # noqa: F401  (fixture)
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, Escalation
from voiceai.runtime.session import AgentSession
from voiceai.runtime.state import CallState
from voiceai.runtime.tools import VERIFY_FAILED, ToolExecutor

H = {"X-Tenant-Id": "evergreen-care"}
MARIA_PHONE = "+12025550141"
DOB_ONLY = ("verify_member", {"date_of_birth": "1986-04-12"})


async def _start(client, seeded, caller_number: str | None = None, agent: str = "care") -> str:  # noqa: ANN001
    body = {"agent_id": seeded[agent]["agent_id"], "channel": "text"}
    if caller_number:
        body["caller_number"] = caller_number
    r = await client.post("/api/calls", headers=H, json=body)
    assert r.status_code == 200, r.text
    return r.json()["call_id"]


async def _say(client, call_id: str, text: str) -> dict:  # noqa: ANN001
    r = await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    return r.json()


async def _events(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


def system_of(messages: list[dict]) -> str:
    return next(m["content"] for m in messages if m["role"] == "system")


def test_phone_call_from_a_registered_number_is_identified(phone):  # noqa: F811
    """Covers: IDV-01"""
    r = signed_post(phone.client, call_params(From=MARIA_PHONE, StirVerstat="TN-Validation-Passed-A"))
    _, call_id = stream_of(r.text)
    (meta,), = rows(phone, "select meta from calls where id=?", call_id)
    ident = json.loads(meta)["identification"]
    assert ident == {"member_ref": "EVG-482913", "first_name": "Maria", "method": "caller_id", "attestation": "TN-Validation-Passed-A"}
    assert MARIA_PHONE not in meta and "2025550141" not in meta
    assert rows(phone, "select caller_ref from calls where id=?", call_id) == [(None,)]  # identified, not verified
    detail = phone.client.get(f"/api/calls/{call_id}", headers=H).json()
    assert detail["identification"] == {"first_name": "Maria", "method": "caller_id", "attestation": "TN-Validation-Passed-A"}

    _, other = stream_of(signed_post(phone.client, call_params(From=CALLER)).text)  # IDV-03: not registered
    (meta,), = rows(phone, "select meta from calls where id=?", other)
    assert "identification" not in json.loads(meta)


async def test_playground_caller_number_identifies_like_a_phone_call(client, seeded):
    """Covers: IDV-06, API-05"""
    call_id = await _start(client, seeded, MARIA_PHONE)
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    assert detail["identification"]["first_name"] == "Maria"
    async with sessionmaker()() as s:
        assert MARIA_PHONE not in json.dumps((await s.get(Call, call_id)).meta)
    unknown = await _start(client, seeded, "+12025550199")
    assert (await client.get(f"/api/calls/{unknown}", headers=H)).json()["identification"] is None
    bad = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text", "caller_number": "0123"})
    assert bad.status_code == 422


async def test_identified_caller_verifies_with_the_date_of_birth(client, seeded, fake_llm):
    """Covers: IDV-02, IDV-07, TS-09"""
    seen: list[list[dict]] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append(messages)
        return FakeReply(tool_calls=[DOB_ONLY]) if len(seen) == 1 else FakeReply(text="Thanks Maria, you're verified.")

    fake_llm(responder)
    call_id = await _start(client, seeded, MARIA_PHONE)
    await _say(client, call_id, "April 12th 1986")
    before = system_of(seen[0])
    assert "on Maria's record" in before and "ask only for their date of birth" in before
    assert "EVG-482913" not in before and "- (not verified yet)" in before and "Facts:" not in before  # IDV-07
    session = await AgentSession.open(call_id, "evergreen-care")
    assert session.state.verified and session.state.verified_member_ref == "EVG-482913" and session.state.verification_level == "verified"
    call_args = next(e.data["args"] for e in await _events(call_id) if e.kind == "tool_call")
    assert call_args == {"date_of_birth": "1986-04-12"}  # no member ID was needed


async def test_an_unknown_caller_is_asked_for_member_id_and_date_of_birth(client, seeded, fake_llm):
    """Covers: IDV-03"""
    seen: list[list[dict]] = []
    fake_llm(lambda role, messages, tools: seen.append(messages) or FakeReply(text="Can I have your member ID?"))
    call_id = await _start(client, seeded, "+12025550199")
    await _say(client, call_id, "What is my claim status?")
    assert "Ask for member ID and date of birth" in system_of(seen[0]) and "on Maria's record" not in system_of(seen[0])


async def test_three_failed_attempts_hand_the_call_to_a_human(client, seeded, fake_llm):
    """Covers: IDV-04, ES-09, TS-09"""
    wrong = ("verify_member", {"member_id": "482913", "date_of_birth": "1990-01-01"})
    sorry = FakeReply(text="Let's try again.")
    fake_llm(script(FakeReply(tool_calls=[wrong]), sorry, FakeReply(tool_calls=[wrong]), sorry, FakeReply(tool_calls=[wrong])))
    call_id = await _start(client, seeded)
    for _ in range(2):
        assert (await _say(client, call_id, "482913, January 1st 1990"))["ended"] is False
    out = await _say(client, call_id, "482913, January 1st 1990")
    assert out["ended"] is True and out["escalated"] is True
    results = [e.data["result"] for e in await _events(call_id) if e.kind == "tool_result"]
    assert results == [{"verified": False, "say": VERIFY_FAILED}] * 3  # the same words each time, never the API's reason
    async with sessionmaker()() as s:
        esc = (await s.scalars(select(Escalation).where(Escalation.call_id == call_id))).all()
        call = await s.get(Call, call_id)
    assert [e.reason_category for e in esc] == ["verification_failed"] and call.end_reason == "handoff"


async def test_attested_caller_id_unlocks_read_only_tools_only_when_trusted():
    """Covers: IDV-05"""
    hits: list[tuple[str, str | None]] = []
    app = FastAPI()

    @app.api_route("/echo", methods=["GET", "POST"])
    async def echo(request: Request, x_member_ref: str | None = Header(default=None)) -> dict:
        hits.append((request.method, x_member_ref))
        return {"status": "ok"}

    tools = [{"name": "read_claims", "method": "GET", "url": "/echo", "requires_verification": True},
             {"name": "change_address", "method": "POST", "url": "/echo", "requires_verification": True}]
    state = CallState(identified_member_ref="EVG-482913", identified_first_name="Maria", verification_level="attested")
    ex = ToolExecutor("evergreen-care", "c1", tools, state, app=app)
    read, _ = await ex.run("read_claims", "{}")
    write, _ = await ex.run("change_address", "{}")
    assert read == {"status": "ok"} and hits == [("GET", "EVG-482913")]
    assert write["error"] == "identity_not_verified" and "date of birth" in write["say"] and "member ID" not in write["say"]

    state.verification_level = "identified"  # setting off: both wait for the date of birth
    blocked, _ = await ex.run("read_claims", "{}")
    assert blocked["error"] == "identity_not_verified" and len(hits) == 1


async def test_session_trusts_attestation_only_with_the_setting(client, seeded):
    """Covers: IDV-05"""
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.id == await _start(client, seeded, MARIA_PHONE)))
        call.meta = {**call.meta, "identification": {**call.meta["identification"], "attestation": "TN-Validation-Passed-A"}}
        call.meta.pop("state", None)
        await s.commit()
        call_id = call.id
    from voiceai.runtime.session import REGISTRY

    REGISTRY.pop(call_id, None)
    plain = await AgentSession.open(call_id, "evergreen-care")
    assert plain.state.verification_level == "identified"  # trust_attested_caller_id is off by default
    REGISTRY.pop(call_id, None)
    config = {**plain.config, "verification": {"trust_attested_caller_id": True}}
    trusted = await AgentSession.open(call_id, "evergreen-care", config_override=config)
    assert trusted.state.verification_level == "attested"


async def test_identify_ignores_withheld_numbers(monkeypatch):
    """Covers: IDV-03"""
    from voiceai import caller_id

    called: list[str] = []

    class Boom(httpx.AsyncClient):
        async def post(self, *a, **k):  # noqa: ANN002, ANN003, ANN202
            called.append("post")
            raise AssertionError("withheld numbers are never looked up")

    monkeypatch.setattr(caller_id, "business_client", lambda absolute, app=None: Boom())
    for withheld in ("anonymous", "", "client:alice", None):
        assert await caller_id.identify(withheld) is None
    assert called == []
