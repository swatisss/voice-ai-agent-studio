"""Ward assets, facility faults and claim intake: the business writes a visual call makes.

Covers: MOCK-13, MOCK-14, MOCK-15, IMG-01, IMG-06
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from voiceai.modules.businessmock import data

M = {"X-Tenant-Id": "evergreen-care"}
JAMES = {**M, "X-Member-Ref": "EVG-337120"}  # motor policy MP-200415


# ---------------------------------------------------------------- MOCK-13: ward assets
async def test_a_ward_asset_needs_no_member_header(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-13"""
    r = await client.get("/mock/internal/assets/BED-4012", headers=M)
    assert r.status_code == 200
    body = r.json()
    assert body["asset_tag"] == "BED-4012"
    assert body["ward"] == 4 and body["bed"] == 12
    assert body["kind"] == "electric profiling bed"

    # the tag is normalised like every other identifier in this API
    assert (await client.get("/mock/internal/assets/bed 4012", headers=M)).json()["asset_tag"] == "BED-4012"
    assert (await client.get("/mock/internal/assets/bed_4012", headers=M)).json()["asset_tag"] == "BED-4012"


async def test_an_unknown_asset_tag_is_a_404(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-13"""
    r = await client.get("/mock/internal/assets/BED-9999", headers=M)
    assert r.status_code == 404
    assert r.json()["error"] == "asset_not_found"
    assert "BED-4012" in r.json()["assets"]  # the escalation path knows what does exist


# ---------------------------------------------------------------- MOCK-14: facility faults
async def test_a_fault_report_returns_a_reference(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-14"""
    r = await client.post(
        "/mock/internal/facility-faults", headers=M,
        json={"location": "ward 4 bed 12", "summary": "The side rail is bent near its hinge.",
              "severity": "high", "asset_tag": "bed-4012", "evidence_ref": "case-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reference"].startswith("FF-") and body["status"] == "open"
    assert body["queue"] == "Facilities urgent"

    stored = data.FACILITY_FAULTS[-1]
    assert stored["asset_tag"] == "BED-4012"
    assert stored["evidence_ref"] == "case-1"  # the ticket traces back to the evidence (VI-12)


async def test_an_unknown_severity_is_rejected(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-14"""
    r = await client.post(
        "/mock/internal/facility-faults", headers=M,
        json={"location": "ward 2", "summary": "The hoist strap is frayed.", "severity": "catastrophic"},
    )
    assert r.status_code == 422
    assert r.json()["error"] == "invalid_severity"
    assert "high" in r.json()["severities"]


async def test_references_do_not_repeat(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-14"""
    refs = set()
    for _ in range(3):
        r = await client.post(
            "/mock/internal/facility-faults", headers=M,
            json={"location": "ward 1", "summary": "A chair castor is broken.", "severity": "low"},
        )
        refs.add(r.json()["reference"])
    assert len(refs) == 3


# ---------------------------------------------------------------- MOCK-15: claim intake
async def test_claim_intake_opens_a_claim(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-15"""
    r = await client.post(
        "/mock/insurance/claims/intake", headers=JAMES,
        json={"policy_id": "MP-200415", "item": "rear car door",
              "summary": "The rear door is dented and the trim is cracked.",
              "incident_date": (date.today() - timedelta(days=2)).isoformat(), "evidence_ref": "case-7"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["reference"].startswith("C-") and body["status"] == "received"
    assert body["next_step"]
    assert data.CLAIM_INTAKES[-1]["evidence_ref"] == "case-7"


async def test_claim_intake_needs_a_verified_member(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-15"""
    r = await client.post(
        "/mock/insurance/claims/intake", headers=M,
        json={"policy_id": "MP-200415", "item": "door", "summary": "Dented.", "incident_date": "2026-10-01"},
    )
    assert r.status_code == 401 and r.json()["error"] == "member_not_verified"


async def test_claim_intake_refuses_another_members_policy(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-15"""
    r = await client.post(
        "/mock/insurance/claims/intake", headers={**M, "X-Member-Ref": "EVG-482913"},
        json={"policy_id": "MP-200415", "item": "door", "summary": "Dented.", "incident_date": "2026-10-01"},
    )
    assert r.status_code == 404 and r.json()["error"] == "policy_not_found"


async def test_claim_intake_rejects_a_future_incident_date(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-15"""
    r = await client.post(
        "/mock/insurance/claims/intake", headers=JAMES,
        json={"policy_id": "MP-200415", "item": "door", "summary": "Dented.",
              "incident_date": (date.today() + timedelta(days=3)).isoformat()},
    )
    assert r.status_code == 422 and r.json()["error"] == "incident_date_in_future"

    bad = await client.post(
        "/mock/insurance/claims/intake", headers=JAMES,
        json={"policy_id": "MP-200415", "item": "door", "summary": "Dented.", "incident_date": "whenever"},
    )
    assert bad.status_code == 422 and bad.json()["error"] == "invalid_incident_date"


async def test_claim_intake_refuses_an_inactive_policy(client, database) -> None:  # noqa: ANN001
    """Covers: MOCK-15"""
    data.POLICIES["MP-200415"]["status"] = "lapsed"
    r = await client.post(
        "/mock/insurance/claims/intake", headers=JAMES,
        json={"policy_id": "MP-200415", "item": "door", "summary": "Dented.", "incident_date": "2026-10-01"},
    )
    assert r.status_code == 409 and r.json()["error"] == "policy_not_active"


# ---------------------------------------------------------------- IMG-01, IMG-06
def test_nothing_in_the_product_generates_an_image() -> None:
    """Covers: IMG-01"""
    package = Path(__file__).resolve().parents[1] / "voiceai"
    offenders: list[str] = []
    for path in package.rglob("*.py"):
        source = path.read_text(encoding="utf-8").lower()
        for marker in ("images.generate", "image_generation", "dall-e", "dalle", "text_to_image", "stable-diffusion"):
            if marker in source:
                offenders.append(f"{path.name}: {marker}")
    assert offenders == [], offenders
    # and no role asks a model for an image
    from voiceai.core.llm.gateway import ROLES

    assert all("image" not in role for role in ROLES)


def test_the_seeded_imagery_is_the_declared_set() -> None:
    """Covers: IMG-06"""
    from voiceai.modules.evidence import assets

    samples = assets.sample_images()
    references = assets.reference_images()
    assert set(samples) == {"bed-rail", "footplate", "ceiling-tile", "car-door"}
    assert len(references) == 6
    for label, path in {**samples, **references}.items():
        assert path.is_file(), f"{label} missing at {path}"
        assert path.suffix == ".jpg"
        assert path.read_bytes()[:3] == b"\xff\xd8\xff", f"{label} is not a JPEG"
    assert assets.sample_path("bed-rail") is not None
    assert assets.sample_path("not-a-sample") is None


# ---------------------------------------------------------------- IMG-02..IMG-05
async def test_a_sample_image_is_tagged_sample_the_whole_way_down(client, seeded, tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Covers: IMG-04, IMG-05"""
    from sqlalchemy import select

    from voiceai.core import blobstore as blobstore_core
    from voiceai.core.config import Settings
    from voiceai.core.db import sessionmaker
    from voiceai.core.llm import gateway as gw
    from voiceai.core.tables import MediaObject
    from voiceai.modules.evidence.contract import case_for_call, evidence_for_call, look_at_sample

    monkeypatch.setattr(blobstore_core, "get_settings", lambda: Settings(_env_file=None, media_dir=str(tmp_path / "m")))
    blobstore_core.reset_blob_store()

    def respond(role, messages, tools):  # noqa: ANN001, ANN202
        if role == "vision":
            return {"description": "A bed side rail is bent.", "items": [], "confidence": "confirmed",
                    "safety_flag": "none", "asked_for": ""}
        return {"narrative": "A bent rail.", "missing": [], "routing": "ready_for_review",
                "routing_reason": "Enough to act on.", "sample_evidence": False}

    gw.set_fake(respond)
    async with sessionmaker()() as s:
        result = await look_at_sample(
            s, "bed-rail", tenant_id="evergreen-care", call_id="c-sample", agent_id="a1",
            case_kind="facility_fault", caller_words="Like this one.",
        )
        await s.commit()

    assert result.status == "ok"
    async with sessionmaker()() as s:
        entries = await evidence_for_call(s, "evergreen-care", "c-sample")
        case = await case_for_call(s, "evergreen-care", "c-sample")
        obj = (await s.scalars(select(MediaObject).where(MediaObject.call_id == "c-sample"))).one()
    assert entries[0]["source"] == "sample"          # tagged on the evidence entry
    assert obj.source == "sample"                    # and on the stored object
    assert case["sample_evidence"] is True           # the case says so, whatever the model returned
    blobstore_core.reset_blob_store()


async def test_an_unknown_sample_is_declined(client, seeded) -> None:  # noqa: ANN001
    """Covers: IMG-04"""
    from voiceai.core.db import sessionmaker
    from voiceai.modules.evidence.contract import look_at_sample

    async with sessionmaker()() as s:
        result = await look_at_sample(
            s, "not-a-real-sample", tenant_id="evergreen-care", call_id="c-x", agent_id="a1",
            case_kind="claim",
        )
    assert result.status == "declined"


async def test_a_reference_choice_is_never_evidence(client, seeded) -> None:  # noqa: ANN001
    """Covers: IMG-02, IMG-03"""
    from sqlalchemy import select

    from voiceai.core.db import sessionmaker
    from voiceai.core.llm import gateway as gw
    from voiceai.core.tables import MediaObject
    from voiceai.modules.evidence.contract import evidence_for_call, note_reference_choice

    gw.set_fake(lambda role, messages, tools: {
        "narrative": "Staff say it resembles a bent side rail; no photograph yet.",
        "missing": ["A photograph of the rail"], "routing": "needs_docs",
        "routing_reason": "No image has been captured.", "sample_evidence": False,
    })
    async with sessionmaker()() as s:
        case = await note_reference_choice(
            s, "rail-bent", tenant_id="evergreen-care", call_id="c-ref", agent_id="a1",
            case_kind="facility_fault", transcript="Caller: the rail is bent.",
        )
        await s.commit()

    assert case["routing"] == "needs_docs"
    assert "photograph" in " ".join(case["missing"]).lower()
    async with sessionmaker()() as s:
        assert await evidence_for_call(s, "evergreen-care", "c-ref") == []   # nothing pinned
        assert (await s.scalars(select(MediaObject).where(MediaObject.call_id == "c-ref"))).all() == []


async def test_at_most_three_references_are_offered(client, seeded) -> None:  # noqa: ANN001
    """Covers: IMG-02"""
    r = await client.get("/api/media/samples/catalog", headers=M)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["references"]) <= 3
    assert {s["key"] for s in body["samples"]} == {"bed-rail", "footplate", "ceiling-tile", "car-door"}
    assert all(s["label"] for s in body["samples"])
