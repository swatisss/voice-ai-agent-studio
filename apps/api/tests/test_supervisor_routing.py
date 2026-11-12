"""Supervisor routing and the front desk: two stages, decision targets with failover, PHI mode, clarification, scopes,
routed voice and phone conversations, the routing trace, settings, health and the routing suite.

Covers: RTE-01, RTE-02, RTE-03, RTE-04, RTE-05, RTE-06, RTE-07, RTE-08, RTE-09, RTE-10, RTE-11, RTE-12, RTE-13, RTE-14, RTE-15,
RTE-16, RTE-17, LG-14, MT-16, API-13, TEL-12, DEP-05, PUB-03, PUB-05, CAT-07, CAT-09
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from tests.test_capability_catalog import run_index_jobs
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.events import bus
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, Conversation
from voiceai.public import auth
from voiceai.routing import catalog, decision, supervisor

H = {"X-Tenant-Id": "northgate-health"}
CLAIM = "My GP has referred me to a specialist."  # a Claims & Pre-authorisation sample utterance: a clear Stage A win


class Brain:
    """One fake LLM for every role: drafting writes utterances, router decides or asks, realtime answers."""

    def __init__(self) -> None:
        self.router: list[Any] = []      # queued router replies (dict for a decision or a question)
        self.realtime: list[str] = []
        self.calls: dict[str, int] = {}

    def __call__(self, role: str, messages: list[dict[str, Any]], tools: Any) -> Any:
        self.calls[role] = self.calls.get(role, 0) + 1
        text = messages[-1]["content"] if messages else ""
        if role == "drafting":
            purpose = "test" if "Purpose: test" in text else "index"
            return {"utterances": [f"{purpose} request {uuid.uuid4().hex[:6]}" for _ in range(3 if purpose == "test" else 12)]}
        if role == "router":
            if not self.router:
                raise RuntimeError("router unavailable")
            reply = self.router.pop(0)
            if isinstance(reply, Exception):
                raise reply
            return reply
        if role == "realtime":
            return FakeReply(text=self.realtime.pop(0) if self.realtime else "Happy to help with that.")
        raise RuntimeError(f"unexpected role {role}")


class Model:
    """A fake Jev-compatible decision model. `answer` is the route answer, an HTTP status, or an exception."""

    def __init__(self) -> None:
        self.answer: Any = None
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.answer, Exception):
            raise self.answer
        if isinstance(self.answer, int) or self.answer is None:
            return httpx.Response(self.answer or 503)
        return httpx.Response(200, json={"model": "fake-model", "answers": {"route": self.answer}})


@pytest.fixture
def brain(fake_llm) -> Brain:  # noqa: ANN001
    b = Brain()
    fake_llm(b)
    return b


@pytest.fixture
def model(monkeypatch) -> Model:  # noqa: ANN001
    m = Model()
    monkeypatch.setattr(decision, "transport", httpx.MockTransport(m))
    monkeypatch.setenv("DECISION_MODEL_URL", "http://decision.test")
    monkeypatch.setenv("DECISION_MODEL_API_KEY", "dm-test")
    monkeypatch.setenv("DECISION_MODEL_NAME", "test-model")
    monkeypatch.setenv("PHI_MODE", "0")
    get_settings.cache_clear()
    auth.reset_limits()
    yield m
    get_settings.cache_clear()


@pytest.fixture
async def indexed(client, seeded, brain):  # noqa: ANN001
    await run_index_jobs()
    return seeded


def close_scores(a: str, b: str):  # noqa: ANN201
    async def fake(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        return [{"agent_id": a, "score": 0.62}, {"agent_id": b, "score": 0.58}]

    return fake


def clear_win(a: str, b: str):  # noqa: ANN201
    """Stage A with a clear winner `a` and `b` still on the shortlist, so the decision model may pick either."""
    async def fake(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        return [{"agent_id": a, "score": 0.95}, {"agent_id": b, "score": 0.40}]

    return fake


async def _internal_agent(client) -> str:  # noqa: ANN001
    """The seed has no internal agent: add and publish one (staff scope), then index it."""
    r = await client.post("/api/agents", headers=H, json={"name": "Staff Helpdesk", "draft_config": {"mode": "internal", "voice": {"pipeline": "cascade"}}})
    assert r.status_code == 200, r.text
    agent_id = r.json()["id"]
    assert (await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})).status_code == 200
    await run_index_jobs()
    return agent_id


async def _front_desk(**patch) -> None:  # noqa: ANN003
    from voiceai.routing import front_desk

    async with sessionmaker()() as s:
        await front_desk.update(s, "northgate-health", front_desk.FrontDeskPatch(**patch))
        await s.commit()


async def test_clear_match_routes_in_stage_a(indexed, model):
    """Covers: RTE-01, RTE-12"""
    rec = await supervisor.route("northgate-health", "member", CLAIM, channel="text")
    assert rec["mode"] == "embedding" and rec["method"] == "embedding" and rec["agent_id"] == indexed["claims"]["agent_id"]
    assert rec["candidates"][0]["agent_id"] == indexed["claims"]["agent_id"] and rec["stage_b"] is None and not model.requests


async def test_decision_model_decides_first(indexed, model, monkeypatch):
    """Covers: RTE-02, RTE-15"""
    claims, care = indexed["claims"]["agent_id"], indexed["care"]["agent_id"]
    monkeypatch.setattr(catalog, "stage_a", clear_win(claims, care))
    await _front_desk(routing_mode="decision_model")
    model.answer = {"choice": care, "confidence": 0.36, "x_jev_confidence": 0.91, "probabilities": {care: 0.9}}
    rec = await supervisor.route("northgate-health", "member", CLAIM, channel="text")  # Stage A's clear win is claims
    assert rec["mode"] == "decision_model" and rec["method"] == "decision" and rec["agent_id"] == care
    assert rec["stage_b"]["confidence"] == 0.91 and rec["stage_b"]["target"] == "decision_model"
    req = model.requests[0]
    body = json.loads(req.content)
    criteria = body["questions"]["route"]["criteria"]
    assert {claims, care, "none"} <= set(criteria) and all(isinstance(v, str) and v for v in criteria.values())
    assert req.headers["authorization"] == "Bearer dm-test" and body["model"] == "test-model" and str(req.url) == "http://decision.test/v1/systemone"


async def test_decision_model_falls_back_to_the_embedding(indexed, model, monkeypatch):
    """Covers: RTE-03"""
    claims, care = indexed["claims"]["agent_id"], indexed["care"]["agent_id"]
    monkeypatch.setattr(catalog, "stage_a", clear_win(claims, care))
    await _front_desk(routing_mode="decision_model", max_clarifications=0, default_agents={"member": care})
    for answer, reason in ((httpx.ReadTimeout("slow"), "timeout"), (503, "http_503"), ({"choice": "nobody", "confidence": 0.9}, "invalid_answer"),
                           ({"choice": "none", "confidence": 0.9}, "unsure"), ({"choice": care, "confidence": 0.1}, "unsure")):
        model.answer = answer
        rec = await supervisor.route("northgate-health", "member", CLAIM, channel="text")
        assert rec["method"] == "embedding" and rec["agent_id"] == claims, reason
        assert rec["fallbacks"] == [{"target": "decision_model", "error": reason}]
    monkeypatch.setattr(catalog, "stage_a", close_scores(claims, care))  # no clear win either: unsure, then the default agent
    rec = await supervisor.route("northgate-health", "member", "something", channel="text")
    assert rec["method"] == "default" and rec["agent_id"] == care and rec["unsure"]


async def test_phi_mode_blocks_a_hosted_model(indexed, model, monkeypatch):
    """Covers: RTE-04"""
    monkeypatch.setattr(catalog, "stage_a", clear_win(indexed["claims"]["agent_id"], indexed["care"]["agent_id"]))
    await _front_desk(routing_mode="decision_model")
    model.answer = {"choice": indexed["care"]["agent_id"], "confidence": 0.99}
    monkeypatch.setenv("PHI_MODE", "1")
    get_settings.cache_clear()
    rec = await supervisor.route("northgate-health", "member", CLAIM, channel="voice")
    assert not model.requests and rec["fallbacks"] == [{"target": "decision_model", "error": "phi_mode"}] and rec["method"] == "embedding"
    monkeypatch.setenv("DECISION_MODEL_HOSTED", "0")
    get_settings.cache_clear()
    rec = await supervisor.route("northgate-health", "member", CLAIM, channel="voice")
    assert len(model.requests) == 1 and rec["method"] == "decision"


async def test_not_configured_runs_the_embedding(indexed, monkeypatch):
    """Covers: RTE-13"""
    await _front_desk(routing_mode="decision_model")
    rec = await supervisor.route("northgate-health", "member", CLAIM, channel="text")
    assert rec["method"] == "embedding" and rec["fallbacks"] == [{"target": "decision_model", "error": "not_configured"}]


async def test_thresholds_are_settings(indexed, monkeypatch):
    """Covers: RTE-14"""
    claims, care = indexed["claims"]["agent_id"], indexed["care"]["agent_id"]

    async def scores(s, tenant_id, scope, text, candidates=None):  # noqa: ANN001, ANN202
        return [{"agent_id": claims, "score": 0.65}, {"agent_id": care, "score": 0.62}]

    monkeypatch.setattr(catalog, "stage_a", scores)
    await _front_desk(max_clarifications=0)
    assert (await supervisor.route("northgate-health", "member", "x", channel="text"))["unsure"]
    await _front_desk(clear_win=0.6, clear_margin=0.02)
    rec = await supervisor.route("northgate-health", "member", "x", channel="text")
    assert rec["method"] == "embedding" and rec["agent_id"] == claims


async def test_clarify_then_default(indexed, brain, monkeypatch):
    """Covers: RTE-05"""
    claims, care = indexed["claims"]["agent_id"], indexed["care"]["agent_id"]
    monkeypatch.setattr(catalog, "stage_a", close_scores(claims, care))
    await _front_desk(default_agents={"member": claims}, max_clarifications=1)
    brain.router.append({"question": "Is this about a claim, or about your coverage?"})
    rec = await supervisor.route("northgate-health", "member", "I have a question", channel="voice")
    assert rec["method"] == "clarify" and rec["clarification"] == "Is this about a claim, or about your coverage?"
    rec = await supervisor.route("northgate-health", "member", "I have a question still", channel="voice", clarifications_used=1)
    assert rec["method"] == "default" and rec["agent_id"] == claims
    await _front_desk(max_clarifications=0)
    rec = await supervisor.route("northgate-health", "member", "hm", channel="voice")
    assert rec["method"] == "default"


async def test_scopes(client, indexed):
    """Covers: RTE-06"""
    internal = await _internal_agent(client)
    async with sessionmaker()() as s:
        member = set(await supervisor.candidates(s, "northgate-health", "member"))
        staff = set(await supervisor.candidates(s, "northgate-health", "staff"))
    assert member == {indexed["care"]["agent_id"], indexed["sales"]["agent_id"], indexed["claims"]["agent_id"]}
    assert staff == {internal}
    rec = await supervisor.route("northgate-health", "staff", "who handles fraud?", channel="text")
    assert rec["method"] == "single" and rec["agent_id"] == internal


async def test_routed_voice_conversation(client, indexed, model, brain, monkeypatch, app):
    """Covers: RTE-07"""
    from voiceai.routing.voice_session import ConversationSession

    monkeypatch.setenv("PUBLIC_API_SECRET", "s3cret")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "dg-test")
    get_settings.cache_clear()
    r = await client.post("/api/conversations", headers=H, json={"channel": "voice", "scope": "member"})
    assert r.status_code == 201, r.text
    cid = r.json()["conversation_id"]
    async with sessionmaker()() as s:
        conv = await s.get(Conversation, cid)
    session = await ConversationSession.open(conv, app)
    voice_before = session.call_settings.cascade_voice
    greeting = await session.start()
    assert "virtual assistant" in greeting.lower()
    brain.realtime.append("I can help you get that referral covered.")
    chunks = [c async for c in session.respond(CLAIM)]
    joined = "".join(chunks)
    assert chunks[0] == "You're now with our claims and treatment team." and "referral covered" in joined
    assert session.call_settings.cascade_voice == voice_before  # one voice for the whole conversation
    async with sessionmaker()() as s:
        call = await s.scalar(select(Call).where(Call.conversation_id == cid))
        events = (await s.scalars(select(CallEvent).where(CallEvent.call_id == call.id).order_by(CallEvent.seq))).all()
    assert events[0].data.get("front_desk") and events[0].text == greeting
    kinds = [(e.kind, e.text) for e in events if e.kind in ("user", "assistant")]
    assert kinds[1] == ("user", CLAIM) and kinds[2][1] == "You're now with our claims and treatment team."
    # the realtime pipeline: intro, then the agent's model answers with refreshed instructions
    r2 = await client.post("/api/conversations", headers=H, json={"channel": "voice", "scope": "member"})
    async with sessionmaker()() as s:
        conv2 = await s.get(Conversation, r2.json()["conversation_id"])
    rt = await ConversationSession.open(conv2, app)
    await rt.start()
    d = await rt.caller_turn(CLAIM)
    assert d.say == "You're now with our claims and treatment team." and d.model_turn and d.refresh
    assert "never answer questions yourself" not in rt.prompt() and "How this caller reached you" in rt.prompt()  # the agent's prompt


async def test_front_desk_phone_number(app, tmp_path, monkeypatch, fake_llm):
    """Covers: RTE-08, TEL-12"""
    from starlette.testclient import TestClient

    from voiceai import conversations, telephony

    b = Brain()
    fake_llm(b)
    for k, v in {"DATABASE_URL": f"sqlite+aiosqlite:///{(tmp_path / 'fd.db').as_posix()}", "AUTO_SEED": "1", "TWILIO_AUTH_TOKEN": "tok",
                 "PUBLIC_BASE_URL": "https://abc.ngrok.test", "DEEPGRAM_API_KEY": "dg"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    with TestClient(app) as c:
        await run_index_jobs()
        r = c.post("/api/phone-numbers", headers=H, json={"e164": "+447700900222", "target": "front_desk"})
        assert r.status_code == 200 and r.json()["target"] == "front_desk" and r.json()["agent_id"] is None
        params = {"CallSid": "CA9", "From": "+447700900567", "To": "+447700900222"}
        url = "https://abc.ngrok.test/api/telephony/twilio/voice?ivr_menu=claims"
        sig = telephony.compute_signature("tok", url, {k: [v] for k, v in params.items()})
        twiml = c.post("/api/telephony/twilio/voice?ivr_menu=claims", data=params, headers={"X-Twilio-Signature": sig}).text
        assert "/api/telephony/twilio/conversation/" in twiml
        async with sessionmaker()() as s:
            conv = await s.scalar(select(Conversation).where(Conversation.source == "phone"))
            assert conv.scope == "member" and not await s.scalar(select(Call).where(Call.conversation_id == conv.id))
        out = await conversations.front_desk_turn(conv.id, "northgate-health", CLAIM, app)
        assert out["kind"] == "routed"
        async with sessionmaker()() as s:
            call = await s.get(Call, out["call_id"])
            assert call.meta["telephony"]["to"] == "+447700900222" and call.meta["context"]["ivr_menu"] == "claims"
    get_settings.cache_clear()


async def test_routing_trace_events(client, indexed, model):
    """Covers: RTE-09, PUB-05, PUB-03"""
    sub = bus.subscribe("northgate-health", set())
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "message": CLAIM})
    body = r.json()
    assert body["agent"]["name"] == "Claims & Pre-authorisation" and body["routing"]["method"] == "embedding"
    assert [m["speaker"] for m in body["messages"]][:2] == ["front_desk", "agent"]
    assert body["messages"][1]["text"] == "You're now with our claims and treatment team." and len(body["messages"]) == 3
    sub.topics = {f"conversation:{body['conversation_id']}"}
    view = (await client.get(f"/api/conversations/{body['conversation_id']}", headers=H)).json()
    decision_rec = view["routing"][-1]
    assert decision_rec["candidates"] and "stage_b" in decision_rec and decision_rec["agent_id"] == indexed["claims"]["agent_id"]
    bus.unsubscribe(sub)
    # the event is published on the conversation topic
    seen: list[dict] = []
    sub = bus.subscribe("northgate-health", set())
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member"})
    cid = r.json()["conversation_id"]
    assert r.json()["agent"] is None and r.json()["messages"][0]["speaker"] == "front_desk"
    sub.topics = {f"conversation:{cid}"}
    await client.post(f"/api/conversations/{cid}/messages", headers=H, json={"text": CLAIM})
    while not sub.queue.empty():
        seen.append(sub.queue.get_nowait())
    bus.unsubscribe(sub)
    assert [e["type"] for e in seen][:2] == ["routing.decision", "conversation.segment"]
    assert seen[0]["data"]["decision"]["candidates"]


async def test_explicit_agent_makes_no_routing_request(client, indexed, model):
    """Covers: RTE-10"""
    r = await client.post("/api/conversations", headers=H, json={"channel": "text", "scope": "member", "agent_id": indexed["care"]["agent_id"]})
    assert r.json()["routing"]["method"] == "explicit" and not model.requests


async def test_health_reports_the_decision_model(client, monkeypatch, database):
    """Covers: RTE-11, DEP-05"""
    monkeypatch.setenv("PUBLIC_API_SECRET", "s3cret")
    monkeypatch.setenv("DECISION_MODEL_URL", "https://decision.example.test")
    monkeypatch.setenv("PHI_MODE", "")
    monkeypatch.setenv("K_SERVICE", "voiceai")
    monkeypatch.setenv("DECISION_MODEL_TIMEOUT_VOICE_MS", "")
    monkeypatch.setenv("DECISION_MODEL_TIMEOUT_TEXT_MS", "")
    get_settings.cache_clear()
    budgets = {"voice": 350, "text": 1500}
    try:
        h = (await client.get("/healthz")).json()
        assert h["public_api"] is True
        assert h["router"] == {"decision_model": {"configured": True, "hosted": True, "blocked": True, "timeouts_ms": budgets}}
        monkeypatch.setenv("DECISION_MODEL_URL", "")
        get_settings.cache_clear()
        assert (await client.get("/healthz")).json()["router"]["decision_model"] == {"configured": False, "hosted": True, "blocked": False,
                                                                                   "timeouts_ms": budgets}
    finally:
        monkeypatch.delenv("K_SERVICE")
        get_settings.cache_clear()


def test_router_role_only(tmp_path):
    """Covers: LG-14"""
    import yaml

    from voiceai.llm.gateway import Gateway

    g = Gateway()
    assert g.role_model("router") and g.roles["router"]["fallback"][-1].startswith("openai:")
    cfg = yaml.safe_load(open(get_settings().models_config, encoding="utf-8"))
    assert "decision" not in cfg and not hasattr(g, "decision")


async def test_front_desk_settings(client, indexed):
    """Covers: API-13, MT-16"""
    fd = (await client.get("/api/tenant-settings/front-desk", headers={"X-Tenant-Id": "northgate-sandbox"})).json()
    assert fd["max_clarifications"] == 1 and fd["pipeline"] == "cascade" and fd["default_agents"] == {"member": None, "staff": None}
    for body in ({"default_agents": {"member": await _internal_agent(client)}}, {"max_clarifications": 3}):
        assert (await client.put("/api/tenant-settings/front-desk", headers=H, json=body)).status_code == 422
    await client.put("/api/tenant-settings", headers={"X-Tenant-Id": "northgate-sandbox"}, json={"allowed_pipelines": ["cascade"]})
    assert (await client.put("/api/tenant-settings/front-desk", headers={"X-Tenant-Id": "northgate-sandbox"}, json={"pipeline": "realtime"})).status_code == 422
    ok = await client.put("/api/tenant-settings/front-desk", headers=H, json={"pipeline": "realtime", "default_agents": {"member": indexed["care"]["agent_id"]}})
    assert ok.status_code == 200
    r = await client.put("/api/tenant-settings", headers=H, json={"allowed_pipelines": ["cascade"]})
    assert r.status_code == 409 and "Front desk" in r.json()["detail"]


async def test_routing_suite_run(client, indexed, model):
    """Covers: CAT-07"""
    from voiceai.routing import suite

    from voiceai.models import EvalRun

    r = await client.post("/api/routing/runs", headers=H)
    assert r.status_code == 409 and r.json()["error"] == "run_in_progress"  # the catalog's own run is waiting
    async with sessionmaker()() as s:
        run = await s.scalar(select(EvalRun).where(EvalRun.kind == "routing", EvalRun.trigger == "catalog"))
    summary = await suite.run(run.id, "northgate-health")
    assert summary["cases"] > 0 and summary["accuracy"] is not None and "confusion" in summary and "passes" in summary
    detail = (await client.get(f"/api/routing/runs/{run.id}", headers=H)).json()
    assert len(detail["results"]) == summary["cases"] and all("method" in r and "latency_ms" in r for r in detail["results"])


async def test_compare_modes(client, indexed, model):
    """Covers: CAT-09"""
    from voiceai.models import EvalRun
    from voiceai.routing import suite

    care = indexed["care"]["agent_id"]
    r = await client.post("/api/routing/cases", headers=H, json={"utterance": "Can you help me with something?", "expected_agent_id": "?"})
    assert r.status_code == 201
    async with sessionmaker()() as s:  # the catalog's own run is waiting: turn it into a comparison
        run = await s.scalar(select(EvalRun).where(EvalRun.kind == "routing"))
        run.config = {"compare": True}
        await s.commit()
    model.answer = {"choice": care, "confidence": 0.9}
    summary = (await suite.run_compare(run.id, "northgate-health"))["compare"]
    cases = summary["embedding"]["cases"]
    assert summary["current"] == "embedding" and len(model.requests) <= cases
    for mode in ("embedding", "decision_model"):
        row = summary[mode]
        assert row["configured"] and row["vague"] == 1 and {"right_first", "decided_alone", "right_when_decided", "vague_asked", "latency_ms"} <= set(row)
    assert summary["embedding"]["latency_ms"]["p95"] <= summary["decision_model"]["latency_ms"]["p95"]
    # without a decision model its row is marked not configured and nothing is sent
    model.requests.clear()
    from voiceai.config import get_settings as gs
    import os

    os.environ["DECISION_MODEL_URL"] = ""
    gs.cache_clear()
    try:
        assert (await suite.compare_case("northgate-health", "member", CLAIM))["decision_model"] == {"configured": False} and not model.requests
    finally:
        os.environ["DECISION_MODEL_URL"] = "http://decision.test"
        gs.cache_clear()


async def test_time_budgets_are_settings(indexed, model, monkeypatch):
    """Covers: RTE-16"""
    claims, care = indexed["claims"]["agent_id"], indexed["care"]["agent_id"]
    monkeypatch.setattr(catalog, "stage_a", clear_win(claims, care))
    await _front_desk(routing_mode="decision_model")

    async def slow(request: httpx.Request) -> httpx.Response:  # answers in 600 ms
        model.requests.append(request)
        await asyncio.sleep(0.6)
        return httpx.Response(200, json={"model": "fake-model", "answers": {"route": {"choice": care, "confidence": 0.9}}})

    monkeypatch.setattr(decision, "transport", httpx.MockTransport(slow))

    async def route(channel: str, voice_ms: str, text_ms: str) -> dict[str, Any]:
        monkeypatch.setenv("DECISION_MODEL_TIMEOUT_VOICE_MS", voice_ms)
        monkeypatch.setenv("DECISION_MODEL_TIMEOUT_TEXT_MS", text_ms)
        get_settings.cache_clear()
        return await supervisor.route("northgate-health", "member", CLAIM, channel=channel)

    rec = await route("voice", "1000", "")
    assert rec["method"] == "decision" and rec["agent_id"] == care and rec["fallbacks"] == []
    rec = await route("voice", "", "")  # the default voice budget, 350 ms
    assert rec["method"] == "embedding" and rec["agent_id"] == claims
    assert rec["fallbacks"] == [{"target": "decision_model", "error": "timeout"}]
    rec = await route("text", "1000", "200")  # text has its own budget
    assert rec["method"] == "embedding" and rec["fallbacks"] == [{"target": "decision_model", "error": "timeout"}]
    rec = await route("text", "100", "")  # the default text budget, 1.5 s
    assert rec["method"] == "decision" and rec["agent_id"] == care


async def test_time_budget_bounds_and_health(client, monkeypatch, database):
    """Covers: RTE-17"""
    monkeypatch.setenv("DECISION_MODEL_TIMEOUT_TEXT_MS", "")
    for raw, used in (("50", 100), ("99999", 5000), ("abc", 350), ("", 350), ("800", 800)):
        monkeypatch.setenv("DECISION_MODEL_TIMEOUT_VOICE_MS", raw)
        get_settings.cache_clear()
        assert decision.timeout_ms("voice") == used, raw
        h = (await client.get("/healthz")).json()
        assert h["router"]["decision_model"]["timeouts_ms"] == {"voice": used, "text": 1500}
    get_settings.cache_clear()
