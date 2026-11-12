"""Contact tools: email (Brevo), SMS and message calls (Twilio) on every agent, with read-back, guards, outbox and records.

Covers: CT-01, CT-02, CT-03, CT-04, CT-05, CT-06, CT-07, CT-08, CT-09, CT-10, CT-11, CT-12, MOCK-18, DM-15, API-16, DEP-06, TS-06, LANG-06
"""
from __future__ import annotations

import json
from base64 import b64encode
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import inspect, select

from voiceai import contact, db
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, ContactMessage
from voiceai.runtime.session import AgentSession, create_call
from voiceai.runtime.tools import VERIFY_FIRST, VERIFY_UNAVAILABLE

H = {"X-Tenant-Id": "evergreen-care"}
MARIA = {"member_id": "482913", "date_of_birth": "1986-04-12"}
ROBERT = {"member_id": "610277", "date_of_birth": "1958-01-30"}
TWILIO = {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "secret-token", "TWILIO_FROM_NUMBER": "+15005550006"}
BREVO = {"BREVO_API_KEY": "xkeysib-test", "EMAIL_FROM": "care@evergreen.example"}


class Provider:
    """A stand-in for Brevo and Twilio: records every request, answers like the real API."""

    def __init__(self, status: int = 201) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.status >= 400:
            return httpx.Response(self.status, json={"code": "invalid_parameter", "message": "Invalid recipient"})
        if "brevo" in request.url.host:
            return httpx.Response(201, json={"messageId": "<msg-1@smtp-relay.brevo.com>"})
        sid = "SM123" if request.url.path.endswith("Messages.json") else "CA123"
        return httpx.Response(201, json={"sid": sid, "status": "queued"})

    def form(self, i: int = -1) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(self.requests[i].content.decode()).items()}


@pytest.fixture
def provider(monkeypatch) -> Provider:  # noqa: ANN001
    p = Provider()
    monkeypatch.setattr(contact, "TRANSPORT", httpx.MockTransport(p.handler))
    return p


@pytest.fixture
def env(monkeypatch):  # noqa: ANN001, ANN201
    def set_env(**values: str) -> None:
        for k, v in values.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()

    yield set_env
    get_settings.cache_clear()


async def _session(client, seeded, key: str = "care") -> AgentSession:  # noqa: ANN001
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded[key]["agent_id"], "channel": "text"})
    assert r.status_code == 200, r.text
    return await AgentSession.open(r.json()["call_id"], "evergreen-care")


async def _tool(sess: AgentSession, name: str, **args: Any) -> dict[str, Any]:
    """Runs one tool exactly as the turn loop does (events stored, result as the model sees it)."""
    return json.loads(await sess._run_tool(f"t{sess.seq}", name, json.dumps(args)))


async def _verified(client, seeded, who: dict[str, str] = MARIA) -> AgentSession:  # noqa: ANN001
    sess = await _session(client, seeded)
    assert (await _tool(sess, "verify_member", **who)).get("verified") is True
    return sess


async def _rows(call_id: str) -> list[ContactMessage]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(ContactMessage).where(ContactMessage.call_id == call_id)
                                     .order_by(ContactMessage.seq))).all())


def _email(to: str = "registered", confirmed: bool = True, message: str = "Documents: itemised bill, referral letter.") -> dict[str, Any]:
    return {"to": to, "subject": "Your claim documents", "message": message, "confirmed": confirmed}


async def test_every_agent_and_channel_offers_the_contact_tools(client, seeded, fake_llm):
    """Covers: CT-01"""
    seen: list[set[str]] = []

    def responder(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append({(t.get("function") or t)["name"] for t in tools or []})
        return FakeReply(text="Okay.")

    fake_llm(responder)
    for key in ("care", "internal", "claims"):  # inbound with a verifier, internal without HTTP verification, realtime agent
        sess = await _session(client, seeded, key)
        await client.post(f"/api/calls/{sess.call_id}/messages", headers=H, json={"text": "Hello"})
    assert len(seen) == 3 and all({"send_email", "send_sms", "place_call"} <= names for names in seen)
    params = {s["function"]["name"]: s["function"]["parameters"] for s in contact.SCHEMAS}
    assert params["send_email"]["required"] == ["to", "subject", "message", "confirmed"]
    assert params["send_sms"]["required"] == params["place_call"]["required"] == ["to", "message", "confirmed"]

    from tests.test_realtime_voice import build

    bridge, conn, _session_rt, _ = await build(seeded)  # the realtime session.update carries them too
    names = {t["name"] for t in conn.of("session.update")[0]["session"]["tools"]}
    assert {"send_email", "send_sms", "place_call"} <= names
    await bridge.shutdown()


async def test_registered_contact_needs_verification(client, seeded, monkeypatch):
    """Covers: CT-02"""
    looked: list[str] = []

    async def spy(*args: Any, **kwargs: Any) -> None:
        looked.append("lookup")

    monkeypatch.setattr(contact, "registered_contact", spy)
    sess = await _session(client, seeded)
    assert await _tool(sess, "send_email", **_email()) == {"error": "identity_not_verified", "say": VERIFY_FIRST}
    assert sess.state.tool_error_streak == 0 and sess.state.verification_attempts == 0
    internal = await _session(client, seeded, "internal")  # no verification tool: the cannot-verify text
    assert (await _tool(internal, "send_sms", to="registered", message="Hi", confirmed=True))["say"] == VERIFY_UNAVAILABLE
    assert looked == [] and await _rows(sess.call_id) == [] and await _rows(internal.call_id) == []


async def test_registered_email_is_read_back_masked_then_sent(client, seeded, env, provider):
    """Covers: CT-03"""
    env(**BREVO)
    sess = await _verified(client, seeded)
    first = await _tool(sess, "send_email", **_email(confirmed=False))
    assert first["status"] == "needs_confirmation" and first["to"] == "m***@example.com" and "m***@example.com" in first["say"]
    assert provider.requests == [] and await _rows(sess.call_id) == []
    sent = await _tool(sess, "send_email", **_email())
    assert sent == {"status": "sent", "channel": "email", "to": "m***@example.com"}
    assert json.loads(provider.requests[0].content)["to"] == [{"email": "maria.lopez@example.com"}]
    [row] = await _rows(sess.call_id)
    assert (row.destination, row.to_masked, row.status, row.provider) == ("registered", "m***@example.com", "sent", "brevo")
    async with sessionmaker()() as s:
        events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == sess.call_id))).all()
        await sess._persist()
        call = await s.get(Call, sess.call_id)
        await s.refresh(call)
    stored = json.dumps([e.data for e in events], ensure_ascii=False) + json.dumps(call.meta, default=str) + repr(vars(row))
    assert "maria.lopez@example.com" not in stored


async def test_no_registered_mobile(client, seeded, provider):
    """Covers: CT-04"""
    sess = await _verified(client, seeded, ROBERT)
    result = await _tool(sess, "send_sms", to="registered", message="Your claim was received.", confirmed=True)
    assert result == {"error": "no_registered_phone", "say": contact.SAY_NO_PHONE}
    assert provider.requests == [] and await _rows(sess.call_id) == []


async def test_new_addresses_are_validated_normalised_and_masked(client, seeded, env, provider):
    """Covers: CT-05"""
    env(**TWILIO)
    sess = await _session(client, seeded)  # an unverified caller giving their own address
    assert (await _tool(sess, "send_email", **_email(to="maria at example")))["error"] == "invalid_email"
    assert (await _tool(sess, "send_sms", to="12345", message="Hi", confirmed=True))["error"] == "invalid_phone"
    ask = await _tool(sess, "send_sms", to="+1 (202) 555-0199", message="How to file a claim: ...", confirmed=False)
    assert ask["status"] == "needs_confirmation" and ask["to"] == "+12025550199" and provider.requests == []
    sent = await _tool(sess, "send_sms", to="+1 (202) 555-0199", message="How to file a claim: ...", confirmed=True)
    assert sent["status"] == "sent" and sent["to"] == "***0199"
    assert len(provider.requests) == 1 and provider.form()["To"] == "+12025550199"  # nothing else was called
    [row] = await _rows(sess.call_id)
    assert (row.destination, row.to_masked, row.channel) == ("other", "***0199", "sms")


async def test_member_id_and_long_messages_are_refused(client, seeded, provider):
    """Covers: CT-06"""
    sess = await _verified(client, seeded)
    result = await _tool(sess, "send_email", **_email(message="Member evg-482913: claim C-20931 is paid."))
    assert result["error"] == "member_id_in_message"
    too_long = await _tool(sess, "send_sms", to="+12025550199", message="x" * 481, confirmed=True)
    assert too_long["error"] == "message_too_long"
    assert await _rows(sess.call_id) == [] and provider.requests == []


async def test_three_messages_per_call(client, seeded):
    """Covers: CT-07"""
    sess = await _session(client, seeded)
    for to in ("a@example.org", "b@example.org", "c@example.org"):
        assert (await _tool(sess, "send_email", **_email(to=to)))["status"] == "sent"
    assert await _tool(sess, "send_sms", to="+12025550199", message="Hi", confirmed=True) == {"error": "message_limit", "say": contact.SAY_LIMIT}
    assert len(await _rows(sess.call_id)) == 3


async def test_brevo_request_and_failure(client, seeded, env, provider):
    """Covers: CT-08"""
    env(**BREVO, EMAIL_FROM_NAME="Evergreen Care")
    sess = await _session(client, seeded)
    await _tool(sess, "send_email", **_email(to="Maria.L@Example.org"))
    req = provider.requests[0]
    assert req.method == "POST" and str(req.url) == "https://api.brevo.com/v3/smtp/email" and req.headers["api-key"] == "xkeysib-test"
    assert json.loads(req.content) == {"sender": {"email": "care@evergreen.example", "name": "Evergreen Care"},
                                       "to": [{"email": "maria.l@example.org"}], "subject": "Your claim documents",
                                       "textContent": "Documents: itemised bill, referral letter."}
    [row] = await _rows(sess.call_id)
    assert row.status == "sent" and row.provider_ref == "<msg-1@smtp-relay.brevo.com>"
    provider.status = 400
    failed = await _tool(sess, "send_email", **_email(to="x@example.org"))
    assert failed == {"error": "delivery_failed", "say": contact.SAY_FAILED} and sess.state.tool_error_streak == 1
    assert (await _rows(sess.call_id))[-1].status == "failed" and "http_400" in (await _rows(sess.call_id))[-1].error


async def test_twilio_sms_and_message_call(client, seeded, env, provider):
    """Covers: CT-09"""
    env(**TWILIO)
    sess = await _session(client, seeded)
    await _tool(sess, "send_sms", to="+12025550199", message="Claim C-20931 is paid.", confirmed=True)
    req = provider.requests[0]
    assert str(req.url) == "https://api.twilio.com/2010-04-01/Accounts/ACtest/Messages.json"
    assert req.headers["authorization"] == "Basic " + b64encode(b"ACtest:secret-token").decode()
    assert provider.form(0) == {"To": "+12025550199", "From": "+15005550006", "Body": "Claim C-20931 is paid."}
    await _tool(sess, "place_call", to="+12025550199", message="Bring ID & your card.", confirmed=True)
    assert provider.requests[1].url.path.endswith("/Calls.json")
    twiml = provider.form(1)["Twiml"]
    assert twiml.count('<Say language="en-US">Bring ID &amp; your card.</Say>') == 2 and "Here is the message again." in twiml
    await _tool(sess, "place_call", to="+12025550199", message="आपका दावा मिल गया है।", confirmed=True)
    assert 'language="hi-IN"' in provider.form(2)["Twiml"]
    assert [r.provider_ref for r in await _rows(sess.call_id)] == ["SM123", "CA123", "CA123"]


async def test_outbox_without_providers_and_simulations_never_deliver(client, seeded, env, provider):
    """Covers: CT-10"""
    sess = await _session(client, seeded)
    assert (await _tool(sess, "send_email", **_email(to="a@example.org")))["status"] == "sent"
    assert (await _tool(sess, "send_sms", to="+12025550199", message="Hi", confirmed=True))["status"] == "sent"
    assert (await _tool(sess, "place_call", to="+12025550199", message="Hi", confirmed=True))["status"] == "sent"
    assert provider.requests == [] and {(r.status, r.provider) for r in await _rows(sess.call_id)} == {("outbox", "outbox")}

    env(**BREVO, **TWILIO)
    for channel, is_eval in (("simulation", False), ("text", True)):
        async with sessionmaker()() as s:
            call = await create_call(s, "evergreen-care", seeded["care"]["agent_id"], channel, is_eval=is_eval)
            await s.commit()
        sim = await AgentSession.open(call.id, "evergreen-care")
        assert (await _tool(sim, "send_email", **_email(to="a@example.org")))["status"] == "sent"
        assert (await _tool(sim, "place_call", to="+12025550199", message="Hi", confirmed=True))["status"] == "sent"
        assert {r.status for r in await _rows(sim.call_id)} == {"simulated"}
    assert provider.requests == []


async def test_redirect_for_testing(client, seeded, env, provider):
    """Covers: CT-11"""
    env(**BREVO, CONTACT_REDIRECT_EMAIL="owner@test.example")
    sess = await _verified(client, seeded)
    await _tool(sess, "send_email", **_email())
    body = json.loads(provider.requests[0].content)
    assert body["to"] == [{"email": "owner@test.example"}] and body["subject"] == "[for m***@example.com] Your claim documents"
    [row] = await _rows(sess.call_id)
    assert row.redirected is True and row.to_masked == "m***@example.com"


async def test_hindi_message_is_sent_as_written(client, seeded, env, provider):
    """Covers: CT-12, LANG-06"""
    env(**TWILIO)
    sess = await _session(client, seeded)
    message = "आपका दावा १४ मार्च को मिला।"
    await _tool(sess, "send_sms", to="+९१ ९८७६५ ४३२१०", message=message, confirmed=True)
    assert provider.form() == {"To": "+919876543210", "From": "+15005550006", "Body": message}


async def test_mock_contact_endpoint(client, seeded):
    """Covers: MOCK-18"""
    r = await client.get("/mock/healthcare/members/me/contact", headers={"X-Member-Ref": "EVG-482913"})
    assert r.json() == {"email": "maria.lopez@example.com", "mobile": "+12025550141"}
    r = await client.get("/mock/healthcare/members/me/contact", headers={"X-Member-Ref": "EVG-610277"})
    assert r.json() == {"email": "robert.chen@example.com", "mobile": None}
    assert (await client.get("/mock/healthcare/members/me/contact")).status_code == 401


async def test_call_detail_lists_the_messages(client, seeded, env, provider):
    """Covers: API-16"""
    sess = await _verified(client, seeded)
    await _tool(sess, "send_email", **_email())  # outbox
    env(**TWILIO)
    provider.status = 400
    await _tool(sess, "send_sms", to="+12025550199", message="Hi", confirmed=True)
    r = await client.get(f"/api/calls/{sess.call_id}", headers=H)
    msgs = r.json()["contact_messages"]
    assert [(m["channel"], m["destination"], m["to"], m["status"], m["provider"]) for m in msgs] == [
        ("email", "registered", "m***@example.com", "outbox", "outbox"), ("sms", "other", "***0199", "failed", "twilio")]
    assert msgs[1]["error"] and "maria.lopez@example.com" not in r.text and "+12025550199" not in json.dumps(msgs)
    other = await _session(client, seeded)
    assert (await client.get(f"/api/calls/{other.call_id}", headers=H)).json()["contact_messages"] == []


async def test_health_reports_messaging_providers(client, env):
    """Covers: DEP-06"""
    assert (await client.get("/healthz")).json()["messaging"] == {"email": "outbox", "sms": "outbox", "call": "outbox"}
    env(**BREVO, **TWILIO)
    r = await client.get("/healthz")
    assert r.json()["messaging"] == {"email": "brevo", "sms": "twilio", "call": "twilio"}
    assert "xkeysib-test" not in r.text and "secret-token" not in r.text


async def test_contact_tool_names_are_reserved(client, seeded):
    """Covers: TS-06"""
    for name in ("send_email", "send_sms", "place_call"):
        assert (await client.post("/api/tools", headers=H, json={"name": name, "url": "/x"})).status_code == 422


async def test_contact_messages_table_is_added_to_an_old_database(tmp_path: Path):
    """Covers: DM-15"""
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), industry VARCHAR(100), created_at DATETIME)")
        await conn.exec_driver_sql("INSERT INTO tenants VALUES ('t', 'T', '', '2026-10-01 00:00:00')")
    await db.init_db()
    async with db.engine().begin() as conn:
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("contact_messages")})
        assert {"to_masked", "channel", "destination", "status", "provider", "redirected"} <= cols and "to" not in cols
        assert (await conn.exec_driver_sql("SELECT count(*) FROM tenants")).scalar() == 1
    await db.engine().dispose()
