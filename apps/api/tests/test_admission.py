"""Call admission: one decision for POST /api/calls, the voice socket and the Twilio webhook.

Covers: ADM-01, ADM-02, ADM-03, ADM-04, ADM-05
"""
from __future__ import annotations

import itertools
import sqlite3

import pytest
from starlette.websockets import WebSocketDisconnect

from tests.test_telephony import H, call_params, not_in_service, phone, signed_post, stream_of  # noqa: F401  (fixture)
from voiceai import admission, tenant_settings, vault
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.llm.gateway import reset_gateway
from voiceai.models import TenantSettings

TENANT = "evergreen-care"
OWN_KEY = "sk-tenant-0123456789abcdef"


def env(monkeypatch, **values: str) -> None:  # noqa: ANN001
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    reset_gateway()


@pytest.fixture
def vault_key(monkeypatch):  # noqa: ANN001, ANN201
    env(monkeypatch, TENANT_SECRETS_KEY=vault.generate_key())
    yield
    get_settings.cache_clear()
    reset_gateway()


CASES = list(itertools.product(
    (["cascade"], ["cascade", "realtime"]),          # allowlist
    ("cascade", "realtime"),                          # pipeline
    (True, False),                                    # Deepgram key
    (True, False),                                    # tenant's own OpenAI key
    ("on", "off", "unset"),                           # platform OpenAI key with fallback
))


@pytest.mark.parametrize("allowed,pipeline,deepgram,own,platform", CASES)
async def test_the_decision_table(database, vault_key, monkeypatch, allowed, pipeline, deepgram, own, platform):
    """Covers: ADM-01"""
    from voiceai.models import Tenant

    env(monkeypatch, DEEPGRAM_API_KEY="dg-test" if deepgram else "", OPENAI_API_KEY="" if platform == "unset" else "sk-platform-000000000000")
    async with sessionmaker()() as s:
        s.add(Tenant(id=TENANT, name="Care", industry=""))
        s.add(TenantSettings(tenant_id=TENANT, allowed_pipelines=allowed, openai_platform_fallback=platform != "off"))
        if own:
            await tenant_settings.set_openai_key(s, TENANT, OWN_KEY)
        await s.commit()
        decided = await admission.admit(s, TENANT, {"voice": {"pipeline": pipeline}})

    if pipeline not in allowed:
        assert decided == admission.Refusal("pipeline_not_allowed")
    elif pipeline == "cascade":
        assert decided == (admission.CallPlan("cascade", "platform") if deepgram else admission.Refusal("voice_unavailable"))
    elif own:
        assert isinstance(decided, admission.CallPlan) and decided.credential_source == "tenant" and decided.model_ref
    elif platform == "on":
        assert isinstance(decided, admission.CallPlan) and decided.credential_source == "platform"
    else:
        assert decided == admission.Refusal("voice_unavailable")
    if isinstance(decided, admission.CallPlan):
        assert OWN_KEY not in str(decided.to_meta()) and "sk-platform" not in str(decided.to_meta())


async def test_no_usable_key_refuses_before_a_call_exists(client, seeded):
    """Covers: ADM-02"""
    from sqlalchemy import func, select

    from voiceai.models import Call

    async with sessionmaker()() as s:
        before = await s.scalar(select(func.count()).select_from(Call))
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["claims"]["agent_id"], "channel": "voice"})
    assert r.status_code == 409 and r.json()["error"] == "voice_unavailable"
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Call)) == before
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["claims"]["agent_id"], "channel": "text"})
    assert r.status_code == 200


def sql(phone, statement: str, *args) -> None:  # noqa: ANN001
    con = sqlite3.connect(phone.db)
    try:
        con.execute(statement, args)
        con.commit()
    finally:
        con.close()


def socket_code(client, call_id: str) -> tuple[int, str]:  # noqa: ANN001
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect(f"/api/voice/{call_id}?tenant={TENANT}") as ws:
            ws.receive_text()
    return exc.value.code, exc.value.reason


@pytest.mark.parametrize("reason", ["pipeline_not_allowed", "voice_unavailable"])
def test_every_path_refuses_alike(phone, reason):
    """Covers: ADM-03"""
    c = phone.client
    claims = phone.agents["Insurance Claims Agent"]
    earlier = c.post("/api/calls", headers=H, json={"agent_id": claims, "channel": "voice"}).json()["call_id"]  # admitted now
    if reason == "pipeline_not_allowed":
        sql(phone, "update tenant_settings set allowed_pipelines=? where tenant_id=?", '["cascade"]', TENANT)
    else:
        sql(phone, "update tenant_settings set openai_platform_fallback=0 where tenant_id=?", TENANT)  # no own key either
    r = c.post("/api/calls", headers=H, json={"agent_id": claims, "channel": "voice"})
    assert r.status_code == 409 and r.json()["error"] == reason
    assert not_in_service(signed_post(c, call_params()))
    assert socket_code(c, earlier) == (4500, reason)


def test_a_planned_tenant_key_never_falls_back(phone, monkeypatch):
    """Covers: ADM-04"""
    from voiceai.voice import realtime as rt

    env(monkeypatch, TENANT_SECRETS_KEY=vault.generate_key())
    attempts: list[str] = []

    async def fake_connect(api_key, model_ref):  # noqa: ANN001, ANN202
        attempts.append(api_key)
        raise rt.ProviderUnavailable("test")

    monkeypatch.setattr(rt, "connect_openai", fake_connect)
    c = phone.client
    assert c.put("/api/tenant-settings/openai-key", headers=H, json={"api_key": OWN_KEY}).status_code == 200
    call_id = c.post("/api/calls", headers=H, json={"agent_id": phone.agents["Insurance Claims Agent"], "channel": "voice"}).json()["call_id"]
    assert c.get(f"/api/calls/{call_id}", headers=H).json()["settings"]["openai_key_source"] == "tenant"
    assert c.delete("/api/tenant-settings/openai-key", headers=H).status_code == 204  # platform fallback is on
    assert socket_code(c, call_id) == (4500, "voice_unavailable") and attempts == []


def test_the_source_is_chosen_once_per_call(phone, monkeypatch):
    """Covers: ADM-05"""
    from voiceai.voice import pipeline
    from voiceai.voice import realtime as rt

    env(monkeypatch, TENANT_SECRETS_KEY=vault.generate_key())
    used: list[str] = []

    async def fake_realtime(websocket, session, controls, connector, phone=None):  # noqa: ANN001, ANN202
        try:
            await connector()
        except rt.ProviderUnavailable:
            pass
        await websocket.close(code=1000)

    async def fake_connect(api_key, model_ref):  # noqa: ANN001, ANN202
        used.append(api_key)
        raise rt.ProviderUnavailable("test")

    monkeypatch.setattr(pipeline, "run_realtime", fake_realtime)
    monkeypatch.setattr(rt, "connect_openai", fake_connect)
    c = phone.client
    _, call_id = stream_of(signed_post(c, call_params()).text)            # admitted by the webhook on the platform key
    assert c.get(f"/api/calls/{call_id}", headers=H).json()["settings"]["openai_key_source"] == "platform"
    assert c.put("/api/tenant-settings/openai-key", headers=H, json={"api_key": OWN_KEY}).status_code == 200
    with c.websocket_connect(f"/api/voice/{call_id}?tenant={TENANT}") as ws:  # same serve_voice as the Twilio stream
        with pytest.raises(WebSocketDisconnect):
            ws.receive_text()
    assert used == ["sk-test"]                                            # still the platform key
