"""Studio sign-in: the guard, the session cookie, admin-only requests, who is recorded, sign-in off.

Covers: AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06, AUTH-07, DM-14
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from sqlalchemy import inspect, select, text

from tests.test_escalation_console import _escalated_call
from tests.test_learning_actions import _check, _new_cluster, _scored
from tests.test_self_learning import H, _ready_proposal
from voiceai import auth, db
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.models import AgentVersion, Cluster, FixProposal, LearningAction

ADMIN_PW, REVIEWER_PW = "admin-demo-pass", "reviewer-demo-pass"


@pytest.fixture
def signin(monkeypatch):  # noqa: ANN001, ANN201
    def turn_on(admin: str = ADMIN_PW, reviewer: str = REVIEWER_PW) -> None:
        monkeypatch.setenv("STUDIO_ADMIN_PASSWORD", admin)
        monkeypatch.setenv("STUDIO_REVIEWER_PASSWORD", reviewer)
        get_settings.cache_clear()

    yield turn_on
    monkeypatch.delenv("STUDIO_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("STUDIO_REVIEWER_PASSWORD", raising=False)
    get_settings.cache_clear()


async def _login(client, who: str) -> None:  # noqa: ANN001
    email, pw = (auth.ADMIN.email, ADMIN_PW) if who == "admin" else (auth.REVIEWER.email, REVIEWER_PW)
    client.cookies.clear()
    r = await client.post("/api/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text


async def test_guard_needs_a_session_but_not_for_health_phone_or_v1(client, seeded, signin):
    """Covers: AUTH-01"""
    signin()
    r = await client.get("/api/agents", headers=H)
    assert r.status_code == 401 and r.json()["error"] == "login_required"
    assert (await client.get("/healthz")).status_code == 200
    assert (await client.get("/api/auth/me")).json() == {"enabled": True, "user": None}
    phone = await client.post("/api/telephony/twilio/voice", data={"To": "+15550100", "From": "+15550101", "CallSid": "CA1"})
    assert phone.status_code != 401
    await _login(client, "admin")
    key = (await client.post("/api/api-keys", headers=H, json={"name": "auth-test", "scope": "member"})).json()["key"]
    client.cookies.clear()
    r = await client.get("/v1/tenants/northgate-health/agents", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200, r.text


async def test_sign_in_cookie_logout_tamper_and_expiry(client, seeded, signin):
    """Covers: AUTH-02"""
    signin()
    bad = await client.post("/api/auth/login", json={"email": auth.REVIEWER.email, "password": "nope"})
    assert bad.status_code == 401 and bad.json()["error"] == "bad_credentials" and "set-cookie" not in bad.headers
    ok = await client.post("/api/auth/login", json={"email": auth.REVIEWER.email, "password": REVIEWER_PW})
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    me = (await client.get("/api/auth/me")).json()
    assert me["user"] == {"email": "reviewer@echomind.test", "name": "Riley Reviewer", "role": "reviewer"}
    assert (await client.get("/api/agents", headers=H)).status_code == 200
    token = client.cookies.get(auth.COOKIE)
    payload, mac = token.split(".")
    forged = auth._b64(auth._unb64(payload).replace(b'"reviewer"', b'"admin"')) + "." + mac
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, forged)
    assert (await client.get("/api/agents", headers=H)).status_code == 401
    assert auth.verify(token) == auth.REVIEWER
    assert auth.verify(token, now=time.time() + 13 * 3600) is None
    client.cookies.clear()
    client.cookies.set(auth.COOKIE, token)
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/agents", headers=H)).status_code == 401


async def test_reviewer_cannot_change_what_callers_hear(client, seeded, signin):
    """Covers: AUTH-03"""
    signin()
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the member portal."})
    agent_id = seeded["care"]["agent_id"]
    async with sessionmaker()() as s:
        before = len((await s.scalars(select(AgentVersion))).all())
    await _login(client, "reviewer")
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    refused = [
        await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "x"}),
        await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Riley"}),
        await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Riley", "force": True, "note": "ship it"}),
        await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft}),
        await client.post("/api/knowledge/text", headers=H, json={"title": "T", "content": "Body"}),
        await client.put("/api/tenant-settings", headers=H, json={"allowed_pipelines": ["cascade"]}),
        await client.post("/api/members/NGH-410237/memory/erase", headers=H, json={}),
    ]
    assert [r.status_code for r in refused] == [403] * len(refused)
    assert all(r.json()["error"] == "admin_required" for r in refused)
    async with sessionmaker()() as s:
        assert len((await s.scalars(select(AgentVersion))).all()) == before
        assert (await s.get(FixProposal, pid)).status == "ready"
    assert (await client.post("/api/knowledge/search", headers=H, json={"query": "newborn"})).status_code != 403


async def test_reviewer_does_the_human_in_the_loop_work(client, seeded, fake_llm, signin):
    """Covers: AUTH-04"""
    signin()
    await _login(client, "reviewer")
    call_id, _ = await _escalated_call(client, seeded, fake_llm, lambda: None)
    async with sessionmaker()() as s:
        from voiceai.models import Escalation

        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
    assert (await client.post(f"/api/escalations/{esc.id}/accept", headers=H, json={"assignee": "x"})).status_code == 200
    r = await client.post(f"/api/escalations/{esc.id}/resolve", headers=H, json={"disposition": "appeal_filed", "resolution_note": "Explained the appeal steps."})
    assert r.status_code == 200, r.text
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    async with sessionmaker()() as s:
        _, card = await _scored(s, agent_id, version_id, [_check("knowledge.grounded", "fail", "judge")])
        cluster = await _new_cluster(s, agent_id, version_id, "Extending cover abroad", 3)
        action = LearningAction(tenant_id="northgate-health", agent_id=agent_id, kind="answer_needed", key=f"answer_needed:{cluster.id}",
                                severity="high", title="Answer needed", evidence={"cluster_id": cluster.id})
        s.add(action)
        await s.commit()
        card_id, action_id = card.id, action.id
    r = await client.put(f"/api/scorecards/{card_id}/reviews/knowledge.grounded", headers=H, json={"verdict": "pass", "reviewer": "Someone"})
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/actions/{action_id}/answer", headers=H, json={"answer": "Extend once while abroad, by up to 30 days.", "by": "x"})
    assert r.status_code == 200, r.text
    assert (await client.post("/api/learning/run", headers=H)).status_code == 200
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the member portal."})
    assert (await client.post(f"/api/proposals/{pid}/reject", headers=H, json={"decided_by": "x", "note": "Not needed"})).status_code == 200
    assert (await client.post("/api/calls", headers=H, json={"agent_id": agent_id, "channel": "text"})).status_code == 200
    async with sessionmaker()() as s:
        assert (await s.get(LearningAction, action_id)).closed_by == "Riley Reviewer"
        assert (await s.get(Cluster, cluster.id)).human_answer_by == "Riley Reviewer"
        assert (await s.get(FixProposal, pid)).decided_by == "Riley Reviewer"
        assert (await s.get(Escalation, esc.id)).assignee == "Riley Reviewer"


async def test_admin_approval_records_the_signed_in_admin(client, seeded, signin):
    """Covers: AUTH-05"""
    signin()
    await _login(client, "admin")
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the member portal."})
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Someone Else"})
    assert r.status_code == 200, r.text
    agent_id = seeded["care"]["agent_id"]
    built = await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={"change_note": "builder"})
    async with sessionmaker()() as s:
        assert (await s.get(FixProposal, pid)).decided_by == "Alex Admin"
        assert (await s.get(AgentVersion, r.json()["version"]["id"])).published_by == "Alex Admin"
        assert (await s.get(AgentVersion, built.json()["id"])).published_by == "Alex Admin"
        _, card = await _scored(s, agent_id, seeded["care"]["version_id"], [_check("knowledge.grounded", "fail", "judge")])
        await s.commit()
    await _login(client, "reviewer")
    r = await client.put(f"/api/scorecards/{card.id}/reviews/knowledge.grounded", headers=H, json={"verdict": "pass", "reviewer": "Pat"})
    assert r.json()["reviewer"] == "Riley Reviewer"


async def test_sign_in_off_works_as_before(client, seeded):
    """Covers: AUTH-06"""
    assert (await client.get("/api/auth/me")).json() == {"enabled": False, "user": {"email": "", "name": "Studio", "role": "admin"}}
    pid = await _ready_proposal(seeded, "policy_rule", {"rule": "Offer the member portal."})
    r = await client.post(f"/api/proposals/{pid}/approve", headers=H, json={"decided_by": "Dana"})
    assert r.status_code == 200, r.text
    async with sessionmaker()() as s:
        assert (await s.get(FixProposal, pid)).decided_by == "Dana"
        assert (await s.get(AgentVersion, r.json()["version"]["id"])).published_by == "Studio"
        seeded_version = await s.get(AgentVersion, seeded["care"]["version_id"])
        assert seeded_version.published_by is None  # the seeder publishes outside a request


async def test_account_without_password_cannot_sign_in(client, seeded, signin):
    """Covers: AUTH-07"""
    signin(admin="")
    for pw in ("", ADMIN_PW, "anything"):
        r = await client.post("/api/auth/login", json={"email": auth.ADMIN.email, "password": pw})
        assert r.status_code == 401 and r.json()["error"] == "bad_credentials"


async def test_old_database_gains_published_by(tmp_path: Path):
    """Covers: DM-14"""
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), industry VARCHAR(100), created_at DATETIME)")
        await conn.exec_driver_sql(
            "CREATE TABLE agent_versions (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), agent_id VARCHAR(32), "
            "version INTEGER, config JSON, change_note TEXT, source_proposal_id VARCHAR(32), created_at DATETIME NOT NULL)")
        await conn.exec_driver_sql("INSERT INTO tenants VALUES ('t', 'T', '', '2026-10-01 00:00:00')")
        await conn.exec_driver_sql("INSERT INTO agent_versions VALUES ('v1', 't', 'a', 1, '{}', 'Initial', NULL, '2026-10-01 00:00:00')")
    await db.init_db()
    async with db.engine().begin() as conn:
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("agent_versions")})
        assert "published_by" in cols
        assert (await conn.execute(text("SELECT version, change_note, published_by FROM agent_versions"))).one() == (1, "Initial", None)
    await db.engine().dispose()
