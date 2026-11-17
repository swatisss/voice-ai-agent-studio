"""CP-0051: Twilio phone warm handover - conference, brief, signed callbacks, recording rows, transcription, learning hooks, desk phone.

Twilio REST runs on an httpx MockTransport, callbacks are signed with the real X-Twilio-Signature algorithm and a test token,
the transcriber is a fake, the database is temp SQLite. No network, no credentials.

Covers: TEL-14, TEL-15, TEL-16, TEL-17, TEL-18, TEL-19, TEL-20, TEL-21, TEL-22, TEL-23, TEL-24, TEL-25, TEL-26, DM-21
"""
from __future__ import annotations

import base64
import json
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs
from xml.etree import ElementTree

import httpx
import pytest
from sqlalchemy import func, inspect, select

from tests.test_agent_desk import EMAILS, PW, _login, signin  # noqa: F401
from tests.test_learning_actions import _new_cluster, _quiet_seed_clusters
from tests.test_self_learning import ARTICLE, fake
from voiceai import handover, jobs, telephony
from voiceai.agents import validate_config
from voiceai.config import get_settings
from voiceai.db import engine, sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.models import Call, CallEvent, CallRecording, DeskPresence, Escalation, Job
from voiceai.seed import catalog
from voiceai.voice import transcribe
from voiceai.voice.transcribe import FakeTranscriber, Segment, make_wav

TOKEN = "twilio-test-token"
BASE = "https://abc123.ngrok.test"
FROM = "+15550009999"
SPECIALIST = "+919876500123"
H = {"X-Tenant-Id": "northgate-health"}
SAID = "Caller for claims. Member NGH-410237, email meera@example.com, phone 07700900123. " + "x" * 600


# ---------------------------------------------------------------- fakes
class FakeTwilio:
    """Twilio's REST API on a MockTransport: records every request, answers like Twilio would."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.legs = 0
        self.fail_update = False
        self.fail_create = False
        self.wav = make_wav([[0] * 80, [0] * 80])
        self.reject_two_channels = False
        self.fail_download = False
        self.fail_delete = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/Calls.json") and request.method == "POST":
            if self.fail_create:
                return httpx.Response(500, json={})
            self.legs += 1
            return httpx.Response(201, json={"sid": f"CAleg{self.legs}"})
        if "/Calls/" in path:
            return httpx.Response(500 if self.fail_update else 200, json={})
        if "/Recordings/" in path and request.method == "GET":
            if self.fail_download:
                return httpx.Response(500)
            if self.reject_two_channels and request.url.params.get("RequestedChannels") == "2":
                return httpx.Response(400, json={"message": "mono"})
            return httpx.Response(200, content=self.wav)
        if "/Recordings/" in path and request.method == "DELETE":
            return httpx.Response(500 if self.fail_delete else 204)
        return httpx.Response(404)

    def calls(self, suffix: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith(suffix)]

    def created(self) -> list[httpx.Request]:
        return self.calls("/Calls.json")


def form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode())


@pytest.fixture
def twilio(monkeypatch, fake_llm):  # noqa: ANN001, ANN201
    fake_llm(fake())  # jobs the handover queues (re-analysis, scoring) run on the fake LLM
    for key, value in {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": TOKEN, "PUBLIC_BASE_URL": BASE, "TWILIO_FROM_NUMBER": FROM,
                       "TWILIO_API_KEY_SID": "SKtest", "TWILIO_API_KEY_SECRET": "key-secret-test", "DEEPGRAM_API_KEY": "dg-test"}.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    fake_twilio = FakeTwilio()
    handover.set_http_client(httpx.AsyncClient(transport=httpx.MockTransport(fake_twilio.handler)))
    transcribe.set_transcriber(None)
    yield fake_twilio
    handover.set_http_client(None)
    transcribe.set_transcriber(None)
    get_settings.cache_clear()


async def make_call(seeded, *, packet=None, packet_status="ready", assignee=None, handover_meta=None, ended=True):  # noqa: ANN001, ANN201
    """An ended phone call with a waiting escalation; returns (call_id, escalation_id)."""
    async with sessionmaker()() as s:
        call = Call(tenant_id="northgate-health", agent_id=seeded["care"]["agent_id"], agent_version_id=seeded["care"]["version_id"],
                    channel="voice", status="ended" if ended else "active", outcome="escalated", started_at=utcnow() - timedelta(minutes=5),
                    ended_at=utcnow() if ended else None, end_reason="handoff" if ended else None,
                    meta={"telephony": {"provider": "twilio", "call_sid": "CAcaller", "from_last4": "4567", "to": "+15550001111"},
                          **({"handover": handover_meta} if handover_meta else {})})
        s.add(call)
        await s.flush()
        esc = Escalation(tenant_id="northgate-health", call_id=call.id, agent_id=call.agent_id, status="waiting", reason_category="caller_requested",
                         packet=packet, packet_status=packet_status, assignee=assignee)
        s.add(esc)
        await s.commit()
        return call.id, esc.id


def phone_session(call_id, telephony_cfg, escalated=True):  # noqa: ANN001, ANN201
    notes: list[tuple] = []

    async def note(text, data=None):  # noqa: ANN001, ANN202
        notes.append((text, data))

    return SimpleNamespace(config={"telephony": telephony_cfg}, state=SimpleNamespace(escalated=escalated), tenant_id="northgate-health",
                           call_id=call_id, note=note), notes


CONF = {"transfer_to": SPECIALIST, "handover": {"mode": "conference", "record": True, "ring_seconds": 30, "browser": False, "brief": True}}


async def meta_of(call_id: str) -> dict:
    async with sessionmaker()() as s:
        return dict((await s.get(Call, call_id)).meta or {})


async def events_of(call_id: str) -> list[CallEvent]:
    async with sessionmaker()() as s:
        return list((await s.scalars(select(CallEvent).where(CallEvent.call_id == call_id).order_by(CallEvent.seq))).all())


def system_texts(events: list[CallEvent]) -> list[str]:
    return [e.text for e in events if e.kind == "system"]


async def callback(client, kind: str, call_id: str, sign: bool = True, url: str | None = None, **params: str):  # noqa: ANN001, ANN201
    path = f"/api/telephony/twilio/handover/{kind}/{call_id}"
    headers = {"X-Twilio-Signature": telephony.compute_signature(TOKEN, url or BASE + path, {k: [v] for k, v in params.items()})} if sign else {}
    return await client.post(path, data=params, headers=headers)


# ---------------------------------------------------------------- TEL-14
async def test_handover_config_is_validated(client, seeded):
    """Covers: TEL-14"""
    base = (await client.get(f"/api/agents/{seeded['care']['agent_id']}", headers=H)).json()["draft_config"]
    assert base["telephony"].get("handover") is None  # an agent without handover keeps the cold transfer

    def cfg(**telephony_cfg):  # noqa: ANN202
        return {**base, "telephony": telephony_cfg}

    ok = validate_config(cfg(**CONF))
    assert ok["telephony"]["handover"] == {"mode": "conference", "record": True, "ring_seconds": 30, "browser": False, "brief": True}
    assert validate_config(cfg(transfer_to=SPECIALIST))["telephony"]["handover"] is None
    assert validate_config(cfg(handover={"mode": "conference", "browser": True}))["telephony"]["handover"]["mode"] == "conference"
    for bad in ({"mode": "teams"}, {"ring_seconds": 3}, {"ring_seconds": 200}, {"record": "yes"}, {"record": 1}):
        with pytest.raises(ApiError) as e:
            validate_config(cfg(transfer_to=SPECIALIST, handover=bad))
        assert e.value.status == 422 and e.value.error == "invalid_config", bad
    for tel in ({"handover": {"mode": "conference"}}, {"transfer_to": "sip:claims@example.com", "handover": {"mode": "conference"}}):
        with pytest.raises(ApiError) as e:
            validate_config(cfg(**tel))
        assert e.value.status == 422 and e.value.error == "handover_needs_destination"
    saved = await client.put(f"/api/agents/{seeded['care']['agent_id']}", headers=H, json={"draft_config": cfg(**CONF)})
    assert saved.status_code == 200, saved.text
    refused = await client.put(f"/api/agents/{seeded['care']['agent_id']}", headers=H, json={"draft_config": cfg(handover={"mode": "conference"})})
    assert refused.status_code == 422 and refused.json()["error"] == "handover_needs_destination"


# ---------------------------------------------------------------- TEL-15, TEL-26
async def test_conference_handover_moves_the_caller_and_rings_the_specialist(seeded, twilio):
    """Covers: TEL-15, TEL-26"""
    call_id, _ = await make_call(seeded, packet={"summary": "Wants a claim status", "intent": "claim_status", "suggested_next_action": "Check the claim"})
    session, notes = phone_session(call_id, CONF)
    await telephony.on_phone_end(session, "handoff", "CAcaller")
    update, create = twilio.requests
    assert update.url.path == "/2010-04-01/Accounts/ACtest/Calls/CAcaller.json"
    root = ElementTree.fromstring(form(update)["Twiml"][0])
    assert root[0].tag == "Say" and root[0].text == "This call may be recorded for quality and training."  # TEL-26
    conf = root.find("Dial/Conference")
    assert conf.text == f"h-{call_id}"
    assert conf.attrib["startConferenceOnEnter"] == "false" and conf.attrib["endConferenceOnExit"] == "true"
    assert conf.attrib["participantLabel"] == "caller" and conf.attrib["record"] == "record-from-start"
    assert conf.attrib["statusCallback"] == f"{BASE}/api/telephony/twilio/handover/conference/{call_id}"
    assert conf.attrib["recordingStatusCallback"] == f"{BASE}/api/telephony/twilio/handover/recording/{call_id}"
    assert create.url.path == "/2010-04-01/Accounts/ACtest/Calls.json"
    data = form(create)
    assert data["To"] == [SPECIALIST] and data["From"] == [FROM] and data["Timeout"] == ["30"]
    assert data["StatusCallback"] == [f"{BASE}/api/telephony/twilio/handover/specialist/{call_id}"]
    spec = ElementTree.fromstring(data["Twiml"][0])
    assert "claim status" in spec.find("Say").text
    leg = spec.find("Dial/Conference")
    assert leg.text == f"h-{call_id}" and leg.attrib["startConferenceOnEnter"] == "true" and leg.attrib["participantLabel"] == "specialist"
    h = (await meta_of(call_id))["handover"]
    assert h["state"] == "ringing" and h["conference"] == f"h-{call_id}" and h["caller_sid"] == "CAcaller" and list(h["legs"]) == ["CAleg1"]
    assert notes[0][0] == "handover_started"


async def test_conference_handover_without_recording_has_no_notice_or_record_attributes(seeded, twilio):
    """Covers: TEL-26"""
    call_id, _ = await make_call(seeded)
    cfg = {"transfer_to": SPECIALIST, "handover": {"mode": "conference", "record": False}}
    await telephony.on_phone_end(phone_session(call_id, cfg)[0], "handoff", "CAcaller")
    twiml = form(twilio.requests[0])["Twiml"][0]
    root = ElementTree.fromstring(twiml)
    assert root.find("Say") is None and "record" not in twiml.replace("recording", "") and "recordingStatusCallback" not in twiml


async def test_failed_caller_update_creates_no_specialist_call(seeded, twilio):
    """Covers: TEL-15"""
    twilio.fail_update = True
    call_id, _ = await make_call(seeded)
    session, notes = phone_session(call_id, CONF)
    await telephony.on_phone_end(session, "handoff", "CAcaller")  # never raises
    assert len(twilio.requests) == 1 and twilio.created() == []
    assert [n[0] for n in notes] == ["handover_started", "handover_failed"]
    assert (await meta_of(call_id))["handover"]["state"] == "failed"


# ---------------------------------------------------------------- TEL-16
async def test_dial_mode_keeps_the_cold_transfer_and_can_record(seeded, twilio):
    """Covers: TEL-16, TEL-07"""
    call_id, _ = await make_call(seeded)
    await telephony.on_phone_end(phone_session(call_id, {"transfer_to": SPECIALIST})[0], "handoff", "CAcaller")
    assert form(twilio.requests[0])["Twiml"] == [f'<?xml version="1.0" encoding="UTF-8"?><Response><Dial>{SPECIALIST}</Dial></Response>']
    assert "handover" not in await meta_of(call_id)

    twilio.requests.clear()
    call2, _ = await make_call(seeded)
    cfg = {"transfer_to": SPECIALIST, "handover": {"mode": "dial", "record": True}}
    await telephony.on_phone_end(phone_session(call2, cfg)[0], "handoff", "CAcaller")
    dial = ElementTree.fromstring(form(twilio.requests[0])["Twiml"][0]).find("Dial")
    assert dial.attrib["record"] == "record-from-answer-dual" and dial.text == SPECIALIST
    assert dial.attrib["recordingStatusCallback"] == f"{BASE}/api/telephony/twilio/handover/recording/{call2}"
    assert len(twilio.requests) == 1  # a cold transfer: no conference, no specialist call


# ---------------------------------------------------------------- TEL-17, TEL-18
RINGING = {"mode": "conference", "state": "ringing", "conference": "h-x", "caller_sid": "CAcaller", "started_at": "2026-11-16T10:00:00+00:00",
           "record": False, "join_order": ["caller"], "legs": {"CAphone": {"kind": "phone", "status": "ringing"}}}


async def test_specialist_join_connects_the_handover(client, seeded, twilio):
    """Covers: TEL-17"""
    call_id, esc_id = await make_call(seeded, handover_meta=RINGING)
    r = await callback(client, "conference", call_id, StatusCallbackEvent="participant-join", ParticipantLabel="specialist", CallSid="CAphone")
    assert r.status_code == 200 and r.content == b""
    h = (await meta_of(call_id))["handover"]
    assert h["state"] == "connected" and h["answered_by"] == "phone" and h["connected_at"]
    assert "handover_connected" in system_texts(await events_of(call_id))
    async with sessionmaker()() as s:
        assert (await s.get(Escalation, esc_id)).status == "waiting"  # a number is not a signed-in person

    browser = {**RINGING, "legs": {"CAbrowser": {"kind": "browser", "status": "ringing", "email": "specialist@echomind.test", "name": "Sam Specialist"}}}
    call2, esc2 = await make_call(seeded, handover_meta=browser)
    await callback(client, "conference", call2, StatusCallbackEvent="participant-join", ParticipantLabel="specialist", CallSid="CAbrowser")
    assert (await meta_of(call2))["handover"]["answered_by"] == "browser"
    async with sessionmaker()() as s:
        esc = await s.get(Escalation, esc2)
        assert esc.status == "accepted" and esc.assignee == "Sam Specialist"


async def test_no_answer_apologises_and_hangs_up(client, seeded, twilio):
    """Covers: TEL-18"""
    for status, state in (("no-answer", "no_answer"), ("busy", "no_answer"), ("failed", "failed")):
        twilio.requests.clear()
        call_id, esc_id = await make_call(seeded, handover_meta=RINGING)
        r = await callback(client, "specialist", call_id, CallSid="CAphone", CallStatus=status)
        assert r.status_code == 200
        h = (await meta_of(call_id))["handover"]
        assert h["state"] == state
        (update,) = twilio.calls("/Calls/CAcaller.json")
        twiml = form(update)["Twiml"][0]
        assert "colleague will call you back" in twiml and "<Hangup/>" in twiml
        failed = [e for e in await events_of(call_id) if e.text == "handover_failed"]
        assert len(failed) == 1 and failed[0].data["status"] == status
        async with sessionmaker()() as s:
            call = await s.get(Call, call_id)
            assert call.end_reason == "handoff" and (await s.get(Escalation, esc_id)).status == "waiting"
        assert twilio.created() == []  # nothing is retried
        await callback(client, "specialist", call_id, CallSid="CAphone", CallStatus=status)  # a repeat changes nothing
        assert len(twilio.calls("/Calls/CAcaller.json")) == 1


async def test_two_legs_first_to_join_wins(client, seeded, twilio):
    """Covers: TEL-18, TEL-25"""
    async with sessionmaker()() as s:
        for tenant, email, ready in (("northgate-health", "specialist@echomind.test", True), (catalog.SANDBOX_TENANT, "other@echomind.test", True),
                                     ("northgate-health", "old@echomind.test", True)):
            await handover.set_presence(s, tenant, email, ready)
        stale = await s.scalar(select(DeskPresence).where(DeskPresence.user_email == "old@echomind.test"))
        stale.updated_at = utcnow() - timedelta(seconds=120)
        await s.commit()
    call_id, _ = await make_call(seeded)
    cfg = {"transfer_to": SPECIALIST, "handover": {"mode": "conference", "browser": True}}
    await telephony.on_phone_end(phone_session(call_id, cfg)[0], "handoff", "CAcaller")
    created = twilio.created()
    assert [form(r)["To"][0] for r in created] == [SPECIALIST, "client:desk-specialist_echomind_test"]  # only the Ready one of this unit
    twilio.requests.clear()
    await callback(client, "conference", call_id, StatusCallbackEvent="participant-join", ParticipantLabel="specialist", CallSid="CAleg2")
    h = (await meta_of(call_id))["handover"]
    assert h["answered_by"] == "browser"
    (cancel,) = twilio.calls("/Calls/CAleg1.json")
    assert form(cancel)["Status"] == ["canceled"]
    await callback(client, "conference", call_id, StatusCallbackEvent="participant-join", ParticipantLabel="specialist", CallSid="CAleg1")
    assert (await meta_of(call_id))["handover"]["answered_leg"] == "CAleg2"  # the loser cannot take over


# ---------------------------------------------------------------- TEL-19
def test_brief_is_short_masked_and_xml_safe():
    """Covers: TEL-19"""
    packet = {"summary": SAID + " <b>&</b>", "intent": "claim_status", "suggested_next_action": "Call back"}
    brief = handover.build_brief(packet, "ready")
    assert len(brief) <= 300 and brief.startswith("Caller for claim status.")
    for identifier in ("NGH-410237", "meera@example.com", "07700900123"):
        assert identifier not in brief
    assert not any(ch in brief for ch in "<>&\"'")
    assert handover.build_brief(packet, "pending") == handover.GENERIC_BRIEF
    assert handover.build_brief(None, "ready") == handover.GENERIC_BRIEF
    assert handover.build_brief({"summary": "Short.", "intent": "x"}, "fallback") == "Caller for x. Short."
    assert "<Say>" not in handover.twiml_specialist("c1", None) and "<Say>hi</Say>" in handover.twiml_specialist("c1", "hi")


async def test_brief_false_has_no_say_in_the_specialist_twiml(seeded, twilio):
    """Covers: TEL-19"""
    call_id, _ = await make_call(seeded, packet={"summary": "x", "intent": "y"})
    cfg = {"transfer_to": SPECIALIST, "handover": {"mode": "conference", "brief": False}}
    await telephony.on_phone_end(phone_session(call_id, cfg)[0], "handoff", "CAcaller")
    assert ElementTree.fromstring(form(twilio.created()[0])["Twiml"][0]).find("Say") is None


# ---------------------------------------------------------------- TEL-20
async def test_callbacks_are_signed_idempotent_and_need_a_handover(client, seeded, twilio):
    """Covers: TEL-20"""
    call_id, _ = await make_call(seeded, handover_meta=RINGING)
    join = {"StatusCallbackEvent": "participant-join", "ParticipantLabel": "specialist", "CallSid": "CAphone"}
    for kind in ("specialist", "conference", "recording"):
        assert (await callback(client, kind, call_id, sign=False, **join)).status_code == 403
        assert (await callback(client, kind, call_id, url=BASE + "/other/path", **join)).status_code == 403
        assert (await callback(client, kind, "nosuchcall", **join)).status_code == 404
    plain, _ = await make_call(seeded)  # no meta.handover
    assert (await callback(client, "conference", plain, **join)).status_code == 404
    assert (await meta_of(call_id))["handover"]["state"] == "ringing"  # nothing changed so far
    assert (await callback(client, "conference", call_id, **join)).status_code == 200
    assert (await callback(client, "conference", call_id, **join)).status_code == 200
    assert system_texts(await events_of(call_id)).count("handover_connected") == 1
    end = {"StatusCallbackEvent": "conference-end"}
    await callback(client, "conference", call_id, **end)
    await callback(client, "conference", call_id, **end)
    h = (await meta_of(call_id))["handover"]
    assert h["state"] == "ended" and system_texts(await events_of(call_id)).count("handover_ended") == 1


# ---------------------------------------------------------------- TEL-21
REC = {"RecordingSid": "RE1", "RecordingStatus": "completed", "RecordingChannels": "2", "RecordingDuration": "42", "CallSid": "CAphone"}


async def test_recording_callback_creates_one_row_and_one_job(client, seeded, twilio):
    """Covers: TEL-21"""
    call_id, _ = await make_call(seeded, handover_meta={**RINGING, "join_order": ["caller", "specialist"]})
    assert (await callback(client, "recording", call_id, **REC)).status_code == 200
    assert (await callback(client, "recording", call_id, **REC)).status_code == 200
    async with sessionmaker()() as s:
        (row,) = (await s.scalars(select(CallRecording))).all()
        assert row.recording_sid == "RE1" and row.channels == 2 and row.duration_s == 42 and row.source == "conference"
        assert row.channel_map == {"1": "caller", "2": "specialist"} and row.status == "received"
        jobs_ = (await s.scalars(select(Job).where(Job.kind == "transcribe_handover"))).all()
        assert len(jobs_) == 1 and jobs_[0].payload == {"recording_id": row.id}

    inverted, _ = await make_call(seeded, handover_meta={**RINGING, "join_order": ["specialist", "caller"]})
    await callback(client, "recording", inverted, **{**REC, "RecordingSid": "RE2"})
    mono, _ = await make_call(seeded, handover_meta=RINGING)
    await callback(client, "recording", mono, **{**REC, "RecordingSid": "RE3", "RecordingChannels": "1"})
    dial, _ = await make_call(seeded, handover_meta={**RINGING, "mode": "dial", "join_order": []})
    await callback(client, "recording", dial, **{**REC, "RecordingSid": "RE4"})
    skipped, _ = await make_call(seeded, handover_meta=RINGING)
    await callback(client, "recording", skipped, **{**REC, "RecordingSid": "RE5", "RecordingStatus": "in-progress"})
    await callback(client, "recording", skipped, **{**REC, "RecordingSid": "RE6", "RecordingStatus": "absent"})
    async with sessionmaker()() as s:
        rows = {r.recording_sid: r for r in (await s.scalars(select(CallRecording))).all()}
        assert rows["RE2"].channel_map == {"1": "specialist", "2": "caller"}
        assert rows["RE3"].channel_map is None and rows["RE4"].source == "dial" and rows["RE4"].channel_map == {"1": "caller", "2": "specialist"}
        assert rows["RE5"].status == "received" and rows["RE6"].status == "failed"
        queued = {j.payload["recording_id"] for j in (await s.scalars(select(Job).where(Job.kind == "transcribe_handover"))).all()}
        assert queued == {rows[k].id for k in ("RE1", "RE2", "RE3", "RE4")}


# ---------------------------------------------------------------- TEL-22
async def recorded(client, seeded, twilio, *, channels: int = 2, assignee: str | None = "Sam Specialist"):  # noqa: ANN001, ANN201
    call_id, esc_id = await make_call(seeded, assignee=assignee, handover_meta={**RINGING, "join_order": ["caller", "specialist"]})
    await callback(client, "recording", call_id, **{**REC, "RecordingChannels": str(channels)})
    async with sessionmaker()() as s:
        row = await s.scalar(select(CallRecording).where(CallRecording.call_id == call_id))
        return call_id, esc_id, row.id


async def test_transcription_writes_the_human_portion(client, seeded, twilio):
    """Covers: TEL-22"""
    call_id, _, rid = await recorded(client, seeded, twilio)
    async with sessionmaker()() as s:
        before = (await s.scalar(select(func.max(CallEvent.seq)).where(CallEvent.call_id == call_id))) or 0
    stt = FakeTranscriber([Segment(0.0, 2.0, "Hello, I need help with a claim", "en"), Segment(9.0, 10.0, "Thanks", "en")],
                          [Segment(3.0, 6.0, "Sure, your claim was paid on Friday", "en"), Segment(7.0, 8.0, "Anything else?", "en")])
    transcribe.set_transcriber(stt)
    seen = []

    from voiceai.events import bus

    sub = bus.subscribe("northgate-health", {"console"})
    await jobs.drain()
    while not sub.queue.empty():
        seen.append(sub.queue.get_nowait())
    events = [e for e in await events_of(call_id) if e.seq > before]
    assert [(e.kind, e.text) for e in events] == [
        ("user", "Hello, I need help with a claim"), ("human", "Sure, your claim was paid on Friday"), ("human", "Anything else?"), ("user", "Thanks")]
    assert [e.seq for e in events] == sorted(e.seq for e in events) and events[0].seq == before + 1
    assert all(e.data["on_human_leg"] is True and e.data["language"] == "en" for e in events)
    assert events[1].data["author"] == "Sam Specialist" and events[1].data["start_s"] == 3.0 and events[1].data["end_s"] == 6.0
    assert events[0].at < events[1].at < events[2].at < events[3].at
    async with sessionmaker()() as s:
        row = await s.get(CallRecording, rid)
        assert row.status == "deleted" and row.transcribed_at and row.deleted_at and row.error is None
    assert [r.method for r in twilio.requests] == ["GET", "DELETE"] and twilio.requests[0].url.params["RequestedChannels"] == "2"
    assert twilio.requests[0].headers["authorization"] == "Basic " + base64.b64encode(b"SKtest:key-secret-test").decode()
    assert [e["type"] for e in seen] == ["handover.transcribed"] and seen[0]["data"] == {"call_id": call_id, "recording_id": rid}
    assert len(stt.calls) == 2 and isinstance(stt.calls[0][1], list)  # one request per channel, the agent's languages as hints

    from voiceai.handover_transcribe import transcribe_handover

    await transcribe_handover("northgate-health", {"recording_id": rid})  # running it again writes nothing
    assert len([e for e in await events_of(call_id) if e.seq > before]) == 4


async def test_mono_recording_is_labelled_mixed_and_a_400_retries_with_one_channel(client, seeded, twilio):
    """Covers: TEL-22"""
    twilio.reject_two_channels = True
    twilio.wav = make_wav([[0] * 80])
    call_id, _, rid = await recorded(client, seeded, twilio, channels=1)
    transcribe.set_transcriber(FakeTranscriber([Segment(0.0, 2.0, "Hello there", "hi"), Segment(2.0, 4.0, "Namaste", "hi")]))
    await jobs.drain()
    events = await events_of(call_id)
    mixed = [e for e in events if e.data.get("on_human_leg")]
    assert [e.kind for e in mixed] == ["human", "human"] and all(e.data["speaker"] == "mixed" for e in mixed)
    assert "recording_mono" in system_texts(events)
    assert [r.url.params.get("RequestedChannels") for r in twilio.requests if r.method == "GET"] == ["2", "1"]


async def test_recordings_are_kept_when_deletion_is_off_or_fails(client, seeded, twilio, monkeypatch):
    """Covers: TEL-22"""
    monkeypatch.setenv("TWILIO_RECORDING_DELETE", "0")
    get_settings.cache_clear()
    call_id, _, rid = await recorded(client, seeded, twilio)
    transcribe.set_transcriber(FakeTranscriber([Segment(0, 1, "a", "en")], []))
    await jobs.drain()
    async with sessionmaker()() as s:
        assert (await s.get(CallRecording, rid)).status == "transcribed"
    assert [r.method for r in twilio.requests] == ["GET"]


# ---------------------------------------------------------------- TEL-23
async def test_failed_transcription_leaves_the_call_untouched(client, seeded, twilio, monkeypatch, caplog):
    """Covers: TEL-23"""
    monkeypatch.setattr(jobs, "MAX_ATTEMPTS", 1)
    call_id, esc_id, rid = await recorded(client, seeded, twilio)
    before = len(await events_of(call_id))
    transcribe.set_transcriber(FakeTranscriber(fail=True))
    with caplog.at_level("DEBUG"):
        await jobs.drain()
    async with sessionmaker()() as s:
        row = await s.get(CallRecording, rid)
        assert row.status == "failed" and "fake transcription failure" in row.error and row.transcribed_at is None
        assert (await s.get(Escalation, esc_id)).status == "waiting" and (await s.get(Call, call_id)).end_reason == "handoff"
    assert len(await events_of(call_id)) == before
    assert "key-secret-test" not in caplog.text and "key-secret-test" not in row.error

    twilio.fail_download = True
    call2, _, rid2 = await (recorded_again(client, seeded, twilio))
    await jobs.drain()
    async with sessionmaker()() as s:
        row2 = await s.get(CallRecording, rid2)
        assert row2.status == "failed" and "HTTP 500" in row2.error


async def recorded_again(client, seeded, twilio):  # noqa: ANN001, ANN201
    call_id, esc_id = await make_call(seeded, handover_meta={**RINGING, "join_order": ["caller", "specialist"]})
    await callback(client, "recording", call_id, **{**REC, "RecordingSid": "RE9"})
    async with sessionmaker()() as s:
        row = await s.scalar(select(CallRecording).where(CallRecording.recording_sid == "RE9"))
        return call_id, esc_id, row.id


async def test_no_api_key_means_no_job_and_a_system_event(client, seeded, twilio, monkeypatch):
    """Covers: TEL-23"""
    monkeypatch.setenv("TWILIO_API_KEY_SID", "")
    get_settings.cache_clear()
    call_id, _ = await make_call(seeded, handover_meta=RINGING)
    assert (await callback(client, "recording", call_id, **REC)).status_code == 200
    assert any("not transcribed" in (t or "") for t in system_texts(await events_of(call_id)))
    async with sessionmaker()() as s:
        assert (await s.scalars(select(Job).where(Job.kind == "transcribe_handover"))).all() == []


# ---------------------------------------------------------------- TEL-24
async def test_human_portion_reaches_analysis_evidence_and_not_the_scorecard(client, seeded, twilio, fake_llm):
    """Covers: TEL-24"""
    seen: dict[str, list[str]] = {}
    fake_llm(fake(seen=seen))
    call_id, _, rid = await recorded(client, seeded, twilio)
    long_line = "Extend once, up to thirty days. " * 40
    transcribe.set_transcriber(FakeTranscriber([Segment(0, 1, "Please extend my cover abroad", "en")], [Segment(2, 3, long_line, "en")]))
    await jobs.drain()
    async with sessionmaker()() as s:
        assert (await s.scalars(select(Job).where(Job.dedupe_key == f"analyze_call:{call_id}:2"))).one().payload == {"call_id": call_id}
    # the analysis sees the human portion
    await jobs.drain()
    assert any("Specialist: Extend once" in p and "Caller (with the specialist): Please extend" in p for p in seen.get("analysis", []))

    # the drafter's evidence carries one capped line
    await _quiet_seed_clusters(seeded)
    agent_id, version_id = seeded["care"]["agent_id"], seeded["care"]["version_id"]
    from voiceai.learning import propose
    from voiceai.models import CallAnalysis

    async with sessionmaker()() as s:
        cluster = await _new_cluster(s, agent_id, version_id, "Extending cover abroad", 4)
        analysis = await s.scalar(select(CallAnalysis).where(CallAnalysis.cluster_id == cluster.id))
        s.add(CallEvent(tenant_id="northgate-health", call_id=analysis.call_id, seq=1, kind="human", text=long_line,
                        data={"on_human_leg": True, "author": "Sam"}))
        s.add(CallEvent(tenant_id="northgate-health", call_id=analysis.call_id, seq=2, kind="human", text="Not part of the call", data={"author": "Sam"}))
        await s.commit()
        evidence = await propose.cluster_evidence(s, cluster.id)
        portions = [e["human_portion"] for e in evidence if e["human_portion"]]
        assert len(portions) == 1 and 590 <= len(portions[0]) == 600 and "Not part" not in portions[0]
        await propose.draft(s, "northgate-health", cluster)
    line = next(ln for ln in seen["drafting"][-1].splitlines() if ln.startswith("- Human portion (specialist): "))
    assert len(line) == len("- Human portion (specialist): ") + 600

    # the scorecard judges the AI only
    from voiceai.learning import scoring

    judge_prompts: list[str] = []
    base_fake = fake(seen=seen)

    def judging(role, messages, tools):  # noqa: ANN001, ANN202
        if role == "judge":
            judge_prompts.append(messages[-1]["content"])
        return base_fake(role, messages, tools)

    fake_llm(judging)
    async with sessionmaker()() as s:
        s.add(CallEvent(tenant_id="northgate-health", call_id=call_id, seq=500, kind="user", text="I want to know my excess"))
        await s.commit()
        call = await s.get(Call, call_id)
        await scoring.score(s, call, always_judge=True)
    assert judge_prompts and all("Please extend my cover abroad" not in p and "Extend once" not in p for p in judge_prompts)
    assert any("I want to know my excess" in p for p in judge_prompts)


# ---------------------------------------------------------------- TEL-25
async def test_desk_phone_token_and_presence(client, seeded, twilio, signin):
    """Covers: TEL-25"""
    signin()
    await _login(client, "specialist")
    token = await client.post("/api/desk/phone-token")
    assert token.status_code == 200, token.text
    body = token.json()
    assert body["identity"] == "desk-specialist_echomind_test" and body["ttl_seconds"] == 3600 and "key-secret-test" not in token.text
    head, payload, sig = body["token"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["iss"] == "SKtest" and claims["sub"] == "ACtest" and claims["grants"] == {"identity": body["identity"], "voice": {"incoming": {"allow": True}}}
    import hashlib
    import hmac

    assert sig == base64.urlsafe_b64encode(hmac.new(b"key-secret-test", f"{head}.{payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()

    on = await client.put("/api/desk/phone-presence", json={"ready": True})
    assert on.status_code == 200 and on.json() == {"ready": True, "expires_in_s": 90}
    async with sessionmaker()() as s:
        assert [r.user_email for r in await handover.ready_specialists(s, "northgate-health")] == ["specialist@echomind.test"]
    off = await client.put("/api/desk/phone-presence", json={"ready": False})
    assert off.json() == {"ready": False, "expires_in_s": 0}
    async with sessionmaker()() as s:
        assert await handover.ready_specialists(s, "northgate-health") == []
        await handover.set_presence(s, "northgate-health", "specialist@echomind.test", True)
        row = await s.scalar(select(DeskPresence))
        row.updated_at = utcnow() - timedelta(seconds=91)  # silence ends it
        await s.commit()
        assert await handover.ready_specialists(s, "northgate-health") == []

    from voiceai import auth

    other = await client.post("/api/auth/login", json={"email": auth.REVIEWER.email, "password": PW["reviewer"]})
    assert other.status_code == 200 and (await client.post("/api/desk/phone-token")).status_code == 200  # admins and reviewers too


async def test_phone_token_is_unavailable_without_the_api_key(client, seeded, monkeypatch):
    """Covers: TEL-25"""
    monkeypatch.setenv("TWILIO_API_KEY_SID", "")
    get_settings.cache_clear()
    r = await client.post("/api/desk/phone-token", headers=H)
    assert r.status_code == 503 and r.json()["error"] == "phone_unavailable"
    assert (await client.get("/healthz")).json()["providers"]["twilio_voice_sdk"] is False
    monkeypatch.setenv("TWILIO_API_KEY_SID", "SKx")
    monkeypatch.setenv("TWILIO_API_KEY_SECRET", "s")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACx")
    get_settings.cache_clear()
    assert (await client.get("/healthz")).json()["providers"]["twilio_voice_sdk"] is True
    get_settings.cache_clear()


# ---------------------------------------------------------------- call detail, DM-21
async def test_call_detail_carries_the_handover_and_recordings(client, seeded, twilio):
    """Covers: TEL-21"""
    call_id, _, rid = await recorded(client, seeded, twilio)
    detail = (await client.get(f"/api/calls/{call_id}", headers=H)).json()
    assert detail["handover"]["mode"] == "conference" and detail["handover"]["state"] == "ringing"
    assert detail["recordings"] == [{"id": rid, "status": "received", "channels": 2, "duration_s": 42}]
    assert "http" not in json.dumps(detail["recordings"])
    plain, _ = await make_call(seeded)
    other = (await client.get(f"/api/calls/{plain}", headers=H)).json()
    assert "handover" not in other and "recordings" not in other


async def test_new_tables_and_unique_recording_sid(database):
    """Covers: DM-21"""
    async with engine().connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
        cols = await conn.run_sync(lambda c: {col["name"] for col in inspect(c).get_columns("call_recordings")})
    assert {"call_recordings", "desk_presence"} <= set(names)
    assert not {"audio", "media", "recording_url", "url"} & cols  # metadata only
    assert {"recording_sid", "channel_map", "status", "error", "transcribed_at", "deleted_at"} <= cols
    assert CallRecording.__table__.c.recording_sid.unique
