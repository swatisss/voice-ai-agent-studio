"""Public /v1 API: keys, tenant binding, scopes, rate limits, conversations, streaming, connect tokens, media streams.

Covers: PUB-01, PUB-02, PUB-03, PUB-04, PUB-05, PUB-06, PUB-07, PUB-08, PUB-09, PUB-10, MT-14, MT-15, API-10, API-12, DM-10
"""
from __future__ import annotations

import base64
import hashlib
import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import script
from voiceai.db import sessionmaker, utcnow
from voiceai.llm.gateway import FakeReply
from voiceai.models import ApiKey, Call, Conversation
from voiceai.public import auth, tokens

H = {"X-Tenant-Id": "evergreen-care"}
SANDBOX = {"X-Tenant-Id": "evergreen-sandbox"}
MARIA_PHONE = "+12025550141"


@pytest.fixture(autouse=True)
def _limits():
    auth.reset_limits()
    tokens._used.clear()
    yield
    auth.reset_limits()


async def new_key(client, scope: str = "member", headers=H, **extra) -> dict:  # noqa: ANN001
    r = await client.post("/api/api-keys", headers=headers, json={"name": f"{scope}-{uuid.uuid4().hex[:8]}", "scope": scope, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def bearer(key: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {key['key']}"}


async def test_key_shown_once_and_stored_hashed(client, seeded):
    """Covers: PUB-01, API-10"""
    key = await new_key(client)
    raw = key["key"]
    assert raw.startswith("vak_") and len(raw) == 44 and key["prefix"] == raw[:12]
    listed = (await client.get("/api/api-keys", headers=H)).json()["items"]
    assert listed[0]["prefix"] == raw[:12] and "key" not in listed[0] and raw not in json.dumps(listed)
    async with sessionmaker()() as s:
        row = await s.get(ApiKey, key["id"])
        assert row.key_hash == hashlib.sha256(raw.encode()).hexdigest() and raw not in json.dumps(row.__dict__, default=str)
        assert row.last_used_at is None
    r = await client.get("/v1/tenants/evergreen-care/agents", headers=bearer(key))
    assert r.status_code == 200
    async with sessionmaker()() as s:
        assert (await s.get(ApiKey, key["id"])).last_used_at is not None
    # the scope cannot change; revoking ends access; a 21st active key is refused
    assert (await client.put(f"/api/api-keys/{key['id']}", headers=H, json={"scope": "staff"})).status_code == 422
    assert (await client.delete(f"/api/api-keys/{key['id']}", headers=H)).status_code == 204
    assert (await client.get("/v1/tenants/evergreen-care/agents", headers=bearer(key))).status_code == 401
    for i in range(20):
        assert (await client.post("/api/api-keys", headers=H, json={"name": f"k{i}", "scope": "member"})).status_code == 201
    r = await client.post("/api/api-keys", headers=H, json={"name": "k21", "scope": "member"})
    assert r.status_code == 409 and r.json()["error"] == "too_many_keys"


async def test_tenant_bound_to_key(client, seeded):
    """Covers: PUB-02, MT-14"""
    key = await new_key(client)
    other = await client.get("/v1/tenants/evergreen-sandbox/agents", headers={**bearer(key), "X-Tenant-Id": "evergreen-sandbox"})
    unknown = await client.get("/v1/tenants/no-such-tenant/agents", headers=bearer(key))
    assert other.status_code == unknown.status_code == 404
    assert other.json()["error"] == "tenant_not_found"
    assert other.json()["detail"].replace("evergreen-sandbox", "X") == unknown.json()["detail"].replace("no-such-tenant", "X")
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "Bearer vak_" + "a" * 40}, {"Authorization": key["key"]}):
        r = await client.get("/v1/tenants/evergreen-care/agents", headers=headers)
        assert r.status_code == 401 and r.json()["error"] == "invalid_key" and r.headers["www-authenticate"] == "Bearer"


async def test_scope_limits_reachable_agents(client, seeded):
    """Covers: PUB-03"""
    member, staff = await new_key(client, "member"), await new_key(client, "staff")
    names = {a["name"] for a in (await client.get("/v1/tenants/evergreen-care/agents", headers=bearer(member))).json()["items"]}
    assert names == {"Customer Care Agent", "Insurance Claims Agent"}
    staff_names = {a["name"] for a in (await client.get("/v1/tenants/evergreen-care/agents", headers=bearer(staff))).json()["items"]}
    assert staff_names == {"Internal Knowledge Assistant"}
    for key, agent in ((member, "internal"), (member, "renewals"), (staff, "care")):
        r = await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key),
                              json={"channel": "text", "agent_id": seeded[agent]["agent_id"]})
        assert r.status_code == 404 and r.json()["error"] == "agent_not_found"


async def test_rate_limits(client, seeded, monkeypatch):
    """Covers: PUB-04"""
    key = await new_key(client, rate_limit_per_min=10)
    for _ in range(10):
        assert (await client.get("/v1/tenants/evergreen-care/agents", headers=bearer(key))).status_code == 200
    r = await client.get("/v1/tenants/evergreen-care/agents", headers=bearer(key))
    assert r.status_code == 429 and r.json()["error"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    assert r.headers["x-ratelimit-remaining"] == "0"
    # concurrent voice: one active voice conversation blocks the next
    monkeypatch.setenv("PUBLIC_API_SECRET", "s3cret")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    from voiceai.config import get_settings

    get_settings.cache_clear()
    try:
        voice_key = await new_key(client, max_concurrent_voice=1)
        body = {"channel": "voice", "agent_id": seeded["care"]["agent_id"]}
        assert (await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(voice_key), json=body)).status_code == 201
        r = await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(voice_key), json=body)
        assert r.status_code == 429 and r.json()["error"] == "voice_capacity"
    finally:
        get_settings.cache_clear()


async def test_text_conversation(client, seeded, fake_llm):
    """Covers: PUB-05"""
    key = await new_key(client)
    fake_llm(script(FakeReply(text="Sure, I can help with a claim."), FakeReply(text="Your claim is being processed.")))
    r = await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key),
                          json={"channel": "text", "agent_id": seeded["claims"]["agent_id"], "message": "I want to check on a claim"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "active" and body["agent"]["name"] == "Insurance Claims Agent" and body["routing"]["method"] == "explicit"
    assert [m["speaker"] for m in body["messages"]] == ["agent", "agent"]
    assert "virtual assistant" in body["messages"][0]["text"].lower() and body["messages"][1]["text"] == "Sure, I can help with a claim."
    cid = body["conversation_id"]
    turn = (await client.post(f"/v1/tenants/evergreen-care/conversations/{cid}/messages", headers=bearer(key), json={"text": "C-20931"})).json()
    assert turn["agent"]["name"] == "Insurance Claims Agent" and turn["messages"][0]["text"] == "Your claim is being processed."
    assert turn["transferred"] is False and turn["ended"] is False
    first = (await client.post(f"/v1/tenants/evergreen-care/conversations/{cid}/end", headers=bearer(key))).json()
    second = (await client.post(f"/v1/tenants/evergreen-care/conversations/{cid}/end", headers=bearer(key))).json()
    assert first == second and first["status"] == "ended"


async def test_streamed_turn_equals_json_turn(client, seeded, fake_llm):
    """Covers: PUB-06"""
    key = await new_key(client)
    fake_llm(script(FakeReply(text="Hello there."), FakeReply(text="Hello there.")))
    create = {"channel": "text", "agent_id": seeded["care"]["agent_id"]}
    a = (await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key), json=create)).json()["conversation_id"]
    b = (await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key), json=create)).json()["conversation_id"]
    plain = (await client.post(f"/v1/tenants/evergreen-care/conversations/{a}/messages", headers=bearer(key), json={"text": "hi"})).json()
    r = await client.post(f"/v1/tenants/evergreen-care/conversations/{b}/messages", headers={**bearer(key), "Accept": "text/event-stream"}, json={"text": "hi"})
    assert r.headers["content-type"].startswith("text/event-stream")
    events = [(blk.split("\n")[0][7:], json.loads(blk.split("\n")[1][6:])) for blk in r.text.strip().split("\n\n")]
    assert events[0][0] == "message.delta" and events[-1][0] == "turn.done" and sum(1 for e in events if e[0] == "turn.done") == 1
    done = events[-1][1]
    assert {k: v for k, v in done.items() if k != "conversation_id"} == {k: v for k, v in plain.items() if k != "conversation_id"}


@pytest.fixture
def live(app, tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """A running app (TestClient) with a seeded database and voice configured."""
    for k, v in {"DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'live.db').as_posix()}", "AUTO_SEED": "1",
                 "PUBLIC_API_SECRET": "s3cret", "DEEPGRAM_API_KEY": "dg-test", "PUBLIC_BASE_URL": "https://voice.example.test"}.items():
        monkeypatch.setenv(k, v)
    from voiceai.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        key = c.post("/api/api-keys", headers=H, json={"name": "live", "scope": "member"}).json()
        agents = {a["name"]: a["id"] for a in c.get("/api/agents", headers=H).json()["items"]}
        yield c, key, agents
    get_settings.cache_clear()


def _voice(c, key, agent_id: str, **extra) -> dict:  # noqa: ANN001
    r = c.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key), json={"channel": "voice", "agent_id": agent_id, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_voice_connect_tokens(live, monkeypatch):
    """Covers: PUB-07"""
    c, key, agents = live
    served: list[str] = []

    async def fake_serve(websocket, conv, phone=None):  # noqa: ANN001, ANN202
        served.append(conv.current_call_id)
        await websocket.send_text(json.dumps({"type": "ready"}))
        await websocket.close(code=1000)

    from voiceai import voice_calls

    monkeypatch.setattr(voice_calls, "serve_conversation", fake_serve)
    v = _voice(c, key, agents["Customer Care Agent"])
    conn = v["connect"]
    assert conn["url"] == f"wss://voice.example.test/v1/voice/{v['conversation_id']}"
    path = f"/v1/voice/{v['conversation_id']}"

    def closes_4401(**kw) -> None:  # noqa: ANN003
        with pytest.raises(WebSocketDisconnect) as exc, c.websocket_connect(kw.pop("p", path), **kw) as ws:
            ws.receive_text()
        assert exc.value.code == 4401

    closes_4401(p=path + f"?token={conn['token']}")              # query strings are refused
    other = _voice(c, key, agents["Customer Care Agent"])
    closes_4401(headers={"Authorization": f"Bearer {other['connect']['token']}"})  # another conversation's token
    with c.websocket_connect(path, headers={"Authorization": f"Bearer {conn['token']}"}) as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
    closes_4401(headers={"Authorization": f"Bearer {conn['token']}"})  # used once
    third = _voice(c, key, agents["Customer Care Agent"])
    with c.websocket_connect(f"/v1/voice/{third['conversation_id']}", subprotocols=["vai.voice.v1", f"vai-token.{third['connect']['token']}"]) as ws:
        assert ws.accepted_subprotocol == "vai.voice.v1"
        ws.receive_text()
    expired, _ = tokens.mint("evergreen-care", other["conversation_id"], "websocket", now=0)
    closes_4401(p=f"/v1/voice/{other['conversation_id']}", headers={"Authorization": f"Bearer {expired}"})
    assert len(served) == 2


def test_media_stream_transport(live, monkeypatch):
    """Covers: PUB-08"""
    c, key, agents = live
    seen = []

    async def fake_serve(websocket, conv, phone=None):  # noqa: ANN001, ANN202
        seen.append(phone)

    from voiceai import voice_calls

    monkeypatch.setattr(voice_calls, "serve_conversation", fake_serve)
    for fmt in ("mulaw_8k", "pcm_16k"):
        extra = {"transport": "media-stream"} | ({"audio_format": fmt} if fmt == "pcm_16k" else {})
        v = _voice(c, key, agents["Customer Care Agent"], **extra)
        assert v["connect"]["url"].endswith(f"/v1/media-stream/{v['conversation_id']}")
        with c.websocket_connect(f"/v1/media-stream/{v['conversation_id']}", headers={"Authorization": f"Bearer {v['connect']['token']}"}) as ws:
            ws.send_text(json.dumps({"event": "connected"}))
            ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ1", "callSid": "", "customParameters": {}}}))
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
    assert [p.audio_format for p in seen] == ["mulaw_8k", "pcm_16k"] and all(p.stream_sid == "MZ1" and not p.twilio for p in seen)


async def test_pcm_media_serializer():
    """Covers: PUB-08"""
    from pipecat.frames.frames import InputAudioRawFrame, InputTransportMessageFrame, InterruptionFrame, OutputAudioRawFrame

    from voiceai.voice.phone import PcmStreamSerializer

    ser = PcmStreamSerializer("MZ1")
    ser._sample_rate = 16000
    pcm = b"\x01\x00" * 320
    frame = await ser.deserialize(json.dumps({"event": "media", "media": {"payload": base64.b64encode(pcm).decode()}}))
    assert isinstance(frame, InputAudioRawFrame) and frame.audio == pcm and frame.sample_rate == 16000
    out = json.loads(await ser.serialize(OutputAudioRawFrame(audio=pcm, sample_rate=16000, num_channels=1)))
    assert out["event"] == "media" and out["streamSid"] == "MZ1" and base64.b64decode(out["media"]["payload"]) == pcm
    assert json.loads(await ser.serialize(InterruptionFrame()))["event"] == "clear"
    stop = await ser.deserialize(json.dumps({"event": "stop"}))
    assert isinstance(stop, InputTransportMessageFrame) and stop.message == {"type": "hangup"}


async def test_caller_number_context_and_metadata(client, seeded, fake_llm):
    """Covers: PUB-09"""
    key = await new_key(client)
    fake_llm(script())
    r = await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key), json={
        "channel": "text", "agent_id": seeded["care"]["agent_id"], "caller": {"number": MARIA_PHONE},
        "context": {"ivr_menu": "claims"}, "metadata": {"crm_case": "48213"}, "external_id": "case-48213"})
    assert r.status_code == 201 and MARIA_PHONE not in r.text
    cid = r.json()["conversation_id"]
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.conversation_id == cid))
        assert call.meta["identification"]["first_name"] == "Maria" and call.meta["context"]["ivr_menu"] == "claims"
        assert MARIA_PHONE not in json.dumps(call.meta) and MARIA_PHONE not in json.dumps((await s.get(Conversation, cid)).__dict__, default=str)
    view = (await client.get(f"/v1/tenants/evergreen-care/conversations/{cid}", headers=bearer(key))).json()
    assert view["metadata"] == {"crm_case": "48213"} and view["external_id"] == "case-48213"
    bad = await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key),
                            json={"channel": "text", "agent_id": seeded["care"]["agent_id"], "context": {"Bad-Key": "x"}})
    assert bad.status_code == 422


async def test_conversation_view_and_transcript(client, seeded, fake_llm):
    """Covers: PUB-10"""
    key = await new_key(client)
    fake_llm(script(FakeReply(text="Let me look that up.", tool_calls=[("search_knowledge", {"query": "copay"})]), FakeReply(text="Your copay is $25.")))
    cid = (await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key),
                             json={"channel": "text", "agent_id": seeded["care"]["agent_id"], "message": "What is my copay?"})).json()["conversation_id"]
    view = (await client.get(f"/v1/tenants/evergreen-care/conversations/{cid}?include=transcript", headers=bearer(key))).json()
    assert [s["segment"] for s in view["segments"]] == [1] and view["segments"][0]["routed_by"] == "explicit"
    speakers = [(line["segment"], line["speaker"]) for line in view["transcript"]]
    assert speakers[0] == (1, "agent") and (1, "caller") in speakers
    assert all(line["speaker"] in ("caller", "agent", "front_desk") for line in view["transcript"]) and "copay" in view["transcript"][-1]["text"]
    assert "transcript" not in (await client.get(f"/v1/tenants/evergreen-care/conversations/{cid}", headers=bearer(key))).json()


async def test_conversations_isolated_and_studio_listing(client, seeded, fake_llm):
    """Covers: MT-15, API-12"""
    fake_llm(script())
    key = await new_key(client)
    api_cid = (await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key),
                                 json={"channel": "text", "agent_id": seeded["care"]["agent_id"]})).json()["conversation_id"]
    r = await client.post("/api/conversations", headers=H, json={"scope": "member", "channel": "text", "agent_id": seeded["care"]["agent_id"]})
    assert r.status_code == 201
    play = r.json()["conversation_id"]
    listed = (await client.get("/api/conversations?source=playground", headers=H)).json()["items"]
    assert [c["id"] for c in listed] == [play]
    segs = (await client.get(f"/api/calls?conversation_id={play}", headers=H)).json()["items"]
    assert len(segs) == 1 and segs[0]["segment"] == 1 and segs[0]["routed_by"] == "explicit" and segs[0]["conversation_id"] == play
    # another tenant's Studio and keys see nothing of tenant A
    assert (await client.get(f"/api/conversations/{play}", headers=SANDBOX)).status_code == 404
    assert (await client.get("/api/conversations", headers=SANDBOX)).json()["items"] == []
    sandbox_key = await new_key(client, headers=SANDBOX)
    assert (await client.get(f"/v1/tenants/evergreen-sandbox/conversations/{api_cid}", headers=bearer(sandbox_key))).status_code == 404
    # a key never sees playground conversations
    assert (await client.get(f"/v1/tenants/evergreen-care/conversations/{play}", headers=bearer(key))).status_code == 404


async def test_unconnected_voice_conversation_is_abandoned(client, seeded, monkeypatch):
    """Covers: PUB-07"""
    monkeypatch.setenv("PUBLIC_API_SECRET", "s3cret")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    from voiceai import conversations
    from voiceai.config import get_settings

    get_settings.cache_clear()
    try:
        key = await new_key(client)
        cid = (await client.post("/v1/tenants/evergreen-care/conversations", headers=bearer(key),
                                 json={"channel": "voice", "agent_id": seeded["care"]["agent_id"]})).json()["conversation_id"]
        async with sessionmaker()() as s:
            await s.execute(update(Conversation).where(Conversation.id == cid).values(started_at=utcnow() - timedelta(minutes=5)))
            await s.commit()
        assert await conversations.expire_unconnected() == 1
        view = (await client.get(f"/v1/tenants/evergreen-care/conversations/{cid}", headers=bearer(key))).json()
        assert view["status"] == "ended" and view["end_reason"] == "idle" and view["outcome"] == "abandoned"
    finally:
        get_settings.cache_clear()


async def test_calls_gain_conversation_columns(tmp_path):
    """Covers: DM-10"""
    from sqlalchemy import inspect, text

    from voiceai import db

    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), industry VARCHAR(100), created_at DATETIME)")
        await conn.exec_driver_sql("CREATE TABLE calls (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), "
                                   "agent_id VARCHAR(32), agent_version_id VARCHAR(32), channel VARCHAR(16), meta JSON)")
        await conn.exec_driver_sql("INSERT INTO tenants VALUES ('t', 'T', '', '2026-10-01 00:00:00')")
        await conn.exec_driver_sql("INSERT INTO calls VALUES ('c1', 't', 'a', 'v', 'text', '{}')")
    await db.init_db()
    async with db.engine().begin() as conn:
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("calls")})
        assert {"conversation_id", "segment", "routed_by"} <= cols
        assert (await conn.execute(text("SELECT id, conversation_id FROM calls"))).one() == ("c1", None)
    await db.engine().dispose()
