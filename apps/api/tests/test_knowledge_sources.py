"""Website knowledge sources: HTML to Markdown, discovery, robots.txt, page limits, safe fetching, sync and live search.

Covers: KN-09, KN-10, KN-11, KN-12, KN-13, KN-14, KN-15, DM-12, API-14, SL-14

The fixture site is served in-process through httpx.MockTransport and a stub resolver: no network, no sockets.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect, select, text

from voiceai import db, jobs
from voiceai.config import get_settings
from voiceai.db import sessionmaker
from voiceai.knowledge import fetch, html, sources
from voiceai.knowledge.ingest import create_doc, text_from_url
from voiceai.llm.gateway import FakeReply
from voiceai.models import AgentVersion, Job, KnowledgeChunk, KnowledgeDoc, KnowledgeSource, Tenant
from voiceai.runtime.session import AgentSession, create_call

H = {"X-Tenant-Id": "northgate-health"}
BASE = "http://help.northgate.test"
PUBLIC_IP = "93.184.216.34"


def page(title: str, body: str) -> str:
    return (f"<html><head><title>{title}</title></head><body><header><h1>Northgate Help Centre</h1></header>"
            f"<nav><a href='/help/'>Home</a> <a href='/help/gadgets.html'>Gadgets</a></nav><main>{body}</main>"
            "<footer>Northgate is fictional.</footer></body></html>")


GADGETS = page("Gadget cover", "<h1>Gadget cover</h1><h2>What is covered</h2><p>Phones and laptops stolen on a trip are covered up to £500 per item.</p>"
               "<h2>How to claim</h2><p>Report a theft to the police within 24 hours and attach the police report.</p>")
RENTAL = page("Rental car excess", "<h1>Rental car excess</h1><p>The rental excess you paid is refunded up to £3,000 per trip.</p>")
MEDICAL = page("Medical help abroad", "<h1>Medical help abroad</h1><p>Call the assistance line within 48 hours of a hospital admission.</p>")
INDEX = page("Northgate Help Centre", "<h1>Help home</h1><p>Answers for Northgate policyholders, by topic.</p><ul>"
             "<li><a href='gadgets.html'>Gadgets</a></li><li><a href='rental-car.html?ref=home'>Rental cars</a></li>"
             "<li><a href='medical-abroad.html#top'>Medical</a></li><li><a href='private/notes.html'>Staff</a></li>"
             "<li><a href='/blog/news.html'>Blog</a></li></ul>")


class Site:
    """A small help centre: path -> (status, content type, body); every request is logged."""

    def __init__(self, sitemap: bool = True) -> None:
        self.pages: dict[str, tuple[int, str, str]] = {
            "/help/": (200, "text/html", INDEX), "/help/gadgets.html": (200, "text/html", GADGETS),
            "/help/rental-car.html": (200, "text/html", RENTAL), "/help/medical-abroad.html": (200, "text/html", MEDICAL),
            "/help/private/notes.html": (200, "text/html", page("Staff", "<p>Internal notes the indexer must never fetch.</p>")),
            "/blog/news.html": (200, "text/html", page("News", "<p>Blog post outside the help section of the site.</p>")),
            "/robots.txt": (200, "text/plain", "User-agent: *\nDisallow: /help/private/\n"),
        }
        if sitemap:
            locs = "".join(f"<url><loc>{BASE}{p}</loc></url>" for p in
                           ("/help/", "/help/gadgets.html", "/help/rental-car.html", "/help/medical-abroad.html", "/blog/news.html"))
            self.pages["/sitemap.xml"] = (200, "application/xml",
                                          f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{locs}</urlset>')
        self.requests: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path == "/go-inside":
            return httpx.Response(302, headers={"location": "http://intranet.test/secret"})
        status, ctype, body = self.pages.get(request.url.path, (404, "text/html", "not found"))
        return httpx.Response(status, headers={"content-type": ctype}, text=body)


ADDRESSES = {"help.northgate.test": [PUBLIC_IP], "loopback.test": ["127.0.0.1"], "intranet.test": ["10.0.0.5"],
             "metadata.test": ["169.254.169.254"]}


@pytest.fixture
def site(monkeypatch) -> Site:  # noqa: ANN001
    s = Site()

    async def resolve(host: str, port: int) -> list[str]:
        return ADDRESSES.get(host, [PUBLIC_IP])

    monkeypatch.setattr(fetch, "resolver", resolve)
    monkeypatch.setattr(fetch, "transport", httpx.MockTransport(s.handle))
    monkeypatch.setattr(sources, "REQUEST_GAP_S", 0)
    return s


async def _tenant() -> None:
    async with sessionmaker()() as s:
        if not await s.get(Tenant, "t1"):
            s.add(Tenant(id="t1", name="T1"))
            await s.commit()


async def _source(start: str = f"{BASE}/help/", **kw) -> str:  # noqa: ANN003
    await _tenant()
    async with sessionmaker()() as s:
        src = KnowledgeSource(tenant_id="t1", start_url=start, **kw)
        s.add(src)
        await s.commit()
        return src.id


async def _pages(source_id: str, status: str = "active") -> dict[str, KnowledgeDoc]:
    async with sessionmaker()() as s:
        docs = (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.source_id == source_id, KnowledgeDoc.status == status))).all()
        return {d.source_ref: d for d in docs}


async def _get(source_id: str) -> KnowledgeSource:
    async with sessionmaker()() as s:
        return await s.get(KnowledgeSource, source_id)


async def test_html_becomes_markdown_with_headings(database, site):
    """Covers: KN-09"""
    converted = html.to_markdown(GADGETS)
    md = converted.markdown
    assert converted.title == "Gadget cover"
    assert md.count("\n## ") == 2 and md.startswith("# Gadget cover")
    assert "Northgate Help Centre" not in md and "Gadgets" not in md and "fictional" not in md  # header, nav, footer dropped
    title, content = await text_from_url(f"{BASE}/help/gadgets.html")
    await _tenant()
    async with sessionmaker()() as s:
        doc = await create_doc(s, "t1", title, content, "url", f"{BASE}/help/gadgets.html")
        await s.commit()
        chunks = (await s.scalars(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc.id))).all()
    assert {"What is covered", "How to claim"} <= {c.heading.split(" > ")[-1] for c in chunks}


async def test_sitemap_section_indexes_in_scope_pages(database, site):
    """Covers: KN-10"""
    site.pages["/help/"] = (200, "text/html", INDEX.replace("<li><a href='medical-abroad.html#top'>Medical</a></li>", ""))  # only the sitemap lists it
    sid = await _source()
    await sources.sync(sid)
    pages = await _pages(sid)
    assert set(pages) == {f"{BASE}/help/", f"{BASE}/help/gadgets.html", f"{BASE}/help/rental-car.html", f"{BASE}/help/medical-abroad.html"}
    src = await _get(sid)
    assert src.status == "ready" and src.page_count == 4 and f"{BASE}/blog/news.html" not in site.requests


async def test_links_robots_and_duplicate_urls(database, site):
    """Covers: KN-11"""
    del site.pages["/sitemap.xml"]
    sid = await _source()
    await sources.sync(sid)
    pages = await _pages(sid)
    assert set(pages) == {f"{BASE}/help/", f"{BASE}/help/gadgets.html", f"{BASE}/help/rental-car.html", f"{BASE}/help/medical-abroad.html"}
    assert not any("/private/" in u for u in site.requests)  # robots.txt disallows it: never requested
    assert not any("ref=home" in u for u in site.requests) and sum(u.endswith("/rental-car.html") for u in site.requests) == 1


async def test_page_limit_makes_a_partial_source(database, site):
    """Covers: KN-12"""
    sid = await _source(max_pages=2)
    await sources.sync(sid)
    src = await _get(sid)
    assert len(await _pages(sid)) == 2 and src.page_count == 2 and src.found_count == 4 and src.status == "partial"


@pytest.mark.parametrize("host", ["loopback.test", "intranet.test", "metadata.test"])
async def test_internal_addresses_are_refused(database, site, host):
    """Covers: KN-13"""
    with pytest.raises(fetch.FetchError) as err:
        await fetch.fetch(f"http://{host}/help/")
    assert err.value.code == "blocked_address" and site.requests == []
    with pytest.raises(fetch.FetchError) as err:  # a public page that redirects inside
        await fetch.fetch(f"{BASE}/go-inside")
    assert err.value.code == "blocked_address" and site.requests == [f"{BASE}/go-inside"]


async def test_private_urls_allowed_by_setting(database, site, monkeypatch):
    """Covers: KN-13"""
    monkeypatch.setenv("KNOWLEDGE_ALLOW_PRIVATE_URLS", "1")
    get_settings.cache_clear()
    try:
        got = await fetch.fetch("http://loopback.test/help/gadgets.html")
        assert got.status == 200 and "Gadget cover" in got.text
    finally:
        monkeypatch.setenv("KNOWLEDGE_ALLOW_PRIVATE_URLS", "0")
        get_settings.cache_clear()


async def test_sync_changes_adds_and_archives_after_two_misses(database, site):
    """Covers: KN-14"""
    sid = await _source()
    await sources.sync(sid)
    before = await _pages(sid)
    async with sessionmaker()() as s:
        chunk_ids = {d: set((await s.scalars(select(KnowledgeChunk.id).where(KnowledgeChunk.doc_id == doc.id))).all()) for d, doc in before.items()}
        old_hash = await s.scalar(select(KnowledgeChunk.content_hash).where(KnowledgeChunk.doc_id == before[f"{BASE}/help/gadgets.html"].id))
    site.pages["/help/gadgets.html"] = (200, "text/html", GADGETS.replace("£500", "£750"))  # changed
    site.pages["/help/visa.html"] = (200, "text/html", page("Visa", "<h1>Visa refusals</h1><p>A refused visa is a covered reason to cancel.</p>"))
    site.pages["/sitemap.xml"] = (200, "application/xml", site.pages["/sitemap.xml"][2].replace(
        "</urlset>", f"<url><loc>{BASE}/help/visa.html</loc></url></urlset>"))  # new
    del site.pages["/help/medical-abroad.html"]  # gone (404)
    await sources.sync(sid)
    after = await _pages(sid)
    async with sessionmaker()() as s:
        new_hash = await s.scalar(select(KnowledgeChunk.content_hash).where(KnowledgeChunk.doc_id == after[f"{BASE}/help/gadgets.html"].id))
        rental_ids = set((await s.scalars(select(KnowledgeChunk.id).where(KnowledgeChunk.doc_id == after[f"{BASE}/help/rental-car.html"].id))).all())
    assert new_hash != old_hash and "£750" in after[f"{BASE}/help/gadgets.html"].content
    assert rental_ids == chunk_ids[f"{BASE}/help/rental-car.html"]  # unchanged page keeps its chunks
    assert f"{BASE}/help/visa.html" in after
    assert f"{BASE}/help/medical-abroad.html" in after  # one miss: still active
    run = (await _get(sid)).last_run
    assert run["added"] == 1 and run["changed"] == 1 and run["archived"] == 0
    await sources.sync(sid)
    assert f"{BASE}/help/medical-abroad.html" not in await _pages(sid)
    assert f"{BASE}/help/medical-abroad.html" in await _pages(sid, "archived")


async def test_published_agent_answers_from_the_latest_sync(client, seeded, fake_llm, site):
    """Covers: KN-15"""
    fake_llm(lambda role, messages, tools: FakeReply(text="Okay."))
    created = (await client.post("/api/knowledge/sources", headers=H, json={"start_url": f"{BASE}/help/gadgets.html", "scope": "page"})).json()
    await jobs.drain()
    agent_id = seeded["care"]["agent_id"]
    draft = (await client.get(f"/api/agents/{agent_id}", headers=H)).json()["draft_config"]
    draft["knowledge_source_ids"] = [created["id"]]
    assert (await client.put(f"/api/agents/{agent_id}", headers=H, json={"draft_config": draft})).status_code == 200
    version = (await client.post(f"/api/agents/{agent_id}/publish", headers=H, json={})).json()

    async def ask() -> dict:
        async with sessionmaker()() as s:
            call = await create_call(s, "northgate-health", agent_id, "text")
            await s.commit()
        session = await AgentSession.open(call.id, "northgate-health")
        return json.loads(await session._run_tool("c1", "search_knowledge", json.dumps(
            {"query": "Gadget cover phones laptops stolen trip covered per item"})))

    first = (await ask())["results"][0]
    assert "£500" in first["content"] and first["url"] == f"{BASE}/help/gadgets.html"
    site.pages["/help/gadgets.html"] = (200, "text/html", GADGETS.replace("£500", "£750"))
    assert (await client.post(f"/api/knowledge/sources/{created['id']}/sync", headers=H)).status_code == 202
    await jobs.drain()
    second = (await ask())["results"][0]
    assert "£750" in second["content"] and second["url"] == f"{BASE}/help/gadgets.html"
    versions = (await client.get(f"/api/agents/{agent_id}/versions", headers=H)).json()["items"]
    assert versions[0]["id"] == version["id"]  # no new version


async def test_sources_api(client, seeded, site):
    """Covers: API-14"""
    r = await client.post("/api/knowledge/sources", headers=H, json={"start_url": f"{BASE}/help/", "max_pages": 25, "refresh": "daily"})
    assert r.status_code == 202 and r.json()["status"] == "indexing"
    sid = r.json()["id"]
    async with sessionmaker()() as s:
        assert len((await s.scalars(select(Job).where(Job.kind == "sync_knowledge_source"))).all()) == 1
    again = await client.post(f"/api/knowledge/sources/{sid}/sync", headers=H)
    assert again.status_code == 409 and again.json()["error"] == "sync_in_progress"
    await jobs.drain()
    got = (await client.get(f"/api/knowledge/sources/{sid}", headers=H)).json()
    assert got["status"] == "ready" and got["page_count"] == 4 and len(got["pages"]) == 4 and got["next_sync_at"]
    assert all(p["url"].startswith(f"{BASE}/help/") and p["content_hash"] for p in got["pages"])
    assert (await client.get(f"/api/knowledge/sources/{sid}", headers={"X-Tenant-Id": "northgate-sandbox"})).status_code == 404
    blocked = await client.post("/api/knowledge/sources", headers=H, json={"start_url": "http://intranet.test/wiki/"})
    assert blocked.status_code == 422 and blocked.json()["error"] == "blocked_address"
    assert (await client.delete(f"/api/knowledge/sources/{sid}", headers=H)).status_code == 204
    assert all(d.status == "archived" for d in (await _pages(sid, "archived")).values()) and await _pages(sid) == {}


async def test_old_database_gains_the_source_columns(tmp_path: Path):
    """Covers: DM-12"""
    db.configure(f"sqlite+aiosqlite:///{(tmp_path / 'old.sqlite').as_posix()}")
    async with db.engine().begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE tenants (id VARCHAR(64) PRIMARY KEY, name VARCHAR(200), industry VARCHAR(100), created_at DATETIME)")
        await conn.exec_driver_sql(
            "CREATE TABLE knowledge_docs (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), title VARCHAR(300), "
            "source_type VARCHAR(16), source_ref VARCHAR(500), content TEXT, meta JSON, status VARCHAR(16), created_at DATETIME NOT NULL)")
        await conn.exec_driver_sql(
            "CREATE TABLE knowledge_chunks (id VARCHAR(32) PRIMARY KEY, tenant_id VARCHAR(64) NOT NULL REFERENCES tenants(id), "
            "doc_id VARCHAR(32) REFERENCES knowledge_docs(id) ON DELETE CASCADE, ordinal INTEGER, heading VARCHAR(500), content TEXT, embedding JSON)")
        await conn.exec_driver_sql("INSERT INTO tenants VALUES ('t', 'T', '', '2026-10-01 00:00:00')")
        await conn.exec_driver_sql("INSERT INTO knowledge_docs VALUES ('d1', 't', 'Cards', 'text', '', 'Digital cards.', '{}', 'active', '2026-10-01 00:00:00')")
        await conn.exec_driver_sql("INSERT INTO knowledge_chunks VALUES ('c1', 't', 'd1', 0, '', 'Digital cards.', '[0.0]')")
    await db.init_db()
    async with db.engine().begin() as conn:
        docs = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("knowledge_docs")})
        chunks = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("knowledge_chunks")})
        assert {"source_id", "miss_count", "updated_at"} <= docs and "content_hash" in chunks
        assert (await conn.execute(text("SELECT source_id, miss_count FROM knowledge_docs"))).one() == (None, 0)
        assert (await conn.execute(text("SELECT content_hash FROM knowledge_chunks"))).one() == (None,)
    await db.engine().dispose()


async def test_drafts_never_edit_a_website_page(client, seeded, fake_llm, site):
    """Covers: SL-14"""
    from tests.test_learning import _cluster, responder

    created = (await client.post("/api/knowledge/sources", headers=H, json={"start_url": f"{BASE}/help/newborn.html", "scope": "page"})).json()
    site.pages["/help/newborn.html"] = (200, "text/html", page("Adding a newborn", "<h1>Adding a newborn to the policy</h1>"
                                                               "<p>Add your baby to your health policy within 3 months of birth.</p>"))
    await jobs.drain()
    page_doc = next(iter((await _pages(created["id"])).values()))
    async with sessionmaker()() as s:
        version = await s.get(AgentVersion, seeded["care"]["version_id"])
        version.config = {**version.config, "knowledge_source_ids": [created["id"]]}
        await s.commit()
    base = responder()

    def drafting_edits_the_page(role, messages, tools):  # noqa: ANN001, ANN202
        if role == "drafting" and "These are short descriptions" not in messages[-1]["content"]:
            assert page_doc.id in messages[-1]["content"]  # the page is shown to the drafter as context
            return {"kind": "knowledge_edit", "doc_id": page_doc.id, "title": "Adding a newborn", "rationale": "Three-month rule.",
                    "article": {"title": "Adding a newborn", "content_markdown": "# Adding a newborn\nWithin 3 months of birth."}}
        return base(role, messages, tools)

    fake_llm(drafting_edits_the_page)
    newborn = await _cluster(client, "Adding a newborn to the policy")
    assert (await client.post(f"/api/insights/clusters/{newborn['id']}/draft-fix", headers=H)).status_code == 200
    await jobs.drain()
    proposal = (await client.get(f"/api/insights/clusters/{newborn['id']}", headers=H)).json()["proposals"][0]
    assert proposal["kind"] == "knowledge_article" and "doc_id" not in proposal["payload"]
    async with sessionmaker()() as s:
        assert (await s.get(KnowledgeDoc, page_doc.id)).status == "active"
