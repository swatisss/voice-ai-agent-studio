"""Webhooks for public-API conversations: signatures, retries, transcripts, secrets, resend.

Covers: WH-01, WH-02, WH-03, WH-04, WH-05
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from datetime import timedelta

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select, update

from tests.conftest import script
from voiceai import webhooks
from voiceai.db import sessionmaker, utcnow
from voiceai.models import Conversation, Job, WebhookDelivery, WebhookEndpoint
from voiceai.public import auth

H = {"X-Tenant-Id": "evergreen-care"}


@pytest.fixture(autouse=True)
def vault_key(monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setenv("TENANT_SECRETS_KEY", Fernet.generate_key().decode())
    from voiceai.config import get_settings

    get_settings.cache_clear()
    auth.reset_limits()
    yield
    webhooks.transport = None
    get_settings.cache_clear()


class Receiver:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.statuses = list(statuses or [])
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.statuses.pop(0) if self.statuses else 200)


async def run_deliveries() -> int:
    """Run the due `deliver_webhook` jobs only (other jobs stay queued)."""
    n = 0
    while True:
        async with sessionmaker()() as s:
            job = await s.scalar(select(Job).where(Job.kind == "deliver_webhook", Job.status == "queued", Job.run_after <= utcnow()).order_by(Job.created_at))
            if job is None:
                return n
            job.status = "done"
            await s.commit()
        await webhooks.deliver(job.tenant_id, job.payload)
        n += 1


async def make_endpoint(client, events, include_transcript=False) -> dict:  # noqa: ANN001
    r = await client.post("/api/webhooks", headers=H, json={"url": "https://hooks.example.test/in", "events": events, "include_transcript": include_transcript})
    assert r.status_code == 201, r.text
    return r.json()


async def api_conversation(client, seeded, source_key=None) -> tuple[str, dict]:  # noqa: ANN001
    key = source_key or (await client.post("/api/api-keys", headers=H, json={"name": uuid.uuid4().hex[:8], "scope": "member"})).json()
    r = await client.post("/v1/tenants/evergreen-care/conversations", headers={"Authorization": f"Bearer {key['key']}"},
                          json={"channel": "text", "agent_id": seeded["care"]["agent_id"], "external_id": "case-1", "metadata": {"crm": 7}})
    return r.json()["conversation_id"], key


async def test_ended_event_is_signed_and_api_only(client, seeded, fake_llm):
    """Covers: WH-01"""
    fake_llm(script())
    ep = await make_endpoint(client, ["conversation.ended"])
    recv = Receiver()
    webhooks.transport = httpx.MockTransport(recv)
    cid, key = await api_conversation(client, seeded)
    await client.post(f"/v1/tenants/evergreen-care/conversations/{cid}/end", headers={"Authorization": f"Bearer {key['key']}"})
    # a playground conversation produces no webhook
    play = (await client.post("/api/conversations", headers=H, json={"channel": "text", "agent_id": seeded["care"]["agent_id"]})).json()["conversation_id"]
    await client.post(f"/api/conversations/{play}/end", headers=H)
    assert await run_deliveries() == 1
    req = recv.requests[0]
    body = json.loads(req.content)
    assert body["type"] == "conversation.ended" and body["data"]["conversation_id"] == cid
    assert body["data"]["external_id"] == "case-1" and body["data"]["metadata"] == {"crm": 7}
    sig = dict(p.split("=", 1) for p in req.headers["x-voiceai-signature"].split(","))
    expected = hmac.new(ep["secret"].encode(), f"{sig['t']}.".encode() + req.content, hashlib.sha256).hexdigest()
    assert sig["v1"] == expected


async def test_retry_schedule_and_failure(client, seeded, fake_llm):
    """Covers: WH-02"""
    fake_llm(script())
    await make_endpoint(client, ["conversation.started"])
    recv = Receiver([500, 500, 200])
    webhooks.transport = httpx.MockTransport(recv)
    await api_conversation(client, seeded)
    for expected_wait in (10, 60):
        await run_deliveries()
        async with sessionmaker()() as s:
            row = await s.scalar(select(WebhookDelivery))
            assert row.status == "pending"
            wait = (row.next_attempt_at - utcnow()).total_seconds()
            assert expected_wait - 5 < wait <= expected_wait + 1
            await s.execute(update(Job).where(Job.kind == "deliver_webhook", Job.status == "queued").values(run_after=utcnow()))
            await s.commit()
    await run_deliveries()
    async with sessionmaker()() as s:
        row = await s.scalar(select(WebhookDelivery))
        assert row.status == "delivered" and row.attempts == 3
    assert len({json.loads(r.content)["id"] for r in recv.requests}) == 1
    # an endpoint that never answers 2xx fails after 7 attempts
    async with sessionmaker()() as s:
        await s.execute(update(WebhookDelivery).values(status="pending", attempts=6))
        await s.commit()
        row = await s.scalar(select(WebhookDelivery))
    webhooks.transport = httpx.MockTransport(Receiver([503]))
    await webhooks.deliver("evergreen-care", {"delivery_id": row.id})
    async with sessionmaker()() as s:
        row = await s.scalar(select(WebhookDelivery))
        assert row.status == "failed" and row.attempts == 7 and row.last_status_code == 503


async def test_transcripts_only_on_request(client, seeded, fake_llm):
    """Covers: WH-03"""
    from voiceai import conversations
    from voiceai.models import Call, CallScorecard

    fake_llm(script())
    await make_endpoint(client, list(webhooks.EVENTS), include_transcript=False)
    await make_endpoint(client, ["conversation.analyzed"], include_transcript=True)
    recv = Receiver()
    webhooks.transport = httpx.MockTransport(recv)
    key = (await client.post("/api/api-keys", headers=H, json={"name": "t", "scope": "member"})).json()
    r = await client.post("/v1/tenants/evergreen-care/conversations", headers={"Authorization": f"Bearer {key['key']}"},
                          json={"channel": "text", "agent_id": seeded["care"]["agent_id"], "caller": {"number": "+12025550141"}, "message": "hello"})
    cid = r.json()["conversation_id"]
    await client.post(f"/v1/tenants/evergreen-care/conversations/{cid}/end", headers={"Authorization": f"Bearer {key['key']}"})
    async with sessionmaker()() as s:  # stand-in for the score_call job
        call = await s.scalar(select(Call).where(Call.conversation_id == cid))
        s.add(CallScorecard(tenant_id="evergreen-care", call_id=call.id, agent_id=call.agent_id, agent_version_id=call.agent_version_id,
                            measures={}, checks=[], hard_fail=False, score=1.0, judged=False))
        await s.flush()
        await conversations.segment_scored(s, call)
        await s.commit()
    await run_deliveries()
    bodies = [json.loads(q.content) for q in recv.requests]
    plain = [b for b in bodies if "transcript" not in b["data"]]
    assert len(plain) == len(bodies) - 1
    for body in plain:
        text = json.dumps(body)
        assert "transcript" not in body["data"] and "EVG-" not in text and "+12025550141" not in text
        assert not re.search(r"(?<![0-9a-f])0141(?![0-9a-f])", text)  # the last four digits, not a chance match inside a hex id
    analyzed = [json.loads(q.content) for q in recv.requests if json.loads(q.content)["type"] == "conversation.analyzed"]
    assert len(analyzed) == 2 and sum("transcript" in a["data"] for a in analyzed) == 1


async def test_secret_shown_once_encrypted_and_rotated(client, seeded):
    """Covers: WH-04"""
    ep = await make_endpoint(client, ["conversation.started"])
    assert "secret" not in (await client.get("/api/webhooks", headers=H)).json()["items"][0]
    async with sessionmaker()() as s:
        row = await s.get(WebhookEndpoint, ep["id"])
        assert ep["secret"] not in row.secret_ciphertext
    new = (await client.post(f"/api/webhooks/{ep['id']}/rotate", headers=H)).json()["secret"]
    assert new != ep["secret"]
    async with sessionmaker()() as s:
        row = await s.get(WebhookEndpoint, ep["id"])
        header = webhooks.signature_header(row, b"{}", 100)
        sigs = [p.split("=", 1)[1] for p in header.split(",") if p.startswith("v1=")]
        assert sigs == [webhooks.sign(new, b"{}", 100), webhooks.sign(ep["secret"], b"{}", 100)]
        later = webhooks.signature_header(row, b"{}", 100, now=utcnow() + timedelta(hours=25))
        assert later.count("v1=") == 1


async def test_resend_failed_delivery(client, seeded, fake_llm):
    """Covers: WH-05"""
    fake_llm(script())
    await make_endpoint(client, ["conversation.started"])
    webhooks.transport = httpx.MockTransport(Receiver([500]))
    await api_conversation(client, seeded)
    await run_deliveries()
    async with sessionmaker()() as s:
        row = await s.scalar(select(WebhookDelivery))
        await s.execute(update(WebhookDelivery).values(status="failed"))
        await s.execute(update(Job).where(Job.kind == "deliver_webhook", Job.status == "queued").values(status="done"))
        await s.commit()
    recv = Receiver([200])
    webhooks.transport = httpx.MockTransport(recv)
    r = await client.post(f"/api/webhooks/deliveries/{row.id}/resend", headers=H)
    assert r.status_code == 200 and r.json()["status"] == "pending"
    await run_deliveries()
    async with sessionmaker()() as s:
        fresh = await s.get(WebhookDelivery, row.id)
        assert fresh.status == "delivered" and fresh.attempts == 2
    assert json.loads(recv.requests[0].content)["id"] == row.event_id
    deliveries = (await client.get(f"/api/webhooks/{row.endpoint_id}/deliveries", headers=H)).json()["items"]
    assert deliveries[0]["status"] == "delivered"
    assert Conversation  # imported for clarity of the data model used
