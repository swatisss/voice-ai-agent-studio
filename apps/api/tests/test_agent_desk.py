"""CP-0047: the Agent Desk (specialist) role - allow-list, one business unit, escalated calls only, masking, pattern comments.

Covers: DESK-01, DESK-02, DESK-03, DESK-04, DESK-05, DESK-06, DESK-07, DESK-08, DESK-09, DESK-10, DESK-11, DM-16
"""
from __future__ import annotations

import logging
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select

from tests.test_learning_actions import _member, _new_cluster, _open, _quiet_seed_clusters
from tests.test_self_learning import H, _learning, _run_now, fake
from voiceai import auth, jobs, mask
from voiceai.config import get_settings
from voiceai.db import sessionmaker, utcnow
from voiceai.events import bus
from voiceai.models import Call, CallEvent, ClusterComment, Escalation

PW = {"admin": "admin-demo-pass", "reviewer": "reviewer-demo-pass", "specialist": "specialist-demo-pass"}
EMAILS = {"admin": auth.ADMIN.email, "reviewer": auth.REVIEWER.email, "specialist": auth.SPECIALIST.email}
SAID = "My member number is NGH-410237, email meera@example.com, phone 07700900123."


@pytest.fixture
def signin(monkeypatch):  # noqa: ANN001, ANN201
    def turn_on(**only: str) -> None:
        for who, pw in (only or PW).items():
            monkeypatch.setenv(f"STUDIO_{who.upper()}_PASSWORD", pw)
        get_settings.cache_clear()

    yield turn_on
    for who in PW:
        monkeypatch.delenv(f"STUDIO_{who.upper()}_PASSWORD", raising=False)
    get_settings.cache_clear()


async def _login(client, who: str) -> None:  # noqa: ANN001
    client.cookies.clear()
    r = await client.post("/api/auth/login", json={"email": EMAILS[who], "password": PW[who]})
    assert r.status_code == 200, r.text


async def _escalated(seeded, *, said: str = SAID, caller_ref: str | None = "NGH-410237") -> tuple[str, str]:  # noqa: ANN001
    """An ended call with an escalation, a transcript that carries identifiers and a packet with an entity; returns (call_id, escalation_id)."""
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    async with sessionmaker()() as s:
        call = await _member(s, agent_id, version_id, None, when=utcnow() - timedelta(hours=1))
        call.caller_ref = caller_ref
        s.add(CallEvent(tenant_id="northgate-health", call_id=call.id, seq=1, kind="user", text=said))
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call.id))
        esc.packet = {"summary": f"Caller says: {said}", "entities": {"member_ref": "NGH-410237"}}
        await s.commit()
        return call.id, esc.id


async def test_specialist_signs_in_with_their_own_password(client, seeded, signin):
    """Covers: DESK-01"""
    signin()
    bad = await client.post("/api/auth/login", json={"email": auth.SPECIALIST.email, "password": "nope"})
    assert bad.status_code == 401 and bad.json()["error"] == "bad_credentials"
    await _login(client, "specialist")
    me = (await client.get("/api/auth/me")).json()
    assert me["user"] == {"email": "specialist@echomind.test", "name": "Sam Specialist", "role": "specialist", "tenant_id": "northgate-health"}
    signin(admin=PW["admin"], reviewer="", specialist="")
    client.cookies.clear()
    assert (await client.post("/api/auth/login", json={"email": auth.SPECIALIST.email, "password": PW["specialist"]})).status_code == 401


async def test_everything_outside_the_desk_is_refused(client, seeded, signin):
    """Covers: DESK-02"""
    signin()
    await _login(client, "specialist")
    agent_id = seeded["care"]["agent_id"]
    refused = [
        client.get("/api/dashboard/summary", headers=H), client.get("/api/insights/inbox", headers=H),
        client.get(f"/api/agents/{agent_id}/checks", headers=H), client.put(f"/api/agents/{agent_id}", headers=H, json={"name": "x"}),
        client.post("/api/knowledge/text", headers=H, json={"title": "t", "content": "c"}), client.get("/api/tenant-settings/front-desk", headers=H),
        client.get("/api/members/NGH-410237/memory/export", headers=H),
        client.post("/api/calls", headers=H, json={"agent_id": agent_id, "channel": "text"}),
    ]
    for pending in refused:
        r = await pending
        assert r.status_code == 403 and r.json()["error"] == "role_forbidden", r.url
    assert (await client.get(f"/api/agents/{agent_id}", headers=H)).status_code == 200
    for ok in (client.get("/api/escalations", headers=H), client.get("/api/agents", headers=H), client.get("/api/knowledge", headers=H),
               client.post("/api/knowledge/search", headers=H, json={"query": "excess"}), client.get("/api/calls", headers=H),
               client.get("/api/insights/clusters", headers=H)):
        r = await ok
        assert r.status_code == 200, (r.url, r.text)
    assert (await client.get("/api/events?topics=insights", headers=H)).status_code == 403


async def test_one_business_unit(client, seeded, signin):
    """Covers: DESK-03"""
    signin()
    await _login(client, "specialist")
    other = await client.get("/api/escalations", headers={"X-Tenant-Id": "someone-else"})
    assert other.status_code == 403 and other.json()["error"] == "tenant_forbidden"
    assert (await client.get("/api/escalations")).status_code == 200  # no header: the account's own unit
    items = (await client.get("/api/tenants")).json()["items"]
    assert [t["id"] for t in items] == ["northgate-health"]
    await _login(client, "admin")
    assert len((await client.get("/api/tenants")).json()["items"]) >= 1


async def test_escalated_calls_only(client, seeded, signin):
    """Covers: DESK-04"""
    signin()
    call_id, _ = await _escalated(seeded)
    await _login(client, "admin")
    everything = {c["id"] for c in (await client.get("/api/calls", headers=H)).json()["items"]}
    await _login(client, "specialist")
    mine = {c["id"] for c in (await client.get("/api/calls", headers=H)).json()["items"]}
    assert call_id in mine and mine < everything
    plain = next(c for c in everything - mine)
    assert (await client.get(f"/api/calls/{plain}", headers=H)).status_code == 404
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    assert detail["id"] == call_id and "scorecard" not in detail and "llm_cost_usd" not in detail


async def test_identifiers_are_masked_for_the_specialist_only(client, seeded, signin):
    """Covers: DESK-05"""
    signin()
    call_id, esc_id = await _escalated(seeded)
    await _login(client, "specialist")
    for url in (f"/api/calls/{call_id}", f"/api/escalations/{esc_id}", "/api/escalations", "/api/calls"):
        body = (await client.get(url, headers=H)).text
        for raw in ("NGH-410237", "meera@example.com", "07700900123"):
            assert raw not in body, (url, raw)
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    text = next(e["text"] for e in detail["events"] if e["kind"] == "user")
    assert "NGH-•••237" in text and "m***@example.com" in text and "•••0123" in text
    assert detail["caller_ref"] == "NGH-•••237" and call_id in (await client.get("/api/calls", headers=H)).text  # ids are not masked
    await _login(client, "admin")
    raw = (await client.get(f"/api/calls/{call_id}", headers=H)).text
    assert "NGH-410237" in raw and "meera@example.com" in raw


def test_masking_rules():
    """Covers: DESK-05"""
    assert mask.member_ref("NGH-410237") == "NGH-•••237" and mask.email("meera@example.com") == "m***@example.com"
    assert mask.phone("+447700900123") == "•••0123"
    kept = "Claim CL-70231, authorisation PA-500955, policy PMI-310001, born 1966-11-30, call 05add28a35b047ab888dd9c66d729adb."
    assert mask.text(kept) == kept
    assert mask.text("ring +44 7700 900123 or 07700900123") == "ring •••0123 or •••0123"
    assert mask.text("") == ""


async def test_a_specialists_note_is_masked_before_it_is_stored(client, seeded, signin):
    """Covers: DESK-06"""
    signin()
    _, esc_id = await _escalated(seeded)
    await _login(client, "specialist")
    assert (await client.post(f"/api/escalations/{esc_id}/accept", headers=H, json={"assignee": "ignored"})).json()["assignee"] == "Sam Specialist"
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H,
                          json={"disposition": "resolved_by_human", "resolution_note": "Told NGH-410237 that cover continues for 30 days."})
    assert r.status_code == 200, r.text
    async with sessionmaker()() as s:
        note = (await s.get(Escalation, esc_id)).resolution_note
    assert "NGH-•••237" in note and "410237" not in note


async def test_logs_are_masked(client, seeded, caplog):
    """Covers: DESK-07"""
    with caplog.at_level(logging.INFO, logger="voiceai"):
        logging.getLogger("voiceai.desk_test").info("caller %s mail %s tel %s", "NGH-410237", "meera@example.com", "07700900123")
    assert "NGH-410237" not in caplog.text and "meera@example.com" not in caplog.text and "07700900123" not in caplog.text
    assert "NGH-•••237" in caplog.text


async def test_patterns_carry_no_cost_or_learning_internals(client, seeded, signin):
    """Covers: DESK-08"""
    signin()
    async with sessionmaker()() as s:
        c = await _new_cluster(s, seeded["care"]["agent_id"], seeded["care"]["version_id"], "Extending cover abroad", 5, note="Once, up to 30 days.")
        await s.commit()
        cluster_id = c.id
    await _login(client, "specialist")
    listed = next(i for i in (await client.get("/api/insights/clusters", headers=H)).json()["items"] if i["id"] == cluster_id)
    detail = (await client.get(f"/api/insights/clusters/{cluster_id}", headers=H)).json()
    for view in (listed, detail):
        assert not {"est_weekly_cost_usd", "weekly_escalations", "proposals", "dislike_count"} & view.keys()
    assert listed["signal_count"] == 5 and detail["calls"] and all(m["outcome"] == "escalated" for m in detail["calls"])
    assert any(m["resolution_note"] == "Once, up to 30 days." for m in detail["calls"])
    await _login(client, "admin")
    full = (await client.get(f"/api/insights/clusters/{cluster_id}", headers=H)).json()
    assert "est_weekly_cost_usd" in full and "proposals" in full


async def test_comments_are_stored_masked_with_the_authors_role(client, seeded, signin):
    """Covers: DESK-09, DM-16"""
    signin()
    async with sessionmaker()() as s:
        c = await _new_cluster(s, seeded["care"]["agent_id"], seeded["care"]["version_id"], "Extending cover abroad", 5)
        await s.commit()
        cid = c.id
    url = f"/api/insights/clusters/{cid}/comments"
    sub = bus.subscribe("northgate-health", {"insights"})
    await _login(client, "specialist")
    short = await client.post(url, headers=H, json={"text": "too short"})
    assert short.status_code == 422 and short.json()["error"] == "comment_too_short"
    assert (await client.post(url, headers=H, json={"text": "x" * 1001})).json()["error"] == "comment_too_long"
    text = "Tell them cover can be extended once, by up to 30 days. Member NGH-410237 asked."
    r = await client.post(url, headers=H, json={"text": text})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["author"] == "Sam Specialist" and got["author_role"] == "specialist" and "410237" not in got["text"]
    events = []
    while not sub.queue.empty():
        events.append(sub.queue.get_nowait())
    bus.unsubscribe(sub)
    assert any(e["type"] == "cluster.updated" and e["data"]["id"] == cid for e in events)
    await _login(client, "admin")
    assert (await client.post(url, headers=H, json={"text": "Admin adds a second comment here."})).json()["author_role"] == "admin"
    await _login(client, "reviewer")
    assert (await client.post(url, headers=H, json={"text": "Riley agrees with the first one."})).json()["author"] == "Riley Reviewer"
    listed = (await client.get(url, headers=H)).json()["items"]
    assert [c["author_role"] for c in listed] == ["specialist", "admin", "reviewer"]
    async with sessionmaker()() as s:
        assert "ix_cluster_comments_cluster_id" in {i["name"] for i in await (await s.connection()).run_sync(lambda c: inspect(c).get_indexes("cluster_comments"))}
        assert all("410237" not in row.text for row in (await s.scalars(select(ClusterComment))).all())


async def test_a_comment_is_a_persons_answer_and_evidence(client, seeded, fake_llm, signin):
    """Covers: DESK-10"""
    seen: dict[str, list[str]] = {}
    fake_llm(fake(seen=seen))
    await _learning(seeded, max_proposals_per_night=0)
    await _quiet_seed_clusters(seeded)
    async with sessionmaker()() as s:
        silent = await _new_cluster(s, seeded["care"]["agent_id"], seeded["care"]["version_id"], "Extending cover abroad", 5)
        await s.commit()
        cid = silent.id
    await _run_now(client)
    assert await _open("answer_needed", cid)
    signin()
    await _login(client, "specialist")
    url = f"/api/insights/clusters/{cid}/comments"
    before = (await client.get(f"/api/insights/clusters/{cid}", headers=H)).json()
    assert before["needs_answer"] is True
    short = await client.post(url, headers=H, json={"text": "Fifteen chars.."})  # stored, but under the 20-character bar
    assert short.status_code == 200
    assert (await client.get(f"/api/insights/clusters/{cid}", headers=H)).json()["needs_answer"] is True
    assert await _open("answer_needed", cid)
    signals = before["signal_count"]
    answer = "Cover can be extended once while abroad, by up to 30 days."
    assert (await client.post(url, headers=H, json={"text": answer})).status_code == 200
    after = (await client.get(f"/api/insights/clusters/{cid}", headers=H)).json()
    assert after["needs_answer"] is False and after["signal_count"] == signals
    assert not await _open("answer_needed", cid)
    await _login(client, "admin")
    r = await client.post(f"/api/insights/clusters/{cid}/draft-fix", headers=H)
    assert r.status_code == 200, r.text
    await jobs.drain()
    assert any(f"Specialist comment (Sam Specialist): {answer}" in p for p in seen["drafting"])


async def test_builders_can_still_work_the_console_through_the_api(client, seeded, signin):
    """Covers: DESK-11"""
    signin()
    _, esc_id = await _escalated(seeded)
    await _login(client, "reviewer")
    assert (await client.post(f"/api/escalations/{esc_id}/accept", headers=H, json={"assignee": "x"})).status_code == 200
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "resolved_by_human", "resolution_note": "Told her NGH-410237 is fine."})
    assert r.status_code == 200
    async with sessionmaker()() as s:
        assert "NGH-410237" in (await s.get(Escalation, esc_id)).resolution_note  # only the specialist's own writing is masked


async def test_only_one_specialist_wins_a_simultaneous_accept(client, seeded, signin):
    """Covers: ES-06, DESK-11"""
    import asyncio

    signin()
    _, esc_id = await _escalated(seeded)
    await _login(client, "specialist")
    rs = await asyncio.gather(*[client.post(f"/api/escalations/{esc_id}/accept", headers=H, json={"assignee": "x"}) for _ in range(6)])
    codes = sorted(r.status_code for r in rs)
    assert codes == [200] + [409] * 5, codes
    async with sessionmaker()() as s:
        assert (await s.get(Escalation, esc_id)).assignee == "Sam Specialist"


def test_timestamps_survive_masking():
    """Covers: DESK-05"""
    stamps = ["2026-11-16T15:34:17.123276+00:00", "2026-11-16T15:34:17+00:00", "2026-11-16 15:34:17.123456", "2026-11-16T15:34:17.123276Z"]
    for ts in stamps:
        assert mask.text(ts) == ts and mask.walk({"at": ts, "n": [ts]}) == {"at": ts, "n": [ts]}
    assert mask.text(f"started {stamps[0]}, member NGH-410237") == f"started {stamps[0]}, member NGH-\u2022\u2022\u2022237"
    assert mask.text("cost 0.123456 usd") == "cost 0.123456 usd"
