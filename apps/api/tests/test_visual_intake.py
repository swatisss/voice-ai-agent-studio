"""Visual intake: looking is an act, confidence may be withheld, and evidence is pinned.

Covers: VI-02, VI-03, VI-04, VI-05, VI-06, VI-07, VI-08, VI-09, VI-10, VI-11, VI-12, VI-13,
VI-15, DM-06, RT-10, ES-09
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from voiceai.core import blobstore as blobstore_core
from voiceai.core import framesource as framesource_core
from voiceai.core.config import Settings
from voiceai.core.db import sessionmaker
from voiceai.core.llm import gateway as gw
from voiceai.core.tables import CallEvidence, MediaObject, Tenant, VisualCase
from voiceai.modules.conversation import tools as conv_tools
from voiceai.modules.evidence import contract, domain, service
from voiceai.modules.evidence.contract import evidence_for_call, look_at_camera, packet_evidence
from voiceai.ports.framesource import RawFrame

TENANT = "evergreen-care"
OTHER = "evergreen-sandbox"
CALL = "call-video-1"
AGENT = "agent-facilities"


def _frame(width: int = 640, height: int = 480) -> RawFrame:
    return RawFrame(Image.new("RGB", (width, height), (90, 110, 130)).tobytes(), width, height, "RGB")


class FakeSource:
    """Stands in for the voice module's frame tap."""

    def __init__(self) -> None:
        self.on = False
        self.frame: RawFrame | None = None

    def camera_on(self, call_id: str) -> bool:
        return self.on

    def frame_for(self, call_id: str) -> RawFrame | None:
        return self.frame if self.on else None

    # test helpers
    def turn_on(self, frame: RawFrame | None = None) -> None:
        self.on = True
        self.frame = frame or _frame()

    def turn_off(self) -> None:
        self.on = False
        self.frame = None


@pytest.fixture
def source(monkeypatch):  # noqa: ANN001, ANN201
    fake = FakeSource()
    monkeypatch.setattr(framesource_core, "frame_source", lambda: fake)
    monkeypatch.setattr(service, "frame_source", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def local_media(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(blobstore_core, "get_settings", lambda: Settings(_env_file=None, media_dir=str(tmp_path / "media")))
    blobstore_core.reset_blob_store()
    yield
    blobstore_core.reset_blob_store()


@pytest.fixture
async def tenants(database):  # noqa: ANN001, ANN201
    async with sessionmaker()() as s:
        s.add_all([Tenant(id=TENANT, name="Evergreen"), Tenant(id=OTHER, name="Sandbox")])
        await s.commit()


def _vision(confidence: str, *, description: str = "A bed side rail is bent outward.",
            safety: str = "none", asked_for: str = "") -> dict:
    return {
        "description": description,
        "items": [{"label": "side rail", "detail": "bent outward near the hinge"}],
        "confidence": confidence, "safety_flag": safety, "asked_for": asked_for,
    }


def _case(routing: str = "needs_docs", narrative: str = "Staff reported a bent side rail.") -> dict:
    return {
        "narrative": narrative, "missing": ["Ward and bed number"],
        "routing": routing, "routing_reason": "The bed cannot be located yet.", "sample_evidence": False,
    }


def _responder(vision: dict, case: dict | None = None):  # noqa: ANN202
    """Scripted LLM: the vision role answers one way, the drafting role another."""
    def respond(role, messages, tools):  # noqa: ANN001, ANN202
        if role == "vision":
            return vision
        if role == "drafting":
            return case or _case()
        return gw.FakeReply(text="ok")

    return respond


async def _look(source: FakeSource, **over) -> contract.LookResult:  # noqa: ANN003
    ctx = {
        "tenant_id": TENANT, "call_id": CALL, "agent_id": AGENT, "case_kind": "facility_fault",
        "caller_words": "One of the bed rails is bent and will not latch.",
        "asset_hint": "ward bed", "transcript": "Caller: the rail is bent.", "caller_verified": False,
    }
    ctx.update(over)
    async with sessionmaker()() as s:
        result = await look_at_camera(s, **ctx)
        await s.commit()
    return result


# ---------------------------------------------------------------- RT-10 / VI-02: only on video
def test_the_tool_exists_only_on_a_video_call() -> None:
    """Covers: RT-10, VI-02"""
    for channel in ("voice", "text", "simulation"):
        assert "look_at_camera" not in [s["function"]["name"] for s in conv_tools.all_schemas([], channel)]
    assert "look_at_camera" in [s["function"]["name"] for s in conv_tools.all_schemas([], "video")]
    # and it is a reserved name, so a tenant tool cannot shadow it
    from voiceai.modules.agentcfg.domain import BUILTIN_TOOLS

    assert "look_at_camera" in BUILTIN_TOOLS


def test_nothing_in_the_tool_surface_enables_the_camera() -> None:
    """Covers: VI-02"""
    schema = conv_tools.LOOK_SCHEMA["function"]
    assert set(schema["parameters"]["properties"]) == {"asset_hint"}
    assert schema["parameters"].get("required", []) == []
    source = Path(service.__file__).read_text(encoding="utf-8")
    for forbidden in ("enable_camera", "set_camera", "publish_camera", "setCameraEnabled"):
        assert forbidden not in source


# ---------------------------------------------------------------- VI-03, VI-04, VI-15: declines
async def test_a_look_with_the_camera_off_is_declined(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-04"""
    gw.set_fake(_responder(_vision("confirmed")))
    result = await _look(source)  # camera never turned on
    assert result.status == "declined" and result.reason == "camera_off"
    assert result.observation is None
    told = result.for_model()
    assert told["status"] == "declined"
    assert "turn it on" in told["say"]
    async with sessionmaker()() as s:
        assert (await s.scalars(select(CallEvidence))).all() == []
        assert (await s.scalars(select(MediaObject))).all() == []


async def test_nothing_is_stored_or_modelled_without_a_look(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-03"""
    seen: list[str] = []

    def respond(role, messages, tools):  # noqa: ANN001, ANN202
        seen.append(role)
        return _vision("confirmed")

    gw.set_fake(respond)
    source.turn_on()
    # Frames keep arriving; the tap holds them, and with no look nothing happens.
    for _ in range(50):
        source.turn_on(_frame())
    assert seen == []
    async with sessionmaker()() as s:
        assert (await s.scalars(select(MediaObject))).all() == []


def test_the_tap_holds_one_frame_however_many_arrive() -> None:
    """Covers: VI-03"""
    from voiceai.modules.voice import frames

    holder = frames.register("c1")
    try:
        for i in range(40):
            holder.put(_frame(320, 240 + i))
        assert holder.frame is not None
        assert holder.frame.height == 240 + 39  # the newest one
        assert frames.InProcessFrameSource().frame_for("c1") is holder.frame
        # reading does not consume: the agent may ask twice about the same moment
        assert frames.InProcessFrameSource().frame_for("c1") is holder.frame
        assert frames.InProcessFrameSource().frame_for("unknown-call") is None
    finally:
        frames.release("c1")


def test_turning_the_camera_off_drops_the_stale_frame() -> None:
    """Covers: VI-15"""
    from voiceai.modules.voice import frames

    holder = frames.register("c2")
    try:
        holder.put(_frame())
        assert frames.InProcessFrameSource().camera_on("c2") is True
        holder.camera_off()
        assert frames.InProcessFrameSource().camera_on("c2") is False
        assert frames.InProcessFrameSource().frame_for("c2") is None
    finally:
        frames.release("c2")


async def test_a_look_after_the_camera_went_off_is_declined(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-15"""
    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    assert (await _look(source)).status == "ok"
    source.turn_off()
    second = await _look(source)
    assert second.status == "declined" and second.reason == "camera_off"


async def test_the_per_call_cap_declines_without_failing_the_call(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-04"""
    gw.set_fake(_responder(_vision("unclear", asked_for="a closer look")))
    source.turn_on()
    for _ in range(domain.MAX_FRAMES_PER_CALL):
        assert (await _look(source)).status == "ok"
    spent = await _look(source)
    assert spent.status == "declined" and spent.reason == "cap_reached"
    assert "Enough frames" in spent.for_model()["say"]


# ---------------------------------------------------------------- VI-05, VI-06, VI-07: observing
async def test_one_look_produces_one_validated_observation(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-05"""
    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    result = await _look(source)

    assert result.status == "ok"
    obs = result.observation
    assert obs.description == "A bed side rail is bent outward."
    assert obs.items[0].label == "side rail"
    assert obs.confidence == "confirmed" and obs.safety_flag == "none"
    assert obs.asked_for == ""  # a confirmed look asks for nothing
    told = result.for_model()
    assert told["confidence"] == "confirmed" and "asked_for" not in told

    async with sessionmaker()() as s:
        stored = (await s.scalars(select(MediaObject))).all()
    assert len(stored) == 1
    assert stored[0].source == "camera"
    assert max(stored[0].width, stored[0].height) <= domain.MAX_EDGE_PX


async def test_the_caller_description_is_not_taken_as_fact(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-06"""
    gw.set_fake(
        _responder(
            _vision("not_confirmed", description="The rail is straight and latched. A wheel brake is missing its lever.",
                    asked_for="a closer look at the hinge"),
            _case(narrative="Staff described a bent rail; the frame shows a straight, latched rail and a missing brake lever."),
        )
    )
    source.turn_on()
    result = await _look(source)

    obs = result.observation
    assert obs.confidence == "not_confirmed"
    assert obs.asked_for == "a closer look at the hinge"
    told = result.for_model()
    assert told["asked_for"] == "a closer look at the hinge"
    assert "do not accuse" in told["guidance"].lower()
    assert "do not describe damage the frame does not show" in told["guidance"].lower()

    # it is still pinned, and no case inherits the caller's characterisation
    async with sessionmaker()() as s:
        pinned = (await s.scalars(select(CallEvidence))).all()
        assert len(pinned) == 1 and pinned[0].confidence == "not_confirmed"
        assert "straight" in pinned[0].description
        assert (await s.scalars(select(VisualCase))).all() == []  # no confirmed look yet (VI-08)


async def test_two_looks_pin_in_order_with_the_callers_words(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-07"""
    source.turn_on()
    gw.set_fake(_responder(_vision("not_confirmed", asked_for="more light")))
    await _look(source, caller_words="It is cracked right across.")
    gw.set_fake(_responder(_vision("confirmed")))
    await _look(source, caller_words="Is this better?")

    async with sessionmaker()() as s:
        entries = await evidence_for_call(s, TENANT, CALL)
    assert [e["seq"] for e in entries] == [1, 2]
    assert [e["confidence"] for e in entries] == ["not_confirmed", "confirmed"]
    assert entries[0]["caller_words"] == "It is cracked right across."
    assert entries[1]["caller_words"] == "Is this better?"
    assert entries[0]["asked_for"] == "more light"


async def test_a_declined_look_pins_nothing(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-07"""
    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    await _look(source)
    source.turn_off()
    await _look(source)  # declined
    async with sessionmaker()() as s:
        assert len(await evidence_for_call(s, TENANT, CALL)) == 1


# ---------------------------------------------------------------- VI-08, VI-09, VI-10: the case
async def test_one_case_per_call(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-08"""
    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    first = await _look(source)
    assert first.case is not None
    second = await _look(source)
    assert second.case["id"] == first.case["id"]
    async with sessionmaker()() as s:
        assert len((await s.scalars(select(VisualCase))).all()) == 1


async def test_stated_intent_opens_the_case_before_any_confirmed_look(tenants) -> None:  # noqa: ANN001
    """Covers: VI-08"""
    assert contract.states_reporting_intent("I want to report a damaged bed") is True
    assert contract.states_reporting_intent("I'd like to report a broken hoist") is True
    assert contract.states_reporting_intent("how do I check my claim status") is False

    gw.set_fake(_responder(_vision("confirmed")))
    async with sessionmaker()() as s:
        case = await contract.open_case(
            s, tenant_id=TENANT, call_id=CALL, agent_id=AGENT, case_kind="facility_fault",
            transcript="Caller: I want to report a damaged bed.",
        )
        await s.commit()
    assert case["kind"] == "facility_fault"
    async with sessionmaker()() as s:
        assert len((await s.scalars(select(VisualCase))).all()) == 1


async def test_the_narrative_and_missing_come_from_the_draft(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-09"""
    gw.set_fake(_responder(_vision("confirmed"), _case(narrative="A captured frame shows the rail bent near its hinge.")))
    source.turn_on()
    result = await _look(source)
    assert result.case["narrative"] == "A captured frame shows the rail bent near its hinge."
    assert result.case["missing"] == ["Ward and bed number"]
    assert result.case["routing"] == "needs_docs"
    # the model is told what is still needed so it can ask in the same turn
    assert result.for_model()["case"]["missing"] == ["Ward and bed number"]


async def test_specialist_review_is_never_spoken_to_the_caller(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-10"""
    gw.set_fake(_responder(_vision("confirmed"), _case(routing="siu_review")))
    source.turn_on()
    result = await _look(source)
    assert result.case["routing"] == "siu_review"
    assert result.case["routing"] in domain.SILENT_ROUTING
    # the routing reason is for the reviewer; the model is given routing but never the words
    spoken = service.strip_silent_routing("This is going to siu_review for special investigations")
    assert "siu_review" not in spoken and "special investigations" not in spoken
    assert "specialist review" in spoken


async def test_routing_is_always_one_of_the_four(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-10"""
    gw.set_fake(_responder(_vision("confirmed"), _case(routing="ready_for_review")))
    source.turn_on()
    result = await _look(source)
    assert result.case["routing"] in ("needs_docs", "ready_for_review", "siu_review", "escalate")
    assert result.case["routing_reason"]


# ---------------------------------------------------------------- VI-12: the ticket
async def test_the_ticket_reference_is_recorded_and_never_invented(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-12"""
    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    await _look(source)

    async with sessionmaker()() as s:
        case = await contract.case_for_call(s, TENANT, CALL)
    assert case["ticket_ref"] is None  # nothing filed yet, and nothing made up

    async with sessionmaker()() as s:
        await contract.record_ticket(s, TENANT, CALL, "FF-10428")
        await s.commit()
    async with sessionmaker()() as s:
        assert (await contract.case_for_call(s, TENANT, CALL))["ticket_ref"] == "FF-10428"

    # a failed business call leaves it empty rather than guessing
    async with sessionmaker()() as s:
        await contract.record_ticket(s, TENANT, CALL, "")
        await s.commit()
    async with sessionmaker()() as s:
        assert (await contract.case_for_call(s, TENANT, CALL))["ticket_ref"] == "FF-10428"


# ---------------------------------------------------------------- VI-13: tenancy
async def test_another_tenant_sees_neither_evidence_nor_case(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-13"""
    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    await _look(source)

    async with sessionmaker()() as s:
        assert len(await evidence_for_call(s, TENANT, CALL)) == 1
        assert await contract.case_for_call(s, TENANT, CALL) is not None
        # the same ids, asked for by the wrong tenant
        assert await evidence_for_call(s, OTHER, CALL) == []
        assert await contract.case_for_call(s, OTHER, CALL) is None


# ---------------------------------------------------------------- ES-09: the packet
async def test_the_packet_carries_the_evidence_in_order(tenants, source) -> None:  # noqa: ANN001
    """Covers: ES-09"""
    source.turn_on()
    gw.set_fake(_responder(_vision("unclear", asked_for="more light")))
    await _look(source)
    gw.set_fake(_responder(_vision("confirmed")))
    await _look(source)

    async with sessionmaker()() as s:
        packet = await packet_evidence(s, TENANT, CALL)
    assert [e["confidence"] for e in packet["visual_evidence"]] == ["unclear", "confirmed"]
    assert packet["visual_evidence"][0]["asked_for"] == "more light"
    assert packet["visual_case"]["kind"] == "facility_fault"
    assert "routing" in packet["visual_case"]

    async with sessionmaker()() as s:
        assert await packet_evidence(s, TENANT, "a-call-with-no-looks") is None


# ---------------------------------------------------------------- DM-06: lifetimes split
async def test_the_finding_outlives_the_image(tenants, source) -> None:  # noqa: ANN001
    """Covers: DM-06"""
    from datetime import timedelta

    from voiceai.core.db import utcnow
    from voiceai.modules.evidence import media as media_mod

    gw.set_fake(_responder(_vision("confirmed")))
    source.turn_on()
    await _look(source)

    async with sessionmaker()() as s:
        obj = (await s.scalars(select(MediaObject))).one()
        obj.created_at = utcnow() - timedelta(days=400)
        await s.commit()
    async with sessionmaker()() as s:
        await media_mod.prune_expired(s, TENANT)
        await s.commit()

    async with sessionmaker()() as s:
        entries = await evidence_for_call(s, TENANT, CALL)
        obj = (await s.scalars(select(MediaObject))).one()
    assert obj.deleted_at is not None
    assert entries[0]["description"] and entries[0]["confidence"] == "confirmed"
    assert entries[0]["caller_words"]
    assert entries[0]["media_id"] == obj.id  # still linked, so the UI can say "image expired"


async def test_a_second_case_for_one_call_is_refused(tenants) -> None:  # noqa: ANN001
    """Covers: DM-06"""
    from sqlalchemy.exc import IntegrityError

    async with sessionmaker()() as s:
        s.add(VisualCase(tenant_id=TENANT, call_id=CALL, agent_id=AGENT, kind="claim"))
        await s.commit()
    with pytest.raises(IntegrityError):
        async with sessionmaker()() as s:
            s.add(VisualCase(tenant_id=TENANT, call_id=CALL, agent_id=AGENT, kind="claim"))
            await s.commit()


# ---------------------------------------------------------------- VI-11: safety outranks the form
async def test_an_unsafe_observation_is_flagged_for_immediate_handoff(tenants, source) -> None:  # noqa: ANN001
    """Covers: VI-11"""
    gw.set_fake(_responder(_vision("confirmed", safety="injury")))
    source.turn_on()
    result = await _look(source)

    assert result.observation.safety_flag == "injury"
    assert result.observation.is_unsafe() is True
    assert result.unsafe is True  # the turn loop escalates on this, case or no case
    async with sessionmaker()() as s:
        pinned = await evidence_for_call(s, TENANT, CALL)
    assert pinned[0]["safety_flag"] == "injury"

    for flag, unsafe in (("unsafe_premises", True), ("none", False)):
        obs = domain.Observation(description="x", confidence="confirmed", safety_flag=flag)
        assert obs.is_unsafe() is unsafe


def test_case_kind_follows_configuration_then_mode() -> None:
    """Covers: VI-08"""
    assert contract.case_kind_for({"visual": {"case_kind": "claim"}}, "internal") == "claim"
    assert contract.case_kind_for({}, "internal") == "facility_fault"
    assert contract.case_kind_for({}, "inbound") == "claim"
    assert contract.case_kind_for({"visual": {"case_kind": "nonsense"}}, "inbound") == "claim"
