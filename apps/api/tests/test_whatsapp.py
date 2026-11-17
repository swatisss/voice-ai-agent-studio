"""CP-0052: WhatsApp via Twilio as a text channel with human handover.

Twilio REST runs on an httpx MockTransport, webhooks are signed with the real X-Twilio-Signature algorithm and a test token, the
transcriber is the fake of CP-0051, the LLM is the repo's fake, the database is temp SQLite. No network, no credentials.

Covers: WA-01, WA-02, WA-03, WA-04, WA-05, WA-06, WA-07, WA-08, WA-09, WA-10, WA-11, WA-12, WA-13, WA-14, WA-15, DM-20, API-20, API-23, ES-14, DESK-12, HMC-04
"""
from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import func, inspect, select, text

from tests.conftest import script
from tests.test_agent_desk import PW, _login, signin  # noqa: F401
from tests.test_supervisor_routing import brain, indexed  # noqa: F401
from voiceai import handover, telephony, whatsapp
from voiceai.config import get_settings
from voiceai.db import engine, sessionmaker, utcnow
from voiceai.llm.gateway import FakeReply
from voiceai.models import Call, CallEvent, Conversation, Escalation, WhatsappSender, WhatsappThread
from voiceai.voice import transcribe
from voiceai.voice.transcribe import FakeTranscriber, Segment, make_wav

TOKEN = "twilio-test-token"
BASE = "https://abc123.ngrok.test"
SANDBOX = "whatsapp:+14155238886"
PRODUCTION = "whatsapp:+15555550100"
USER = "whatsapp:+447700900123"
USER_DIGITS = "447700900123"
H = {"X-Tenant-Id": "northgate-health"}
P = {"X-Tenant-Id": "northgate-sandbox"}
INBOUND = "/api/channels/twilio/whatsapp/inbound"
STATUS = "/api/channels/twilio/whatsapp/status"
HUMAN = "I want to speak to a human"


# ---------------------------------------------------------------- fakes
class Clock:
    """The pacing clock: sleeping moves time, nothing waits."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class FakeTwilio:
    """Twilio's Messages API and media URLs on a MockTransport."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.sent: list[dict[str, str]] = []
        self.at: list[float] = []
        self.media: dict[str, bytes] = {}
        self.media_requests: list[httpx.Request] = []
        self.out_of_window_once = False
        self.fail_all = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Messages.json") and request.method == "POST":
            fields = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if self.fail_all:
                return httpx.Response(500, json={"message": "boom"})
            if self.out_of_window_once and "Body" in fields:
                self.out_of_window_once = False
                return httpx.Response(400, json={"code": 63016, "message": "outside the allowed window"})
            self.sent.append(fields)
            self.at.append(self.clock.t)
            return httpx.Response(201, json={"sid": f"SM{len(self.sent):032d}"})
        if request.url.path in self.media:
            self.media_requests.append(request)
            return httpx.Response(200, content=self.media[request.url.path], headers={"content-type": "audio/ogg"})
        return httpx.Response(404)

    def bodies(self) -> list[str]:
        return [m["Body"] for m in self.sent if "Body" in m]


@pytest.fixture
def twilio(monkeypatch, fake_llm):  # noqa: ANN001, ANN201
    clock = Clock()
    for key, value in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": TOKEN, "PUBLIC_BASE_URL": BASE,
                       "TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID": ""}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("WHATSAPP_MIN_SEND_INTERVAL_S", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(whatsapp, "_now", clock.now)
    monkeypatch.setattr(whatsapp, "_sleep", clock.sleep)
    whatsapp.reset_state()
    fake = FakeTwilio(clock)
    fake.clock = clock
    handover.set_http_client(httpx.AsyncClient(transport=httpx.MockTransport(fake.handler)))
    transcribe.set_transcriber(None)
    llm = SimpleNamespace(calls=0, all=0)  # calls: the agent's own model; all: every role (packet builds included)

    def counting(*replies):  # noqa: ANN002, ANN202
        inner = script(*replies)

        def responder(role, messages, tools):  # noqa: ANN001, ANN202
            llm.all += 1
            llm.calls += role == "realtime"
            return inner(role, messages, tools)
        return responder

    fake.llm, fake.counting = llm, counting
    fake_llm(counting())
    yield fake
    handover.set_http_client(None)
    transcribe.set_transcriber(None)
    whatsapp.reset_state()
    get_settings.cache_clear()


async def add_sender(seeded, address=SANDBOX, mode="sandbox", front_desk=False):  # noqa: ANN001, ANN201
    async with sessionmaker()() as s:
        row = WhatsappSender(tenant_id="northgate-health", address=address, mode=mode, target="front_desk" if front_desk else "agent",
                             agent_id=None if front_desk else seeded["care"]["agent_id"], label="test")
        s.add(row)
        await s.commit()
        return row.id


async def post(client, path, sender=SANDBOX, user=USER, sid="SM1", sign=True, url=None, **extra):  # noqa: ANN001, ANN201
    params = {"MessageSid": sid, "From": user, "To": sender, "Body": "", "NumMedia": "0", **extra}
    headers = {"X-Twilio-Signature": telephony.compute_signature(TOKEN, url or BASE + path, {k: [v] for k, v in params.items()})} if sign else {}
    return await client.post(path, data=params, headers=headers)


_sids = iter(range(1, 10_000))


async def say(client, body, sender=SANDBOX, user=USER, **extra):  # noqa: ANN001, ANN201
    r = await post(client, INBOUND, sender=sender, user=user, sid=f"SMin{next(_sids)}", Body=body, **extra)
    assert r.status_code == 200, r.text
    return r


async def receipt(client, sid, state, sender=SANDBOX, user=USER, **extra):  # noqa: ANN001, ANN201
    """Twilio's receipt: From is the sender, To is the user."""
    return await post(client, STATUS, sender=user, user=sender, sid=sid, MessageStatus=state, **extra)


async def threads():  # noqa: ANN201
    async with sessionmaker()() as s:
        return list((await s.scalars(select(WhatsappThread).order_by(WhatsappThread.created_at))).all())


async def conversations_():  # noqa: ANN201
    async with sessionmaker()() as s:
        return list((await s.scalars(select(Conversation).where(Conversation.source == "whatsapp").order_by(Conversation.started_at))).all())


async def escalated(client, seeded, twilio, mode="sandbox", sender=SANDBOX):  # noqa: ANN001, ANN201
    """A WhatsApp conversation whose customer asked for a person, accepted by a specialist: returns the escalation id."""
    await add_sender(seeded, sender, mode)
    await say(client, "Hello", sender=sender)
    await say(client, HUMAN, sender=sender)
    esc = await wa_escalation()
    assert esc is not None, twilio.bodies()
    r = await client.post(f"/api/escalations/{esc.id}/accept", headers=H, json={"assignee": "Sam Specialist"})
    assert r.status_code == 200, r.text
    twilio.sent.clear()
    twilio.at.clear()
    return esc.id


async def reply(client, esc_id, text_="Hi, this is Sam.", headers=H):  # noqa: ANN001, ANN201
    return await client.post(f"/api/escalations/{esc_id}/messages", headers=headers, json={"text": text_})


async def wa_events(kind):  # noqa: ANN001, ANN201
    """Events of WhatsApp conversations only (the seed holds calls of its own)."""
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).join(Call, Call.id == CallEvent.call_id).join(Conversation, Conversation.id == Call.conversation_id)
                                     .where(Conversation.source == "whatsapp", CallEvent.kind == kind).order_by(CallEvent.at, CallEvent.seq))).all())


async def human_events():  # noqa: ANN201
    return await wa_events("human")


async def _user_events():  # noqa: ANN202
    return await wa_events("user")


async def wa_escalation():  # noqa: ANN201
    async with sessionmaker()() as s:
        return await s.scalar(select(Escalation).join(Call, Call.id == Escalation.call_id).join(Conversation, Conversation.id == Call.conversation_id)
                              .where(Conversation.source == "whatsapp").order_by(Escalation.created_at.desc()))


# ---------------------------------------------------------------- WA-01, API-20
async def test_sender_api(client, seeded, signin):  # noqa: ANN001
    """Covers: WA-01, API-20"""
    agent_id = seeded["care"]["agent_id"]
    ok = await client.post("/api/whatsapp-senders", headers=H, json={"address": SANDBOX, "agent_id": agent_id, "label": "sandbox"})
    assert ok.status_code == 201 and ok.json()["mode"] == "sandbox" and ok.json()["target"] == "agent"
    assert (await client.post("/api/whatsapp-senders", headers=H, json={"address": "+14155238886", "agent_id": agent_id})).status_code == 422
    assert (await client.post("/api/whatsapp-senders", headers=H, json={"address": PRODUCTION, "mode": "live", "agent_id": agent_id})).status_code == 422
    dup = await client.post("/api/whatsapp-senders", headers=P, json={"address": SANDBOX, "target": "front_desk"})
    assert dup.status_code == 409 and dup.json()["error"] == "sender_in_use"
    bad = await client.post("/api/whatsapp-senders", headers=H, json={"address": PRODUCTION, "agent_id": "nope"})
    assert bad.status_code == 422
    fd = await client.post("/api/whatsapp-senders", headers=H, json={"address": PRODUCTION, "mode": "production", "target": "front_desk"})
    assert fd.status_code == 201 and fd.json()["agent_id"] is None
    assert [i["address"] for i in (await client.get("/api/whatsapp-senders", headers=H)).json()["items"]] == [SANDBOX, PRODUCTION]
    assert (await client.get("/api/whatsapp-senders", headers=P)).json()["items"] == []
    assert (await client.delete(f"/api/whatsapp-senders/{ok.json()['id']}", headers=P)).status_code == 404  # another tenant's sender
    signin()
    for who in ("reviewer", "specialist"):
        await _login(client, who)
        r = await client.post("/api/whatsapp-senders", json={"address": "whatsapp:+15555550111", "target": "front_desk"})
        assert r.status_code == 403, (who, r.text)
    await _login(client, "admin")
    assert (await client.delete(f"/api/whatsapp-senders/{ok.json()['id']}", headers=H)).status_code == 204


async def test_removed_sender_makes_the_webhook_do_nothing(client, seeded, twilio):
    """Covers: WA-01"""
    row_id = await add_sender(seeded)
    assert (await client.delete(f"/api/whatsapp-senders/{row_id}", headers=H)).status_code == 204
    r = await say(client, "Hello")
    assert r.text.endswith("<Response/>") and not twilio.sent and await threads() == []


def test_sender_cli_mirrors_the_api(tmp_path, monkeypatch, capsys):  # noqa: ANN001
    """Covers: WA-01"""
    from voiceai import cli, db

    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'cli.db').as_posix()}")
    get_settings.cache_clear()
    import asyncio

    async def prepare() -> None:
        from voiceai.models import Tenant

        db.configure()
        await db.init_db()
        async with db.sessionmaker()() as s:
            s.add(Tenant(id="northgate-health", name="Northgate Health"))
            await s.commit()
        await db.engine().dispose()

    asyncio.run(prepare())
    try:
        cli.main(["whatsapp", "add", SANDBOX, "--front-desk", "--label", "sandbox"])
        cli.main(["whatsapp", "add", PRODUCTION, "--front-desk", "--production"])
        cli.main(["whatsapp", "list"])
        out = capsys.readouterr().out
        assert f"{SANDBOX}" in out and "sandbox" in out and f"{PRODUCTION}" in out and "production" in out
        with pytest.raises(SystemExit):
            cli.main(["whatsapp", "add", SANDBOX, "--front-desk"])  # already routed
        with pytest.raises(SystemExit):
            cli.main(["whatsapp", "add", "+14155238886", "--front-desk"])  # not a WhatsApp address
        capsys.readouterr()
        cli.main(["whatsapp", "remove", SANDBOX])
        assert "removed" in capsys.readouterr().out
        cli.main(["whatsapp", "list"])
        listing = capsys.readouterr().out
        assert SANDBOX not in listing and PRODUCTION in listing
    finally:
        get_settings.cache_clear()
        asyncio.run(db.engine().dispose())


# ---------------------------------------------------------------- WA-02
async def test_signature_is_checked(client, seeded, twilio):
    """Covers: WA-02"""
    await add_sender(seeded)
    assert (await post(client, INBOUND, sign=False, Body="Hi")).status_code == 403
    assert (await post(client, INBOUND, url="https://other.example.test" + INBOUND, Body="Hi")).status_code == 403  # signed over another URL
    assert (await post(client, INBOUND, url=BASE + "/api/channels/twilio/whatsapp/status", Body="Hi")).status_code == 403
    assert await threads() == [] and await conversations_() == []
    ok = await post(client, INBOUND, Body="Hi, what is my excess?")
    assert ok.status_code == 200 and ok.text.endswith("<Response/>") and len(await conversations_()) == 1
    unknown = await post(client, INBOUND, sender="whatsapp:+15555550199", sid="SM2", Body="Hi")
    assert unknown.status_code == 200 and len(await conversations_()) == 1
    nofrom = await post(client, INBOUND, user="", sid="SM3", Body="Hi")  # spike S8: no usable From is ignored
    assert nofrom.status_code == 200 and len(await threads()) == 1


async def test_signature_validation_can_be_switched_off_locally(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-02"""
    await add_sender(seeded)
    monkeypatch.setenv("TWILIO_VALIDATE_SIGNATURE", "0")
    get_settings.cache_clear()
    assert (await post(client, INBOUND, sign=False, Body="Hi")).status_code == 200
    assert len(await conversations_()) == 1
    monkeypatch.setenv("K_SERVICE", "run")  # TEL-10: never on Cloud Run
    with pytest.raises(RuntimeError):
        telephony.assert_safe_settings()


# ---------------------------------------------------------------- WA-03, WA-04
async def test_first_message_opens_a_conversation_and_thread(client, seeded, twilio):
    """Covers: WA-03"""
    await add_sender(seeded)
    before = utcnow()
    r = await post(client, INBOUND, sid="SMfirst", Body="Hi, what is my excess?")
    assert r.status_code == 200 and r.text.endswith("<Response/>")
    convs, ts = await conversations_(), await threads()
    assert len(convs) == 1 and len(ts) == 1
    assert (convs[0].source, convs[0].channel, convs[0].transport, convs[0].scope) == ("whatsapp", "text", "twilio", "member")
    assert ts[0].conversation_id == convs[0].id and ts[0].status == "active" and ts[0].address == USER and ts[0].address_last4 == "0123"
    assert timedelta(hours=23, minutes=59) < ts[0].window_expires_at - before < timedelta(hours=24, minutes=1)
    assert twilio.sent and all(m["To"] == USER and m["From"] == SANDBOX for m in twilio.sent)
    assert twilio.bodies()[0].startswith("I'm a virtual assistant")
    sent = len(twilio.sent)
    await post(client, INBOUND, sid="SMfirst", Body="Hi, what is my excess?")  # Twilio retries the same message
    assert len(twilio.sent) == sent and len(await conversations_()) == 1
    assert [e.text for e in await wa_events("user")] == ["Hi, what is my excess?"]


async def test_second_message_continues_the_thread(client, seeded, twilio, fake_llm):  # noqa: ANN001
    """Covers: WA-04"""
    await add_sender(seeded)
    await say(client, "Hello")
    first = (await threads())[0]
    long_text = " ".join(f"This is sentence number {i} of a long answer about the excess." for i in range(60))
    assert len(long_text) > 3000
    fake_llm(twilio.counting(FakeReply(text=long_text)))
    twilio.sent.clear()
    twilio.at.clear()
    await say(client, "Tell me everything")
    after = (await threads())[0]
    assert len(await conversations_()) == 1 and len(await threads()) == 1
    assert after.window_expires_at > first.window_expires_at
    parts = twilio.bodies()
    assert len(parts) >= 3 and all(len(p) <= 1500 for p in parts) and " ".join(parts).replace("  ", " ") == long_text
    gaps = [b - a for a, b in zip(twilio.at, twilio.at[1:])]
    assert gaps and all(g >= 3 for g in gaps)  # a sandbox sender: one message per 3 seconds


async def test_production_sender_has_no_pacing(client, seeded, twilio, fake_llm):  # noqa: ANN001
    """Covers: WA-04"""
    await add_sender(seeded, PRODUCTION, "production")
    long_text = " ".join(f"This is sentence number {i} of a long answer about the excess." for i in range(60))
    fake_llm(twilio.counting(FakeReply(text="Welcome."), FakeReply(text=long_text)))
    await say(client, "Hi", sender=PRODUCTION)
    await say(client, "Tell me everything", sender=PRODUCTION)
    assert len(twilio.sent) >= 3 and twilio.clock.slept == []


# ---------------------------------------------------------------- WA-05, WA-06, ES-14
@pytest.mark.parametrize(("line", "category"), [("I have chest pain", "safety"), (HUMAN, "caller_requested")])
async def test_safety_and_a_person_escalate(client, seeded, twilio, line, category):  # noqa: ANN001
    """Covers: WA-05, ES-14"""
    await add_sender(seeded)
    await say(client, "Hello")
    calls_before = twilio.llm.calls
    await say(client, line)
    async with sessionmaker()() as s:
        esc = await wa_escalation()
        conv = (await s.scalars(select(Conversation).where(Conversation.source == "whatsapp"))).one()
        call = await s.scalar(select(Call).where(Call.id == esc.call_id))
    assert esc.reason_category == category and conv.status == "escalated"  # not ended
    assert call.end_reason == "handoff" and conv.ended_at is None
    assert twilio.llm.calls == calls_before  # no model reply for these lines
    assert twilio.bodies() and twilio.bodies()[-1]  # the safety message or the hand-off line was sent


async def test_customer_lines_after_escalation_go_to_the_human(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-06, ES-14"""
    esc_id = await escalated(client, seeded, twilio)
    calls_before = twilio.llm.all
    await say(client, "Hello? Anyone there?")
    assert twilio.llm.all == calls_before and twilio.sent == []
    async with sessionmaker()() as s:
        ev = await s.scalar(select(CallEvent).where(CallEvent.text == "Hello? Anyone there?"))
    assert ev.kind == "user" and ev.data == {"to_human": True}
    detail = (await client.get(f"/api/escalations/{esc_id}", headers=H)).json()
    assert detail["human_thread"] is True and detail["conversation_status"] == "escalated"


# ---------------------------------------------------------------- WA-07, WA-09, API-23, DESK-12, HMC-04
async def test_specialist_reply_is_sent_and_receipts_update_it(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-07, API-23, HMC-04"""
    await add_sender(seeded)
    await say(client, "Hello")
    await say(client, HUMAN)
    esc = await wa_escalation()
    early = await reply(client, esc.id)
    assert early.status_code == 409 and early.json()["error"] == "not_accepted"
    assert await human_events() == []
    await client.post(f"/api/escalations/{esc.id}/accept", headers=H, json={"assignee": "Sam Specialist"})
    twilio.sent.clear()
    published = []
    monkeypatch.setattr(whatsapp.bus, "publish", lambda *a, **k: published.append(a))
    r = await reply(client, esc.id, "Hi, this is Sam.")
    assert r.status_code == 201 and r.json()["delivery"] == "sent" and r.json()["speaker"] == "human"
    assert twilio.bodies() == ["Hi, this is Sam."] and twilio.sent[0]["To"] == USER and "ContentSid" not in twilio.sent[0]
    sid = f"SM{1:032d}"
    ev = (await human_events())[0]
    assert ev.data["delivery"] == "sent" and ev.data["author"] == "Sam Specialist" and ev.data["message_sids"] == [sid]
    published.clear()
    assert (await receipt(client, sid, "delivered")).status_code == 200
    assert (await human_events())[0].data["delivery"] == "delivered"
    assert any(p[1] == "console" and p[2] == "escalation.updated" for p in published)
    await receipt(client, sid, "read")
    await receipt(client, sid, "delivered")  # a late receipt never moves it back
    assert (await human_events())[0].data["delivery"] == "read"
    assert (await post(client, STATUS, sender=USER, user=SANDBOX, sid=sid, sign=False, MessageStatus="failed")).status_code == 403  # an unsigned receipt is refused
    detail = (await client.get(f"/api/escalations/{esc.id}", headers=H)).json()
    assert [e["data"]["delivery"] for e in detail["events"] if e["kind"] == "human"] == ["read"]


async def test_channel_state(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-09, API-23"""
    esc_id = await escalated(client, seeded, twilio)
    th = (await threads())[0]
    state = (await client.get(f"/api/escalations/{esc_id}", headers=H)).json()["channel_state"]
    assert state["channel"] == "whatsapp" and state["window_open"] is True and state["opted_out"] is False and state["mode"] == "sandbox"
    assert state["window_expires_at"].startswith(th.window_expires_at.isoformat()[:19]) and state["address_last4"] == "0123"
    listed = next(i for i in (await client.get("/api/escalations", headers=H)).json()["items"] if i["id"] == esc_id)
    assert listed["channel_state"]["window_open"] is True
    async with sessionmaker()() as s:
        row = await s.get(WhatsappThread, th.id)
        row.window_expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    assert (await client.get(f"/api/escalations/{esc_id}", headers=H)).json()["channel_state"]["window_open"] is False


async def test_other_conversations_have_no_channel_state(client, seeded, fake_llm):  # noqa: ANN001
    """Covers: WA-09, API-23, HMC-04"""
    from tests.test_escalation_console import ESC

    fake_llm(lambda role, messages, tools: FakeReply(tool_calls=[ESC]) if role == "realtime" else FakeReply(text="{}"))
    r = await client.post("/api/calls", headers=H, json={"agent_id": seeded["care"]["agent_id"], "channel": "text"})
    call_id = r.json()["call_id"]
    await client.post(f"/api/calls/{call_id}/messages", headers=H, json={"text": "I want to appeal my denied claim"})
    async with sessionmaker()() as s:
        esc = await s.scalar(select(Escalation).where(Escalation.call_id == call_id))
    await client.post(f"/api/escalations/{esc.id}/accept", headers=H, json={"assignee": "Sam"})
    detail = (await client.get(f"/api/escalations/{esc.id}", headers=H)).json()
    assert "channel_state" not in detail and detail["human_thread"] is False
    assert "channel_state" not in next(i for i in (await client.get("/api/escalations", headers=H)).json()["items"] if i["id"] == esc.id)
    wrong = await reply(client, esc.id)  # a Studio call is still not a text channel with a person
    assert wrong.status_code == 409 and wrong.json()["error"] == "wrong_channel"


async def test_specialist_account_replies_and_sees_only_the_masked_user(client, seeded, twilio, signin):  # noqa: ANN001
    """Covers: DESK-12, WA-12"""
    await add_sender(seeded)
    await say(client, "Hello")
    await say(client, HUMAN)
    signin()
    await _login(client, "specialist")
    esc_id = (await wa_escalation()).id
    assert (await client.post(f"/api/escalations/{esc_id}/accept", json={"assignee": "Sam"})).status_code == 200
    r = await reply(client, esc_id, "Hello, this is Sam.", headers={})
    assert r.status_code == 201 and r.json()["delivery"] == "sent"
    detail = (await client.get(f"/api/escalations/{esc_id}")).json()
    dump = json.dumps(detail) + json.dumps((await client.get("/api/escalations")).json())
    assert USER_DIGITS not in dump and "7700900123" not in dump and detail["channel_state"]["address_last4"] == "0123"


# ---------------------------------------------------------------- WA-08
async def test_closed_window_uses_the_template_and_queues_the_text(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-08"""
    monkeypatch.setenv("TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID", "HXfollowup")
    get_settings.cache_clear()
    esc_id = await escalated(client, seeded, twilio, mode="production", sender=PRODUCTION)
    async with sessionmaker()() as s:
        th = (await s.scalars(select(WhatsappThread))).one()
        th.window_expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    r = await reply(client, esc_id, "Your claim is approved.")
    assert r.status_code == 201 and r.json()["delivery"] == "queued_template"
    assert len(twilio.sent) == 1 and "Body" not in twilio.sent[0]
    assert twilio.sent[0]["ContentSid"] == "HXfollowup" and json.loads(twilio.sent[0]["ContentVariables"]) == {"1": "Sam"}
    assert (await human_events())[0].data["delivery"] == "queued_template"
    twilio.sent.clear()
    await say(client, "I am here", sender=PRODUCTION)  # the customer replies: the window opens and the queue goes out
    assert twilio.bodies() == ["Your claim is approved."]
    ev = (await human_events())[0]
    assert ev.data["delivery"] == "sent" and ev.data["message_sids"]
    assert (await threads())[0].queued == []


async def test_closed_window_without_template_or_in_the_sandbox(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-08"""
    esc_id = await escalated(client, seeded, twilio, mode="production", sender=PRODUCTION)
    async with sessionmaker()() as s:
        th = (await s.scalars(select(WhatsappThread))).one()
        th.window_expires_at = utcnow() - timedelta(minutes=1)
        await s.commit()
    r = await reply(client, esc_id)
    assert r.status_code == 409 and r.json()["error"] == "template_not_configured"
    assert await human_events() == [] and twilio.sent == []
    async with sessionmaker()() as s:
        sender = await s.scalar(select(WhatsappSender))
        sender.mode = "sandbox"
        await s.commit()
    monkeypatch.setenv("TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID", "HXfollowup")
    get_settings.cache_clear()
    r = await reply(client, esc_id)
    assert r.status_code == 409 and r.json()["error"] == "window_closed"
    assert await human_events() == [] and twilio.sent == []


async def test_rejected_free_form_falls_back_to_the_template_once(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-08"""
    monkeypatch.setenv("TWILIO_WHATSAPP_FOLLOWUP_CONTENT_SID", "HXfollowup")
    get_settings.cache_clear()
    esc_id = await escalated(client, seeded, twilio, mode="production", sender=PRODUCTION)
    twilio.out_of_window_once = True  # the clock says open, WhatsApp says closed (error 63016)
    r = await reply(client, esc_id, "Still here.")
    assert r.status_code == 201 and r.json()["delivery"] == "queued_template"
    assert len(twilio.sent) == 1 and twilio.sent[0]["ContentSid"] == "HXfollowup"
    twilio.fail_all = True
    r = await reply(client, esc_id, "Another.")
    assert r.status_code == 201 and r.json()["delivery"] == "failed"  # shown to the specialist, not retried
    assert (await human_events())[-1].data["delivery"] == "failed"


# ---------------------------------------------------------------- WA-10
async def test_stop_opts_out_and_a_new_message_clears_it(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-10"""
    esc_id = await escalated(client, seeded, twilio)
    await say(client, " Stop ")
    assert (await threads())[0].status == "opted_out"
    assert twilio.bodies() == [whatsapp.OPT_OUT_CONFIRMATION]
    state = (await client.get(f"/api/escalations/{esc_id}", headers=H)).json()["channel_state"]
    assert state["opted_out"] is True
    r = await reply(client, esc_id)
    assert r.status_code == 409 and r.json()["error"] == "opted_out"
    assert await human_events() == [] and len(twilio.sent) == 1
    await say(client, "I changed my mind")
    assert (await threads())[0].status == "active" and len(twilio.sent) == 1  # to the specialist, nothing sent back
    assert (await reply(client, esc_id)).status_code == 201


@pytest.mark.parametrize("word", ["UNSUBSCRIBE", "cancel"])
async def test_other_opt_out_words(client, seeded, twilio, word):  # noqa: ANN001
    """Covers: WA-10"""
    await add_sender(seeded)
    await say(client, "Hi")
    await say(client, word)
    assert (await threads())[0].status == "opted_out" and twilio.bodies()[-1] == whatsapp.OPT_OUT_CONFIRMATION


# ---------------------------------------------------------------- WA-11
async def test_voice_note_is_transcribed_and_answered_in_text(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-11"""
    await add_sender(seeded)
    fake = FakeTranscriber([Segment(0, 30, "mera claim kahan tak pahuncha?", "hi")])
    transcribe.set_transcriber(fake)
    twilio.media["/media/voice1"] = make_wav([[0] * (30 * 8000)])
    await say(client, "", NumMedia="1", MediaUrl0="https://api.twilio.com/media/voice1", MediaContentType0="audio/ogg")
    assert len(fake.calls) == 1
    ev = (await wa_events("user"))[0]
    assert ev.text == "mera claim kahan tak pahuncha?" and ev.data.get("voice_note") is True
    assert twilio.bodies() and twilio.media_requests[0].headers["authorization"].startswith("Basic ")


async def test_oversized_voice_notes_are_refused(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-11"""
    await add_sender(seeded)
    fake = FakeTranscriber([Segment(0, 1, "never used")])
    transcribe.set_transcriber(fake)
    twilio.media["/media/long"] = make_wav([[0] * (130 * 8000)])
    twilio.media["/media/big"] = b"x" * (12 * 1024 * 1024)
    for name in ("long", "big"):
        await say(client, "", NumMedia="1", MediaUrl0=f"https://api.twilio.com/media/{name}", MediaContentType0="audio/ogg")
    assert twilio.bodies() == [whatsapp.VOICE_NOTE_FAILED] * 2 and fake.calls == [] and twilio.llm.all == 0
    assert await conversations_() == []


async def test_voice_note_failure_and_missing_transcriber(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-11"""
    await add_sender(seeded)
    twilio.media["/media/v"] = make_wav([[0] * 8000])
    args = {"NumMedia": "1", "MediaUrl0": "https://api.twilio.com/media/v", "MediaContentType0": "audio/ogg"}
    await say(client, "", **args)  # no transcriber configured
    transcribe.set_transcriber(FakeTranscriber(fail=True))
    await say(client, "", **args)
    assert twilio.bodies() == [whatsapp.VOICE_NOTE_FAILED] * 2 and twilio.llm.all == 0


async def test_images_get_one_notice_and_no_download(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-11"""
    esc_id = await escalated(client, seeded, twilio)
    picture = {"NumMedia": "1", "MediaUrl0": "https://api.twilio.com/media/pic", "MediaContentType0": "image/jpeg"}
    await say(client, "", **picture)
    await say(client, "", **picture)
    assert twilio.bodies() == [whatsapp.ATTACHMENT_NOTICE] and twilio.media_requests == []
    texts = [e.text for e in await wa_events("user")]
    assert texts.count("[attachment: image/jpeg]") == 2
    detail = (await client.get(f"/api/escalations/{esc_id}", headers=H)).json()
    assert any(e["text"] == "[attachment: image/jpeg]" for e in detail["events"])
    await say(client, "Here is my letter", **picture)  # text with an attachment is handled as text
    assert any(e.text == "Here is my letter" for e in await _user_events())


# ---------------------------------------------------------------- WA-12, DM-20
async def test_the_address_lives_in_one_column(client, seeded, twilio, caplog):  # noqa: ANN001
    """Covers: WA-12, DM-20"""
    caplog.set_level("DEBUG")
    esc_id = await escalated(client, seeded, twilio)
    await reply(client, esc_id, "Hi, this is Sam.")
    await say(client, "Thanks")
    await receipt(client, f"SM{1:032d}", "delivered")
    async with sessionmaker()() as s:
        dumps = []
        for model in (Conversation, Call, CallEvent, Escalation):
            for row in (await s.scalars(select(model))).all():
                dumps.append(json.dumps({c.name: str(getattr(row, c.key)) for c in model.__table__.columns}, default=str))
        async with engine().connect() as conn:
            all_tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
        for table in [t for t in all_tables if t not in ("whatsapp_threads", "whatsapp_senders")]:
            rows = (await s.execute(text(f'SELECT * FROM "{table}"'))).fetchall()
            dumps.append(json.dumps([[str(v) for v in row] for row in rows]))
    blob = "\n".join(dumps)
    assert USER_DIGITS not in blob and "7700900123" not in blob
    api = json.dumps((await client.get(f"/api/escalations/{esc_id}", headers=H)).json()) + json.dumps((await client.get("/api/escalations", headers=H)).json())
    api += json.dumps((await client.get("/api/conversations", headers=H)).json()) + json.dumps((await client.get("/api/calls", headers=H)).json())
    assert USER_DIGITS not in api and "7700900123" not in api
    logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("voiceai"))
    assert USER_DIGITS not in logs and "7700900123" not in logs
    assert (await threads())[0].address == USER
    conv = (await conversations_())[0]
    assert conv.metadata_ == {"user": "wa-…0123"}


async def test_address_is_cleared_after_retention(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-12, DM-20"""
    esc_id = await escalated(client, seeded, twilio)
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "resolved_by_human", "resolution_note": "Explained the excess."})
    assert r.status_code == 200, r.text
    assert await whatsapp.clear_addresses() == 0 and (await threads())[0].address == USER
    later = utcnow() + timedelta(days=29)
    assert await whatsapp.clear_addresses(later) == 0
    assert await whatsapp.clear_addresses(utcnow() + timedelta(days=31)) == 1
    th = (await threads())[0]
    assert th.address is None and th.address_last4 == "0123"


def test_mask_hides_whatsapp_addresses_in_free_text():
    """Covers: WA-12"""
    from voiceai import mask

    assert mask.text(f"sent to {USER} just now") == "sent to wa-…0123 just now"
    assert mask.wa_ref(USER) == "wa-…0123"


async def test_new_tables_are_added_to_an_existing_database(database):  # noqa: ANN001
    """Covers: DM-20, DM-01"""
    from voiceai import db
    from voiceai.models import Tenant

    async with sessionmaker()() as s:
        s.add(Tenant(id="t1", name="T1"))
        await s.commit()
    async with engine().begin() as conn:
        await conn.exec_driver_sql("DROP TABLE whatsapp_threads")
        await conn.exec_driver_sql("DROP TABLE whatsapp_senders")
    await db.init_db()
    async with engine().connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert {"whatsapp_senders", "whatsapp_threads"} <= set(names) and len(names) == 43
    async with sessionmaker()() as s:
        assert await s.scalar(select(func.count()).select_from(Tenant)) == 1
    async with engine().connect() as conn:
        cols = {c["name"] for c in await conn.run_sync(lambda c: inspect(c).get_columns("whatsapp_threads"))}
    assert {"address", "address_last4", "window_expires_at", "queued", "attachment_notice_sent", "last_message_sid"} <= cols


# ---------------------------------------------------------------- WA-13, WA-14
async def test_resolve_closes_with_one_message_and_the_next_message_starts_over(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-13"""
    esc_id = await escalated(client, seeded, twilio)
    r = await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "resolved_by_human", "resolution_note": "Explained the excess."})
    assert r.status_code == 200
    conv = (await conversations_())[0]
    assert conv.status == "ended" and conv.end_reason == "human_resolved"
    assert twilio.bodies() == ["This conversation has been closed by Sam. Message us again any time."]
    assert (await threads())[0].status == "ended"
    twilio.sent.clear()
    await say(client, "Hi again, what is my excess?")
    convs = await conversations_()
    assert len(convs) == 2 and convs[1].status == "active" and len(await threads()) == 2 and twilio.bodies()
    assert (await reply(client, esc_id)).json()["error"] == "conversation_ended"


async def test_no_closing_message_when_the_window_is_closed(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-13"""
    esc_id = await escalated(client, seeded, twilio)
    async with sessionmaker()() as s:
        th = (await s.scalars(select(WhatsappThread))).one()
        th.window_expires_at = utcnow() - timedelta(hours=1)
        await s.commit()
    await client.post(f"/api/escalations/{esc_id}/resolve", headers=H, json={"disposition": "resolved_by_human", "resolution_note": "Explained the excess."})
    assert twilio.sent == [] and (await conversations_())[0].status == "ended"


async def test_idle_threads_end_but_escalated_ones_stay(client, seeded, twilio):  # noqa: ANN001
    """Covers: WA-14"""
    await add_sender(seeded)
    await say(client, "Hello", user="whatsapp:+447700900124")
    await say(client, "Hello", user="whatsapp:+447700900125")
    await say(client, HUMAN, user="whatsapp:+447700900125")
    assert await whatsapp.expire_idle() == 0
    async with sessionmaker()() as s:
        for th in (await s.scalars(select(WhatsappThread))).all():
            th.last_inbound_at = utcnow() - timedelta(hours=73)
        await s.commit()
    assert await whatsapp.expire_idle() == 1
    by_user = {t.address_last4: t for t in await threads()}
    convs = {c.id: c for c in await conversations_()}
    quiet, escalated_ = convs[by_user["0124"].conversation_id], convs[by_user["0125"].conversation_id]
    assert quiet.status == "ended" and quiet.end_reason == "idle" and by_user["0124"].status == "ended"
    assert escalated_.status == "escalated" and by_user["0125"].status == "active"


# ---------------------------------------------------------------- WA-15
async def test_healthz_flag(client, seeded, twilio, monkeypatch):  # noqa: ANN001
    """Covers: WA-15"""
    assert (await client.get("/healthz")).json()["providers"]["whatsapp"] is False  # credentials but no sender row
    await add_sender(seeded)
    r = await client.get("/healthz")
    assert r.json()["providers"]["whatsapp"] is True
    assert TOKEN not in r.text and "ACtest" not in r.text and SANDBOX not in r.text
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    get_settings.cache_clear()
    assert (await client.get("/healthz")).json()["providers"]["whatsapp"] is False


# ---------------------------------------------------------------- front desk
async def test_front_desk_sender_routes_by_the_supervisor(client, seeded, twilio, indexed):  # noqa: ANN001
    """Covers: WA-03, WA-05"""
    await add_sender(seeded, front_desk=True)
    await say(client, "I want to speak to a human")  # RTE-23: never clarified, the default agent escalates
    conv = (await conversations_())[0]
    assert conv.source == "whatsapp" and conv.transport == "twilio" and twilio.bodies()
    assert twilio.bodies()[0].startswith("I'm a virtual assistant")
    assert conv.status == "escalated" and (await wa_escalation()).reason_category == "caller_requested"
