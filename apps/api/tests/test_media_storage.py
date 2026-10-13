"""Captured frames: the blob-store port, the bounds, retention, and authorised access only.

Covers: MS-01, MS-02, MS-03, MS-04, MS-05, JB-06
"""
from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select

from voiceai.core import blobstore as blobstore_core
from voiceai.core import jobs
from voiceai.core.config import Settings
from voiceai.core.db import sessionmaker, utcnow
from voiceai.core.tables import CallEvidence, Job, MediaObject, Tenant
from voiceai.modules.evidence import domain, media, repo, retention
from voiceai.ports.blobstore import BlobStoreUnavailable

TENANT = "evergreen-care"
OTHER = "evergreen-sandbox"


def _raw(width: int, height: int, colour: tuple[int, int, int] = (120, 90, 60)) -> tuple[bytes, int, int]:
    """A decoded RGB frame, the shape the transport hands over."""
    return Image.new("RGB", (width, height), colour).tobytes(), width, height


def _noisy(width: int, height: int) -> tuple[bytes, int, int]:
    """A frame that does not compress, so the size bound actually bites."""
    import os

    return os.urandom(width * height * 3), width, height


@pytest.fixture(autouse=True)
def local_store(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """Point the blob store at a scratch directory for every test in this module."""
    monkeypatch.setattr(blobstore_core, "get_settings", lambda: Settings(_env_file=None, media_dir=str(tmp_path / "media")))
    blobstore_core.reset_blob_store()
    monkeypatch.setattr(media, "get_settings", lambda: Settings(_env_file=None, media_retention_days=30))
    yield
    blobstore_core.reset_blob_store()


# ---------------------------------------------------------------- MS-01: which adapter is in use
def test_local_is_the_default_and_gcs_without_a_bucket_fails(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Covers: MS-01"""
    monkeypatch.setattr(blobstore_core, "get_settings", lambda: Settings(_env_file=None, media_dir=str(tmp_path / "m")))
    blobstore_core.reset_blob_store()
    store = blobstore_core.blob_store()
    assert type(store).__name__ == "LocalBlobStore"

    # gcs selected with no bucket: a start-up error naming the setting, never a local path
    monkeypatch.setattr(
        blobstore_core, "get_settings",
        lambda: Settings(_env_file=None, media_backend="gcs", media_bucket=None, media_dir=str(tmp_path / "m")),
    )
    blobstore_core.reset_blob_store()
    with pytest.raises(BlobStoreUnavailable, match="MEDIA_BUCKET"):
        blobstore_core.blob_store()

    monkeypatch.setattr(blobstore_core, "get_settings", lambda: Settings(_env_file=None, media_backend="nowhere"))
    blobstore_core.reset_blob_store()
    with pytest.raises(BlobStoreUnavailable, match="unknown MEDIA_BACKEND"):
        blobstore_core.blob_store()


async def test_the_port_round_trips_and_deleting_twice_is_fine() -> None:
    """Covers: MS-01"""
    store = blobstore_core.blob_store()
    await store.put("t/c/one.jpg", b"bytes", "image/jpeg")
    assert await store.get("t/c/one.jpg") == b"bytes"
    await store.delete("t/c/one.jpg")
    assert await store.get("t/c/one.jpg") is None
    await store.delete("t/c/one.jpg")  # already gone is not an error
    assert not hasattr(store, "list"), "the port must not offer listing (MS-05)"
    assert not hasattr(store, "signed_url"), "the port must not sign URLs (MS-05)"


# ---------------------------------------------------------------- MS-02: bounds on the way in
def test_an_oversized_frame_is_bounded() -> None:
    """Covers: MS-02"""
    data, w, h = _raw(2600, 1400)
    encoded = domain.encode_bounded(data, w, h)
    assert max(encoded.width, encoded.height) == domain.MAX_EDGE_PX
    assert encoded.height == 689  # the aspect ratio is kept
    assert len(encoded.data) <= domain.MAX_ENCODED_BYTES
    assert encoded.data[:3] == b"\xff\xd8\xff"  # it really is JPEG
    assert encoded.content_type == "image/jpeg"


def test_a_frame_that_still_will_not_fit_is_rejected(monkeypatch) -> None:  # noqa: ANN001
    """Covers: MS-02"""
    # Bound the encoded size absurdly low so even the retry cannot satisfy it; nothing is written.
    monkeypatch.setattr(domain, "MAX_ENCODED_BYTES", 200)
    data, w, h = _noisy(900, 700)
    with pytest.raises(domain.FrameTooLarge):
        domain.encode_bounded(data, w, h)


def test_a_small_frame_passes_through_unresized() -> None:
    """Covers: MS-02"""
    data, w, h = _raw(640, 480)
    encoded = domain.encode_bounded(data, w, h)
    assert (encoded.width, encoded.height) == (640, 480)
    assert Image.open(io.BytesIO(encoded.data)).size == (640, 480)


# ---------------------------------------------------------------- MS-03: the per-call cap
async def test_the_per_call_frame_cap_counts_stored_rows(database) -> None:  # noqa: ANN001
    """Covers: MS-03"""
    async with sessionmaker()() as s:
        s.add(Tenant(id=TENANT, name="Evergreen"))
        await s.commit()
    frame = domain.encode_bounded(*_raw(320, 240))
    async with sessionmaker()() as s:
        for _ in range(domain.MAX_FRAMES_PER_CALL):
            await media.store_frame(s, tenant_id=TENANT, call_id="call-1", frame=frame, source="camera")
        await s.commit()
        assert await repo.frames_stored(s, TENANT, "call-1") == domain.MAX_FRAMES_PER_CALL
        assert await repo.frames_stored(s, TENANT, "call-2") == 0
        assert await repo.frames_stored(s, OTHER, "call-1") == 0  # another tenant sees none


# ---------------------------------------------------------------- MS-04: retention
async def test_retention_removes_bytes_and_keeps_the_finding(database) -> None:  # noqa: ANN001
    """Covers: MS-04"""
    async with sessionmaker()() as s:
        s.add(Tenant(id=TENANT, name="Evergreen"))
        await s.commit()
    frame = domain.encode_bounded(*_raw(400, 300))
    async with sessionmaker()() as s:
        old = await media.store_frame(s, tenant_id=TENANT, call_id="c1", frame=frame, source="camera")
        fresh = await media.store_frame(s, tenant_id=TENANT, call_id="c1", frame=frame, source="camera")
        await repo.add_evidence(
            s, tenant_id=TENANT, call_id="c1", media_id=old.id, source="camera",
            description="A bed side rail is bent outward.", items=[{"label": "side rail", "detail": "bent"}],
            confidence="confirmed", safety_flag="none", asked_for="", caller_words="The rail will not latch.",
        )
        old.created_at = utcnow() - timedelta(days=31)
        old_key, fresh_key = old.store_key, fresh.store_key
        await s.commit()

    async with sessionmaker()() as s:
        assert await media.prune_expired(s, TENANT) == 1
        await s.commit()

    store = blobstore_core.blob_store()
    assert await store.get(old_key) is None   # the bytes are gone
    assert await store.get(fresh_key) is not None  # the fresh one is untouched

    async with sessionmaker()() as s:
        row = await s.scalar(select(MediaObject).where(MediaObject.store_key == old_key))
        assert row is not None and row.deleted_at is not None  # the row outlives the bytes
        pinned = (await s.scalars(select(CallEvidence).where(CallEvidence.call_id == "c1"))).all()
        assert len(pinned) == 1
        kept = pinned[0]
        assert kept.description == "A bed side rail is bent outward."
        assert kept.confidence == "confirmed"
        assert kept.caller_words == "The rail will not latch."


async def test_retention_is_scoped_to_its_tenant(database) -> None:  # noqa: ANN001
    """Covers: MS-04"""
    async with sessionmaker()() as s:
        s.add_all([Tenant(id=TENANT, name="A"), Tenant(id=OTHER, name="B")])
        await s.commit()
    frame = domain.encode_bounded(*_raw(200, 200))
    async with sessionmaker()() as s:
        mine = await media.store_frame(s, tenant_id=TENANT, call_id="c1", frame=frame, source="camera")
        theirs = await media.store_frame(s, tenant_id=OTHER, call_id="c2", frame=frame, source="camera")
        mine.created_at = theirs.created_at = utcnow() - timedelta(days=90)
        await s.commit()
    async with sessionmaker()() as s:
        assert await media.prune_expired(s, TENANT) == 1  # only this tenant's
        await s.commit()
    async with sessionmaker()() as s:
        assert (await s.scalar(select(MediaObject).where(MediaObject.tenant_id == OTHER))).deleted_at is None


# ---------------------------------------------------------------- JB-06: the job re-arms itself
async def test_prune_media_re_enqueues_itself_exactly_once(database) -> None:  # noqa: ANN001
    """Covers: JB-06"""
    async with sessionmaker()() as s:
        s.add(Tenant(id=TENANT, name="Evergreen"))
        await s.commit()

    assert retention.KIND in jobs.DECLARED_KINDS
    await retention.prune_media(TENANT, {})

    async def queued() -> list[Job]:
        async with sessionmaker()() as s:
            return list((await s.scalars(select(Job).where(Job.kind == retention.KIND))).all())

    rows = await queued()
    assert len(rows) == 1
    assert rows[0].status == "queued"
    ahead = rows[0].run_after - utcnow()
    assert timedelta(hours=5) < ahead <= timedelta(hours=6, minutes=1)

    await retention.prune_media(TENANT, {})  # running again must not pile up a second one
    assert len(await queued()) == 1


async def test_arming_at_start_up_covers_every_tenant(database) -> None:  # noqa: ANN001
    """Covers: JB-06"""
    async with sessionmaker()() as s:
        s.add_all([Tenant(id=TENANT, name="A"), Tenant(id=OTHER, name="B")])
        await s.commit()
    await retention.arm_all()
    await retention.arm_all()  # idempotent
    async with sessionmaker()() as s:
        rows = list((await s.scalars(select(Job).where(Job.kind == retention.KIND))).all())
    assert sorted(r.tenant_id for r in rows) == [TENANT, OTHER]


# ---------------------------------------------------------------- MS-05: authorised access only
async def test_media_is_readable_only_by_its_own_tenant(client, seeded) -> None:  # noqa: ANN001
    """Covers: MS-05, VI-13"""
    frame = domain.encode_bounded(*_raw(320, 240))
    async with sessionmaker()() as s:
        row = await media.store_frame(s, tenant_id=TENANT, call_id="c1", frame=frame, source="camera")
        media_id, key = row.id, row.store_key
        await s.commit()

    mine = {"X-Tenant-Id": TENANT}
    theirs = {"X-Tenant-Id": OTHER}

    ok = await client.get(f"/api/media/{media_id}", headers=mine)
    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("image/jpeg")
    assert "no-store" in ok.headers.get("cache-control", "")
    assert ok.content[:3] == b"\xff\xd8\xff"

    # another tenant's id is indistinguishable from one that never existed
    assert (await client.get(f"/api/media/{media_id}", headers=theirs)).status_code == 404
    assert (await client.get("/api/media/does-not-exist", headers=mine)).status_code == 404

    # and once retention has removed the bytes, so is an expired one
    async with sessionmaker()() as s:
        obj = await s.scalar(select(MediaObject).where(MediaObject.id == media_id))
        obj.created_at = utcnow() - timedelta(days=31)
        await s.commit()
    async with sessionmaker()() as s:
        await media.prune_expired(s, TENANT)
        await s.commit()
    assert (await client.get(f"/api/media/{media_id}", headers=mine)).status_code == 404
    assert await blobstore_core.blob_store().get(key) is None


def test_the_api_offers_no_url_minting_route(app) -> None:  # noqa: ANN001
    """Covers: MS-05"""
    from voiceai.modules.evidence import api as media_api

    paths = {r.path for r in media_api.router.routes}
    assert paths == {"/api/media/{media_id}"}
    source = Path(media_api.__file__).read_text(encoding="utf-8")
    for forbidden in ("generate_signed_url", "signed_url", "make_public", "public_url"):
        assert forbidden not in source


def test_store_keys_are_not_guessable(tmp_path) -> None:  # noqa: ANN001
    """Covers: MS-05"""
    first = media.store_key(TENANT, "call-1")
    second = media.store_key(TENANT, "call-1")
    assert first != second
    assert first.startswith(f"{TENANT}/call-1/") and first.endswith(".jpg")


async def test_a_key_escaping_the_store_is_refused(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """Covers: MS-05"""
    store = blobstore_core.blob_store()
    with pytest.raises(BlobStoreUnavailable):
        await store.put("../../escaped.jpg", b"x", "image/jpeg")
