"""Website knowledge sources: one URL becomes a set of page docs that stays in sync.

Spec: /architecture/knowledge.md (Website sources), /architecture/jobs-and-events.md (sync_knowledge_source)
"""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from collections import deque
from datetime import timedelta
from typing import Any
from urllib import robotparser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from voiceai import jobs
from voiceai.db import sessionmaker, utcnow
from voiceai.errors import ApiError
from voiceai.knowledge import fetch, html
from voiceai.knowledge.ingest import content_hash, create_doc, rechunk
from voiceai.knowledge.search import invalidate
from voiceai.models import Agent, Job, KnowledgeDoc, KnowledgeSource

log = logging.getLogger("voiceai.knowledge.sources")

JOB = "sync_knowledge_source"
REQUEST_GAP_S = 0.5     # at least this long between two requests to a site
MAX_DEPTH = 3           # link discovery depth from the start page
MAX_SITEMAPS = 3        # sitemap files read per sync (index plus children)
GONE = (404, 410)
REFRESH = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


# ------------------------------------------------------------------ URLs and scope
def normalize(url: str) -> str:
    """Without query string and fragment, host in lower case (/architecture/knowledge.md, Discovery)."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "", ""))


def scope_prefix(start_url: str) -> tuple[str, str]:
    parts = urlsplit(normalize(start_url))
    return parts.netloc, parts.path[: parts.path.rfind("/") + 1] or "/"


def in_scope(url: str, start_url: str) -> bool:
    host, prefix = scope_prefix(start_url)
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and parts.netloc == host and parts.path.startswith(prefix)


# ------------------------------------------------------------------ discovery helpers
async def _robots(client: httpx.AsyncClient, start_url: str) -> robotparser.RobotFileParser:
    parser = robotparser.RobotFileParser()
    try:
        page = await fetch.fetch(urljoin(start_url, "/robots.txt"), client=client)
        parser.parse(page.text.splitlines())
    except fetch.FetchError:
        parser.parse([])  # a missing robots.txt allows everything
    return parser


async def _sitemap_urls(client: httpx.AsyncClient, start_url: str) -> list[str]:
    """In-scope page URLs from /sitemap.xml, following sitemap indexes, at most MAX_SITEMAPS files."""
    queue, read, out = [urljoin(start_url, "/sitemap.xml")], 0, []
    while queue and read < MAX_SITEMAPS:
        url = queue.pop(0)
        read += 1
        try:
            page = await fetch.fetch(url, client=client, accept=fetch.TEXT_TYPES + fetch.XML_TYPES)
            root = ET.fromstring(page.text.encode("utf-8"))
        except (fetch.FetchError, ET.ParseError):
            continue
        for el in root.iter():
            if not el.tag.endswith("loc") or not (el.text or "").strip():
                continue
            loc = el.text.strip()
            if root.tag.endswith("sitemapindex"):
                queue.append(loc)
            else:
                out.append(normalize(loc))
    seen: list[str] = []
    for u in out:
        if in_scope(u, start_url) and u not in seen:
            seen.append(u)
    return seen


# ------------------------------------------------------------------ the sync job
class _Run:
    def __init__(self) -> None:
        self.added = self.changed = self.unchanged = self.archived = 0
        self.skipped: list[dict[str, str]] = []
        self.gone: set[str] = set()

    def as_dict(self) -> dict[str, Any]:
        return {"added": self.added, "changed": self.changed, "unchanged": self.unchanged, "archived": self.archived,
                "skipped": self.skipped[:50]}


async def _store_page(s: AsyncSession, source: KnowledgeSource, url: str, page: html.Page,
                      pages: dict[str, KnowledgeDoc], run: _Run) -> None:
    digest = content_hash(page.markdown)
    doc = pages.get(url)
    if doc is None:
        doc = await create_doc(s, source.tenant_id, page.title, page.markdown, "url", url, {"url": url}, source_id=source.id)
        pages[url] = doc
        run.added += 1
        return
    doc.miss_count = 0
    if doc.status == "active" and content_hash(doc.content) == digest:
        run.unchanged += 1
        return
    doc.title, doc.content, doc.status = page.title[:300], page.markdown, "active"
    await rechunk(s, doc)
    run.changed += 1


async def sync(source_id: str) -> None:
    """Fetch the source's pages, add new ones, re-chunk changed ones, archive pages gone twice (KN-10…KN-14)."""
    async with sessionmaker()() as s:
        source = await s.get(KnowledgeSource, source_id)
        if source is None or source.status == "archived":
            return
        source.status = "indexing"
        await s.commit()
        pages = {d.source_ref: d for d in (await s.scalars(select(KnowledgeDoc).where(
            KnowledgeDoc.source_id == source.id, KnowledgeDoc.status != "archived"))).all()}
        run = _Run()
        indexed: set[str] = set()
        found: set[str] = set()  # in scope and allowed, including pages over the limit
        failed_error: str | None = None
        async with fetch.new_client() as client:
            robots = await _robots(client, source.start_url)
            allowed = lambda u: robots.can_fetch(fetch.ROBOTS_AGENT, u)  # noqa: E731
            start = normalize(source.start_url)
            sitemap = await _sitemap_urls(client, source.start_url) if source.scope == "section" else []
            follow_links = source.scope == "section" and not sitemap
            queue: deque[tuple[str, int]] = deque([(start, 0)])
            if sitemap:
                queue.extend((u, 1) for u in sitemap if u != start)
            seen = {start, *sitemap}
            # pages indexed earlier but not discovered now are checked too, so a removed page is noticed (KN-14)
            queue.extend((u, MAX_DEPTH) for u in pages if u not in seen)
            seen.update(pages)
            first = True
            while queue:
                url, depth = queue.popleft()
                if not allowed(url):
                    continue
                found.add(url)
                if len(indexed) >= source.max_pages:
                    continue  # counted as found, not fetched
                if not first:
                    await asyncio.sleep(REQUEST_GAP_S)
                first = False
                try:
                    got = await fetch.fetch(url, client=client)
                except fetch.FetchError as exc:
                    if exc.status in GONE:
                        run.gone.add(url)
                    else:
                        run.skipped.append({"url": url, "reason": exc.detail})
                    if url == start and not pages and exc.status not in GONE:
                        failed_error = exc.detail
                    continue
                page = html.to_markdown(got.text, url) if "html" in got.content_type else html.Page(url, got.text.strip())
                if follow_links and depth < MAX_DEPTH:
                    for href in page.links:
                        nxt = normalize(urljoin(got.url, href))
                        if nxt not in seen and in_scope(nxt, source.start_url):
                            seen.add(nxt)
                            queue.append((nxt, depth + 1))
                if not html.readable(page):
                    run.skipped.append({"url": url, "reason": "no readable text"})
                    continue
                await _store_page(s, source, url, page, pages, run)
                indexed.add(url)
                source.page_count = sum(1 for d in pages.values() if d.status == "active")
                await s.commit()  # the builder shows the page count rising
        for url, doc in pages.items():
            if url in indexed or doc.status != "active":
                continue
            if url in run.gone:
                doc.miss_count = (doc.miss_count or 0) + 1
                if doc.miss_count >= 2:
                    doc.status = "archived"
                    run.archived += 1
        found_total = len(found - run.gone)
        active = sum(1 for d in pages.values() if d.status == "active")
        source.page_count, source.found_count = active, found_total
        source.last_run, source.last_synced_at = run.as_dict(), utcnow()
        source.next_sync_at = source.last_synced_at + REFRESH[source.refresh] if source.refresh in REFRESH else None
        if failed_error and not active:
            source.status, source.error = "failed", failed_error
        else:
            source.status = "partial" if found_total > source.max_pages else "ready"
            source.error = None
        invalidate()
        await s.commit()
        log.info("source %s synced: %s", source.id, run.as_dict())


@jobs.register(JOB)
async def sync_job(tenant_id: str, payload: dict[str, Any]) -> None:
    await sync(payload["source_id"])


# ------------------------------------------------------------------ queueing and scheduling
async def sync_pending(s: AsyncSession, source_id: str) -> bool:
    return bool(await s.scalar(select(Job.id).where(
        Job.kind == JOB, Job.payload["source_id"].as_string() == source_id, Job.status.in_(("queued", "running"))).limit(1)))


async def queue_sync(s: AsyncSession, source: KnowledgeSource) -> Job:
    """At most one sync per source is queued or running (API-14: 409 sync_in_progress). Caller commits."""
    if await sync_pending(s, source.id):
        raise ApiError(409, "sync_in_progress", "This source is already being synced")
    source.status = "indexing"
    return await jobs.enqueue(s, source.tenant_id, JOB, {"source_id": source.id})


async def schedule_due() -> int:
    """Queue every daily or weekly source whose next sync is due (the job worker calls this once a minute)."""
    queued = 0
    async with sessionmaker()() as s:
        due = (await s.scalars(select(KnowledgeSource).where(
            KnowledgeSource.refresh != "off", KnowledgeSource.status != "archived",
            KnowledgeSource.next_sync_at.is_not(None), KnowledgeSource.next_sync_at <= utcnow()))).all()
        for source in due:
            if not await sync_pending(s, source.id):
                await queue_sync(s, source)
                queued += 1
        await s.commit()
    return queued


# ------------------------------------------------------------------ used by agents and search
async def page_ids(s: AsyncSession, tenant_id: str, source_ids: list[str]) -> list[str]:
    """The active page docs of the given sources, resolved at query time so syncs reach published agents (KN-15)."""
    if not source_ids:
        return []
    return list((await s.scalars(select(KnowledgeDoc.id).where(
        KnowledgeDoc.tenant_id == tenant_id, KnowledgeDoc.source_id.in_(source_ids), KnowledgeDoc.status == "active"))).all())


async def archive_source(s: AsyncSession, source: KnowledgeSource) -> None:
    """Archive the source and its pages and take it out of every draft config."""
    source.status = "archived"
    for doc in (await s.scalars(select(KnowledgeDoc).where(KnowledgeDoc.source_id == source.id))).all():
        doc.status = "archived"
    for agent in (await s.scalars(select(Agent).where(Agent.tenant_id == source.tenant_id))).all():
        ids = list((agent.draft_config or {}).get("knowledge_source_ids") or [])
        if source.id in ids:
            agent.draft_config = {**agent.draft_config, "knowledge_source_ids": [i for i in ids if i != source.id]}
    invalidate()
