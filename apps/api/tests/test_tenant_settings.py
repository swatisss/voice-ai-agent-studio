"""Tenant settings: realtime pipeline allowlist and the tenant's own OpenAI key.

Covers: MT-05, MT-06, MT-07, MT-08, MT-09, MT-10, MT-11, MT-12, RV-16, UC-06, TEL-03
"""
from __future__ import annotations

import logging

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from tests.test_telephony import H as PHONE_H, call_params, not_in_service, phone, signed_post  # noqa: F401  (fixture)
from voiceai import tenant_settings as ts
from voiceai import vault
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.llm.gateway import reset_gateway
from voiceai.models import CallEvent, TenantCredential, TenantSettings

CARE = {"X-Tenant-Id": "evergreen-care"}
SANDBOX = {"X-Tenant-Id": "evergreen-sandbox"}
KEY = "sk-test-0123456789abcdefwxyz"


@pytest.fixture
def secrets_key(monkeypatch):  # noqa: ANN001, ANN201
    key = vault.generate_key()
    monkeypatch.setenv("TENANT_SECRETS_KEY", key)
    get_settings.cache_clear()
    yield key
    get_settings.cache_clear()


def realtime(cfg: dict) -> dict:
    return {**cfg, "voice": {**cfg["voice"], "pipeline": "realtime"}}


async def set_allowed(tenant_id: str, allowed: list[str]) -> None:
    """Change the allowlist directly, bypassing the in-use check (MT-08 setup)."""
    async with sessionmaker()() as s:
        row = await s.get(TenantSettings, tenant_id)
        if row is None:
            s.add(TenantSettings(tenant_id=tenant_id, allowed_pipelines=allowed, openai_platform_fallback=True))
        else:
            row.allowed_pipelines = allowed
        await s.commit()


async def test_defaults_and_seeded_settings(client, seeded):
    """Covers: MT-05, UC-06"""
    sandbox = (await client.get("/api/tenant-settings", headers=SANDBOX)).json()
    assert sandbox == {"allowed_pipelines": ["cascade"],
                       "openai": {"key_set": False, "key_last4": None, "key_updated_at": None, "platform_fallback": True}}
    care = (await client.get("/api/tenant-settings", headers=CARE)).json()
    assert care["allowed_pipelines"] == ["cascade", "realtime"] and care["openai"]["platform_fallback"] is True
    assert care["openai"]["key_set"] is False
    async with sessionmaker()() as s:
        assert await s.get(TenantSettings, "evergreen-sandbox") is None


async def test_realtime_needs_the_tenant_to_allow_it(client, seeded):
    """Covers: MT-06"""
    agent = (await client.post("/api/agents", headers=SANDBOX, json={"name": "Benefits pilot"})).json()
    cfg = realtime(agent["draft_config"])
    r = await client.put(f"/api/agents/{agent['id']}", headers=SANDBOX, json={"draft_config": cfg})
    assert r.status_code == 422 and r.json()["error"] == "pipeline_not_allowed"
    r = await client.post("/api/agents", headers=SANDBOX, json={"name": "Other", "draft_config": cfg})
    assert r.status_code == 422 and r.json()["error"] == "pipeline_not_allowed"
    assert (await client.get(f"/api/agents/{agent['id']}", headers=SANDBOX)).json()["draft_config"]["voice"]["pipeline"] == "cascade"

    assert (await client.put("/api/tenant-settings", headers=SANDBOX, json={"allowed_pipelines": ["cascade", "realtime"]})).status_code == 200
    assert (await client.put(f"/api/agents/{agent['id']}", headers=SANDBOX, json={"draft_config": cfg})).status_code == 200
    await set_allowed("evergreen-sandbox", ["cascade"])  # a draft saved earlier cannot be published once disallowed
    r = await client.post(f"/api/agents/{agent['id']}/publish", headers=SANDBOX, json={})
    assert r.status_code == 422 and r.json()["error"] == "pipeline_not_allowed"
    await set_allowed("evergreen-sandbox", ["cascade", "realtime"])
    assert (await client.post(f"/api/agents/{agent['id']}/publish", headers=SANDBOX, json={})).status_code == 200


async def test_allowlist_validation_and_pipeline_in_use(client, seeded):
    """Covers: MT-07"""
    for bad in ([], ["realtime"], ["cascade", "telepathy"]):
        assert (await client.put("/api/tenant-settings", headers=CARE, json={"allowed_pipelines": bad})).status_code == 422
    r = await client.put("/api/tenant-settings", headers=CARE, json={"allowed_pipelines": ["cascade"]})
    assert r.status_code == 409 and r.json()["error"] == "pipeline_in_use" and "Insurance Claims Agent" in r.json()["detail"]
    assert (await client.get("/api/tenant-settings", headers=CARE)).json()["allowed_pipelines"] == ["cascade", "realtime"]
    r = await client.put("/api/tenant-settings", headers=CARE, json={"openai_platform_fallback": False})
    assert r.status_code == 200 and r.json()["openai"]["platform_fallback"] is False


async def test_a_disallowed_pipeline_refuses_voice_calls_but_not_text(client, seeded):
    """Covers: MT-08"""
    claims = seeded["claims"]["agent_id"]
    await set_allowed("evergreen-care", ["cascade"])
    r = await client.post("/api/calls", headers=CARE, json={"agent_id": claims, "channel": "voice"})
    assert r.status_code == 409 and r.json()["error"] == "pipeline_not_allowed"
    r = await client.post("/api/calls", headers=CARE, json={"agent_id": claims, "channel": "text"})
    assert r.status_code == 200 and r.json()["greeting"]


def test_a_disallowed_pipeline_closes_the_voice_socket(phone):
    """Covers: MT-08"""
    import sqlite3

    claims = phone.agents["Insurance Claims Agent"]
    call_id = phone.client.post("/api/calls", headers=PHONE_H, json={"agent_id": claims, "channel": "voice"}).json()["call_id"]
    con = sqlite3.connect(phone.db)
    con.execute("update tenant_settings set allowed_pipelines=? where tenant_id='evergreen-care'", ('["cascade"]',))
    con.commit()
    con.close()
    with pytest.raises(WebSocketDisconnect) as exc:
        with phone.client.websocket_connect(f"/api/voice/{call_id}?tenant=evergreen-care") as ws:
            ws.receive_text()
    assert exc.value.code == 4500 and exc.value.reason == "pipeline_not_allowed"
    before = con_count(phone)
    assert not_in_service(signed_post(phone.client, call_params()))  # TEL-03: the phone line answers "not in service"
    assert con_count(phone) == before


def con_count(phone) -> int:  # noqa: ANN001
    import sqlite3

    con = sqlite3.connect(phone.db)
    try:
        return con.execute("select count(*) from calls").fetchone()[0]
    finally:
        con.close()


async def test_the_key_is_write_only_and_encrypted(client, seeded, secrets_key, caplog):
    """Covers: MT-09"""
    caplog.set_level(logging.DEBUG)
    r = await client.put("/api/tenant-settings/openai-key", headers=CARE, json={"api_key": KEY})
    assert r.status_code == 200 and r.json()["key_set"] is True and r.json()["key_last4"] == "wxyz"
    assert KEY not in r.text
    got = await client.get("/api/tenant-settings", headers=CARE)
    assert got.json()["openai"]["key_last4"] == "wxyz" and KEY not in got.text
    async with sessionmaker()() as s:
        cred = (await s.scalars(select(TenantCredential))).one()
        assert KEY not in cred.ciphertext and vault.decrypt(cred.ciphertext) == KEY
        assert not any(KEY in (e.text or "") or KEY in str(e.data) for e in (await s.scalars(select(CallEvent))).all())
    assert KEY not in caplog.text
    r = await client.put("/api/tenant-settings/openai-key", headers=CARE, json={"api_key": "pk-" + KEY[3:]})
    assert r.status_code == 422 and r.json()["error"] == "invalid_key" and KEY[3:] not in r.text
    assert (await client.delete("/api/tenant-settings/openai-key", headers=CARE)).status_code == 204
    assert (await client.get("/api/tenant-settings", headers=CARE)).json()["openai"]["key_set"] is False


async def test_key_storage_needs_the_secrets_key(client, seeded, monkeypatch):
    """Covers: MT-10"""
    r = await client.put("/api/tenant-settings/openai-key", headers=CARE, json={"api_key": KEY})
    assert r.status_code == 503 and r.json()["error"] == "secrets_unavailable"
    monkeypatch.setenv("TENANT_SECRETS_KEY", vault.generate_key())
    get_settings.cache_clear()
    assert (await client.put("/api/tenant-settings/openai-key", headers=CARE, json={"api_key": KEY})).status_code == 200
    monkeypatch.setenv("TENANT_SECRETS_KEY", vault.generate_key())  # a different vault key: the stored key is unreadable
    get_settings.cache_clear()
    assert (await client.get("/api/tenant-settings", headers=CARE)).json()["openai"]["key_set"] is False
    async with sessionmaker()() as s:
        assert await ts.resolve_openai_key(s, "evergreen-care") is None  # no platform key in tests
    get_settings.cache_clear()


async def test_key_resolution_per_tenant(client, seeded, secrets_key, monkeypatch):
    """Covers: MT-11"""
    async with sessionmaker()() as s:
        assert await ts.resolve_openai_key(s, "evergreen-care") is None  # no own key, no platform key
    monkeypatch.setenv("OPENAI_API_KEY", "sk-platform-000000000000000")
    get_settings.cache_clear()
    reset_gateway()
    try:
        await client.put("/api/tenant-settings/openai-key", headers=CARE, json={"api_key": KEY})
        async with sessionmaker()() as s:
            assert await ts.resolve_openai_key(s, "evergreen-care") == (KEY, "tenant")
            assert await ts.resolve_openai_key(s, "evergreen-sandbox") == ("sk-platform-000000000000000", "platform")
        await client.put("/api/tenant-settings", headers=SANDBOX, json={"openai_platform_fallback": False})
        async with sessionmaker()() as s:
            assert await ts.resolve_openai_key(s, "evergreen-sandbox") is None  # never tenant A's key
    finally:
        monkeypatch.setenv("OPENAI_API_KEY", "")
        get_settings.cache_clear()
        reset_gateway()


def test_each_realtime_call_uses_its_tenants_key(phone, monkeypatch):
    """Covers: RV-16, MT-11"""
    from voiceai.voice import pipeline
    from voiceai.voice import realtime as rt

    monkeypatch.setenv("TENANT_SECRETS_KEY", vault.generate_key())
    get_settings.cache_clear()
    used: list[str] = []

    async def fake_connect(api_key, model_ref):  # noqa: ANN001, ANN202
        used.append(api_key)
        raise rt.ProviderUnavailable("test")

    async def fake_realtime(websocket, session, controls, connector, phone=None):  # noqa: ANN001, ANN202
        try:
            await connector()
        except rt.ProviderUnavailable:
            pass
        await websocket.close(code=1000)

    monkeypatch.setattr(rt, "connect_openai", fake_connect)
    monkeypatch.setattr(pipeline, "run_realtime", fake_realtime)
    c = phone.client
    claims = phone.agents["Insurance Claims Agent"]

    def call() -> str:
        call_id = c.post("/api/calls", headers=PHONE_H, json={"agent_id": claims, "channel": "voice"}).json()["call_id"]
        with c.websocket_connect(f"/api/voice/{call_id}?tenant=evergreen-care") as ws:
            try:
                ws.receive_text()
            except WebSocketDisconnect:
                pass
        return c.get(f"/api/calls/{call_id}", headers=PHONE_H).json()["settings"]["openai_key_source"]

    assert call() == "platform" and used == ["sk-test"]  # the fixture's platform key
    assert c.put("/api/tenant-settings/openai-key", headers=PHONE_H, json={"api_key": KEY}).status_code == 200
    assert call() == "tenant" and used[-1] == KEY


async def test_existing_realtime_tenants_are_grandfathered(client, seeded):
    """Covers: MT-12"""
    async with sessionmaker()() as s:
        await s.delete(await s.get(TenantSettings, "evergreen-care"))
        await s.commit()
    async with sessionmaker()() as s:
        assert await ts.grandfather(s) == ["evergreen-care"]
        await s.commit()
    async with sessionmaker()() as s:
        assert (await s.get(TenantSettings, "evergreen-care")).allowed_pipelines == ["cascade", "realtime"]
        assert await s.get(TenantSettings, "evergreen-sandbox") is None
        assert await ts.grandfather(s) == []
