---
type: Change Proposal
title: CP-0031 Website knowledge sources
description: A builder gives one URL; the platform indexes that page or the whole site section (sitemap or links, robots.txt respected), keeps headings, cites the page, re-syncs on a schedule so the agent answers from the live site, and refuses internal addresses.
status: draft
cp_state: proposed
tags: [knowledge, rag, ui, api, security]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

Most business units already publish what callers ask about: help centres, policy pages, FAQs. Today **From URL** ([/architecture/knowledge.md](/architecture/knowledge.md)) fetches exactly one page once:

* it keeps `h1`–`h3` as Markdown headings and drops `nav`, `footer` and scripts, but keeps site headers, sidebars and forms, and turns list items into bare lines;
* a help centre of 40 pages needs 40 pastes, and nothing tells the builder which pages exist;
* the copy never changes again: when the site is updated, the agent keeps answering from the old text until someone notices;
* any address is fetched, including `localhost`, private networks and cloud metadata endpoints, which on a hosted multi-tenant platform is a server-side request forgery risk.

The product owner asked for a live feature: give a URL, the platform indexes it, and the agent answers from it. Competitors offer site crawling and scheduled re-sync (Retell re-crawls every 24 hours; see [/product/roadmap.md](/product/roadmap.md)).

# What changes

1. **Website sources.** In the Knowledge tab, **From URL** asks for a URL and a scope: *Just this page* or *This site section* (the start URL's host and path prefix, up to a page limit, default 25, at most 100), plus **Keep in sync**: *Off*, *Daily* or *Weekly* (default *Daily*). The platform creates a **knowledge source** and indexes it in the background; the dialog closes at once and the source row shows *Indexing… 7 of 19 pages*.
2. **Discovery.** For a section, pages come from the site's `sitemap.xml` (and sitemap indexes) when it lists pages in scope; otherwise links are followed breadth-first from the start page, depth at most 3, same host and path prefix only, without query strings or fragments. `robots.txt` is respected for the platform's user agent and `*`. Requests are sequential with at least 500 ms between them.
3. **Structure kept.** The existing conversion is extended and written down. HTML becomes Markdown: `h1`–`h3` become `#`–`###`, lists and paragraphs stay, and `nav`, `header`, `footer`, `aside`, `form`, `script`, `style` and `noscript` are dropped. So the existing chunker splits a page by its headings. Each page becomes one knowledge doc of the source (`source_type: url`, the page URL in `source_ref`). The same conversion applies to single-page imports.
4. **Answers from it.** The builder ticks the source as a whole (all its pages). A source added from an agent's Knowledge tab is ticked for that agent at once. Search results from a website page carry the page `url`; Test search and the call detail show it as a link. The agent never reads URLs aloud (prompt rule unchanged).
5. **Live.** A source with *Daily* or *Weekly* re-sync is fetched again on schedule, or at once with **Sync now**. Changed pages are re-chunked, new pages within the limit are added, and pages gone twice in a row (404/410) are archived. Because an agent version holds the *source*, not its page copies, **published agents answer from the latest synced content without a republish**. Every `search_knowledge` event already records the chunk ids it used (KN-07); each chunk keeps the page's content hash, so a call's answer remains traceable after a page changes.
6. **Safe fetching.** Only `http` and `https`. Every hop of every request (including redirects, at most 5) is resolved and refused when it reaches a loopback, private, link-local, multicast, reserved or cloud-metadata address, unless the setting `KNOWLEDGE_ALLOW_PRIVATE_URLS` is `true` (`.env.example` sets it for local development and the demo; the deploy script never does). Pages over 2 MB, non-HTML/text responses and responses slower than 10 s are skipped and listed with the reason.
7. **Self-learning respects the website.** A drafted fix never edits a website page (`knowledge_edit` is not offered for them); it proposes a new article instead, since the website is the source of truth for its pages.

# Affected specs

* [/architecture/knowledge.md](/architecture/knowledge.md) - website sources, discovery, HTML to Markdown, sync, safe fetching, page URL in results (KN-09…KN-15)
* [/data/data-model.md](/data/data-model.md) - table `knowledge_sources`, `knowledge_docs.source_id` and `content_hash` (DM-01 changed to 36 tables, DM-12)
* [/data/agent-config.md](/data/agent-config.md) - `knowledge_source_ids`
* [/api/rest-api.md](/api/rest-api.md) - `/api/knowledge/sources` endpoints (API-14)
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - job `sync_knowledge_source`
* [/architecture/self-learning.md](/architecture/self-learning.md) - no `knowledge_edit` for website pages (SL-14)
* [/ui/agent-builder.md](/ui/agent-builder.md) - From URL dialog, source rows, page links (UI-66)

# Acceptance criteria

New, each written in its spec: KN-09…KN-15 in [/architecture/knowledge.md](/architecture/knowledge.md); DM-12 and the changed DM-01 in [/data/data-model.md](/data/data-model.md); API-14 in [/api/rest-api.md](/api/rest-api.md); SL-14 in [/architecture/self-learning.md](/architecture/self-learning.md); UI-66 in [/ui/agent-builder.md](/ui/agent-builder.md).

# Tasks

1. Spec edits (done in this CP).
2. `voiceai/knowledge/html.py`: HTML to Markdown (headings, lists, dropped regions) — covers KN-09.
3. `voiceai/knowledge/fetch.py`: safe fetcher (scheme, per-hop address check, redirects, size, type, timeout, user agent) used by both single-page import and sources — covers KN-13.
4. `voiceai/knowledge/sources.py`: create, discover (sitemap, links, robots.txt, scope, limit), index, sync (hash compare, add, archive after two misses) — covers KN-10, KN-11, KN-12, KN-14.
5. Data model: `knowledge_sources`, `knowledge_docs.source_id`, `knowledge_chunks.content_hash` with additive migration — covers DM-01, DM-12.
6. Search resolves `knowledge_source_ids` to their active pages and adds `url` to results — covers KN-15.
7. Job `sync_knowledge_source` and the scheduler for daily and weekly sources; `/api/knowledge/sources` routes — covers API-14.
8. Fix drafting skips website pages for `knowledge_edit` — covers SL-14.
9. Web: From URL dialog (scope, page limit, keep in sync), source rows with status, progress, pages and **Sync now**, URL links in Test search — covers UI-66.
10. `.env.example` (`KNOWLEDGE_ALLOW_PRIVATE_URLS=true` with a local-only comment), deploy script (never sets it).
11. Tests: a local HTTP fixture site (index, three pages, sitemap, robots.txt disallowing one page) served from the test process; address-guard cases with a stubbed resolver; no external network.
12. [Demo walkthrough](/product/demo-walkthrough.md): step 3 switches from the single-page import to a site section, and the automated run checks the page count and a fact from the second page.

# Risks and rollout

* **Content that changes under a version.** Published agents answer from the latest synced pages. This is the point of the feature, but it means a website edit changes agent behavior without a review. Mitigation: sync history on the source (pages added, changed, archived per run), chunk hashes on retrieval events, and *Keep in sync: Off* for teams that want frozen content (then a re-sync is manual).
* **Crawling third-party sites.** Only pages under the start URL's host and path; robots.txt respected; a fixed, identifiable user agent; a 500 ms gap; at most 100 pages per source.
* **Indexing time.** 25 pages take about 15–40 s including embeddings; indexing runs as a job and never blocks the request.
* **Migration.** Additive (new table and nullable columns); existing `url` docs stay as they are, without a source.
* **JavaScript-rendered sites** return little text without a browser; they are listed as *skipped: no readable text*. A headless browser is out of scope.

# Out of scope

* Logins, cookies, paywalls and JavaScript rendering.
* Crawling outside the start URL's host and path prefix, or more than 100 pages.
* PDF links found while crawling (upload them separately).
* Change review before synced content goes live (a later option: *Hold changes for review*).
