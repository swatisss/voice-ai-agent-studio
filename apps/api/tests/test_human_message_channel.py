"""CP-0049: the human message channel - a text conversation stays open after the hand-off for the specialist.

Fake LLM, temp SQLite, no network.

Covers: HMC-01, HMC-02, HMC-03, HMC-04, HMC-05, HMC-06, HMC-07, HMC-08, PUB-11, PUB-12, API-17, DM-17, DESK-02
"""
from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from tests.conftest import script
from tests.test_agent_desk import signin  # noqa: F401
from tests.test_public_api import H, SANDBOX, _limits, bearer, new_key  # noqa: F401
from voiceai.db import sessionmaker
from voiceai.models import CallEvent, Conversation, WebhookDelivery

BASE = "/v1/tenants/northgate-health/conversations"


@pytest.fixture(autouse=True)
def vault_key(monkeypatch):  # noqa: ANN001, ANN201 - webhook secrets are encrypted with TENANT_SECRETS_KEY
    from voiceai.config import get_settings

    monkeypatch.setenv("TENANT_SECRETS_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _escalated(client, seeded, fake_llm):  # noqa: ANN001, ANN202
    """An API text conversation whose customer asked for a person: returns (key, conversation id, escalation id)."""
    fake_llm(script())
    key = await new_key(client)
    r = await client.post(BASE, headers=bearer(key), json={"channel": "text", "agent_id": seeded["care"]["agent_id"]})
    assert r.status_code == 201, r.text
    cid = r.json()["conversation_id"]
    turn = (await client.post(f"{BASE}/{cid}/messages", headers=bearer(key), json={"text": "I want to speak to a human"})).json()
    assert turn["escalation"] is not None, turn
    return key, cid, turn["escalation"]["id"]


async def _poll(client, key, cid, cursor=None):  # noqa: ANN001, ANN202
    url = f"{BASE}/{cid}/messages" + (f"?cursor={cursor}" if cursor else "")
    r = await client.get(url, headers=bearer(key))
    assert r.status_code == 200, r.text
    return r.json()


async def _accept(client, esc_id, name="Sam Specialist"):  # noqa: ANN001, ANN202
    r = await client.post(f"/api/escalations/{esc_id}/accept", headers=H, json={"assignee": name})
    assert r.status_code == 200, r.text


async def test_customer_line_after_escalation_is_stored_for_the_human(client, seeded, fake_llm):
    """Covers: HMC-01, PUB-11, DM-17"""
    key, cid, esc_id = await _escalated(client, seeded, fake_llm)
    r = await client.post(f"{BASE}/{cid}/messages", headers=bearer(key), json={"text": "Hello? Is someone there?"})
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["status"] == "escalated" and turn["messages"] == [] and turn["escalation"]["id"] == esc_id
    async with sessionmaker()() as s:
        ev = await s.scalar(select(CallEvent).where(CallEvent.text == "Hello? Is someone there?"))
        assert ev.kind == "user" and ev.data == {"to_human": True}


async def test_thread_orders_speakers_and_pages_by_cursor(client, seeded, fake_llm):
    """Covers: HMC-02, PUB-12, API-17"""
    key, cid, esc_id = await _escalated(client, seeded, fake_llm)
    await client.post(f"{BASE}/{cid}/messages", headers=bearer(key), json={"text": "Anyone there?"})
    await _accept(client, esc_id)
    for text in ("Hi, this is Sam.", "How can I help?"):
        r = await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": text})
        assert r.status_code == 201 and r.json()["speaker"] == "human"
    first = await _poll(client, key, cid)
    speakers = [i["speaker"] for i in first["items"]]
    assert speakers[0] == "front_desk" or speakers[0] == "agent" or speakers[0] == "caller"
    assert speakers[-3:] == ["caller", "human", "human"] and first["items"][-1]["author"] == "Sam"
    assert first["escalation"]["status"] == "accepted" and first["escalation"]["assignee"] == "Sam" and first["status"] == "escalated"
    assert all(i["speaker"] in ("caller", "front_desk", "agent", "human") for i in first["items"])
    await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": "Still with you."})
    later = await _poll(client, key, cid, first["cursor"])
    assert [i["text"] for i in later["items"]] == ["Still with you."]
    again = await _poll(client, key, cid, later["cursor"])
    assert again["items"] == [] and again["cursor"] == later["cursor"]


async def test_reply_needs_an_accepted_escalation(client, seeded, fake_llm):
    """Covers: HMC-03, API-17"""
    key, cid, esc_id = await _escalated(client, seeded, fake_llm)
    r = await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": "Hello"})
    assert r.status_code == 409 and r.json()["error"] == "not_accepted"
    assert not any(i["speaker"] == "human" for i in (await _poll(client, key, cid))["items"])
    await _accept(client, esc_id)
    r = await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": "Hello"})
    assert r.status_code == 201
    async with sessionmaker()() as s:
        ev = await s.scalar(select(CallEvent).where(CallEvent.kind == "human"))
        assert ev.text == "Hello" and ev.data == {"author": "Sam Specialist"}
    assert (await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": "   "})).status_code == 422


async def test_reply_to_a_studio_call_is_wrong_channel(client, seeded, fake_llm):
    """Covers: HMC-04"""
    from tests.test_escalation_console import ESC, H as _H  # noqa: PLC0415
    from voiceai.llm.gateway import FakeReply  # noqa: PLC0415
    from voiceai.models import Escalation  # noqa: PLC0415

    fake_llm(lambda role, messages, tools: FakeReply(tool_calls=[ESC]) if role == "realtime" else FakeReply(text="{}"))
    r = await client.post("/api/calls", headers=_H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})
    call_id = r.json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=_H, json={"text": "I want to appeal my denied claim"})
    async with sessionmaker()() as s:
        esc_id = (await s.scalar(select(Escalation).where(Escalation.call_id == call_id))).id
    await _accept(client, esc_id)
    r = await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": "Hello"})
    assert r.status_code == 409 and r.json()["error"] == "wrong_channel"


async def test_resolve_ends_the_conversation(client, seeded, fake_llm):
    """Covers: HMC-05, PUB-11"""
    key, cid, esc_id = await _escalated(client, seeded, fake_llm)
    ep = await client.post("/api/webhooks", headers=H, json={"url": "https://hooks.example.test/in", "events": ["conversation.ended"]})
    assert ep.status_code == 201
    await _accept(client, esc_id)
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H,
                          json={"disposition": "resolved_by_human", "resolution_note": "Explained the excess and sent the form."})
    assert r.status_code == 200, r.text
    thread = await _poll(client, key, cid)
    assert thread["status"] == "ended"
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
        assert conv.end_reason == "human_resolved" and conv.outcome == "escalated" and conv.ended_at is not None
        deliveries = (await s.scalars(select(WebhookDelivery).where(WebhookDelivery.conversation_id == cid, WebhookDelivery.type == "conversation.ended"))).all()
        assert len(deliveries) == 1 and deliveries[0].payload["data"]["end_reason"] == "human_resolved"
    late = await client.post(f"{BASE}/{cid}/messages", headers=bearer(key), json={"text": "one more thing"})
    assert late.status_code == 409 and late.json()["error"] == "conversation_ended"
    reply = await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": "Hello"})
    assert reply.status_code == 409 and reply.json()["error"] == "conversation_ended"


async def test_customer_can_leave_and_the_escalation_still_resolves(client, seeded, fake_llm):
    """Covers: HMC-06"""
    key, cid, esc_id = await _escalated(client, seeded, fake_llm)
    out = (await client.post(f"{BASE}/{cid}/end", headers=bearer(key))).json()
    assert out["status"] == "ended"
    async with sessionmaker()() as s:
        assert (await s.get(Conversation, cid)).end_reason == "caller_left"
    await _accept(client, esc_id)
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H,
                          json={"disposition": "no_action_needed", "resolution_note": "Customer left before we could reply."})
    assert r.status_code == 200


async def test_reply_text_is_delivered_unmasked_and_read_masked_by_a_specialist(client, seeded, fake_llm, signin):
    """Covers: HMC-07, DESK-02"""
    from tests.test_agent_desk import _login  # noqa: PLC0415

    key, cid, esc_id = await _escalated(client, seeded, fake_llm)
    await _accept(client, esc_id)
    number = "Please ring me back on 07700900123."
    r = await client.post(f"/api/escalations/{esc_id}/messages", headers=H, json={"text": number})
    assert r.status_code == 201
    assert (await _poll(client, key, cid))["items"][-1]["text"] == number
    signin()  # the specialist's own read of the escalation masks it (DESK-05)
    await _login(client, "specialist")
    detail = (await client.get(f"/api/escalations/{esc_id}", headers=H)).json()
    texts = [e["text"] for e in detail["events"] if e["kind"] == "human"]
    assert texts and "07700900123" not in texts[-1] and "0123" in texts[-1]


async def test_poll_is_tenant_and_key_bound_and_validates_the_cursor(client, seeded, fake_llm):
    """Covers: HMC-08, PUB-12"""
    key, cid, _ = await _escalated(client, seeded, fake_llm)
    other = await new_key(client, headers=SANDBOX)
    r = await client.get(f"/v1/tenants/northgate-sandbox/conversations/{cid}/messages", headers=bearer(other))
    assert r.status_code == 404
    r = await client.get(f"/v1/tenants/northgate-health/conversations/{uuid.uuid4().hex}/messages", headers=bearer(key))
    assert r.status_code == 404
    r = await client.get(f"{BASE}/{cid}/messages?cursor=not-a-cursor", headers=bearer(key))
    assert r.status_code == 422 and r.json()["error"] == "invalid_cursor"
