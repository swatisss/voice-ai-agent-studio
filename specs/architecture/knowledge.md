---
type: Component Spec
title: Knowledge
description: Knowledge ingestion from text, files, URLs and OKF bundles; heading-aware chunking; local embeddings; cosine search with a no-answer threshold.
status: draft
tags: [architecture, knowledge, rag, okf]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Sources

| `source_type` | Input | Notes |
|---|---|---|
| `text` | title + Markdown/plain text body | Pasted in the builder |
| `file` | `.md`, `.txt`, `.pdf` upload (≤ 5 MB) | PDF text via `pypdf` |
| `url` | http(s) URL | One page, fetched with the safe fetcher (below), converted from HTML to Markdown, `<title>` used as title. A page indexed by a website source is also a `url` doc, with `source_id` set |
| `okf` | `.zip` of an OKF bundle, or a server path (seed only) | Every non-reserved `.md` with frontmatter becomes one doc; `title` from frontmatter (else filename); `type`, `tags`, `description` stored in `doc.meta`; frontmatter removed from content |

Docs belong to a tenant. An agent uses the docs listed in its config `knowledge_doc_ids` and the active pages of the website sources listed in `knowledge_source_ids` ([/data/agent-config.md](/data/agent-config.md)). Doc `status`: `active` (usable), `draft` (only visible to evaluation candidates), `archived`.

# Website sources

A **knowledge source** of kind `website` turns one URL into a set of page docs that stays current ([CP-0031](/changes/cp-0031-website-knowledge-sources.md)). Fields (table `knowledge_sources`, [/data/data-model.md](/data/data-model.md)): `start_url`, `scope` (`page` or `section`), `max_pages` (1–100, default 25), `refresh` (`off`, `daily`, `weekly`; default `daily`), `status` (`indexing`, `ready`, `partial`, `failed`), `last_synced_at`, `next_sync_at`, `page_count`, `found_count` (pages found in scope, including those over the limit), `last_run` (pages added, changed, unchanged, archived, skipped with reasons).

## Discovery

* `scope: page` indexes the start URL only.
* `scope: section` covers URLs on the start URL's host whose path starts with the start URL's path up to its last `/`. Pages come from `/sitemap.xml` (following sitemap indexes, at most 3 files) when it lists at least one in-scope URL; otherwise links are followed breadth-first from the start page to depth 3. Query strings and fragments are removed and URLs are de-duplicated.
* `/robots.txt` is read once per sync; URLs disallowed for the user agent `VoiceAgentStudio` or `*` are never fetched. A missing robots.txt allows everything.
* Pages are fetched one at a time with at least 500 ms between requests, until `max_pages` pages have been indexed.

## Safe fetching

Every fetch (single-page imports and sources) goes through one fetcher: scheme `http` or `https` only; user agent `VoiceAgentStudio/1.0 (+knowledge indexer)`; timeout 10 s; at most 2 MB; content types `text/html` and `text/plain`; at most 5 redirects. Before each request and each redirect hop the host is resolved and the request is refused with `blocked_address` when any resolved address is loopback, private, link-local, multicast, reserved, unspecified or the cloud metadata address `169.254.169.254`. The setting `KNOWLEDGE_ALLOW_PRIVATE_URLS` (default `false`) lifts the address rule for local development and the demo; `.env.example` sets it to `true` with a "local development only" comment and the deploy script never sets it. A single-page import that fails answers 422 (`invalid_url`, `blocked_address`, `fetch_failed`, `unsupported_content`); a source records skipped pages with the reason and continues.

## HTML to Markdown

`<h1>`–`<h3>` become `#`–`###` lines, `<h4>`–`<h6>` bold lines, `<li>` lines `- `, `<p>`, `<br>` and block elements paragraph breaks; text inside `nav`, `header`, `footer`, `aside`, `form`, `script`, `style`, `noscript` and `template` is dropped; entities are decoded; runs of blank lines collapse. The page title is `<title>`, else the first `#` line, else the URL. A page with fewer than 40 characters of text is skipped (`no readable text`).

## Sync

Indexing and every re-sync run as the job `sync_knowledge_source` ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)); at most one runs per source. A sync fetches the discovered pages and compares each page's Markdown by SHA-256 `content_hash`:

* unchanged → nothing changes; changed → the doc's content is replaced and re-chunked (new chunk ids, new hash); new in scope and under the limit → a new doc;
* a page answering 404 or 410 on two consecutive syncs → its doc is archived; other errors keep the last good copy and are listed in `last_run`.

`refresh: daily` or `weekly` sets `next_sync_at` 24 h or 7 days after the last sync; the scheduler queues due sources once a minute. **Sync now** queues a sync at once (409 `sync_in_progress` while one runs). Because agent versions hold `knowledge_source_ids` rather than page copies, a published agent answers from the latest synced pages without a new version; retrieval events keep chunk ids and each chunk its `content_hash`, so an old answer stays traceable. Deleting a source archives its pages and removes it from every draft config.

# Chunking

1. Split on Markdown headings (`#`–`###`); each chunk keeps its heading path (e.g. `Claims > Timelines`) in `heading`.
2. Sections longer than 900 characters are split on paragraph boundaries into ≤ 900-character pieces with 120 characters of overlap.
3. Chunks shorter than 40 characters are merged into the previous chunk.
4. The text embedded is `"{doc title} — {heading}\n{content}"`.

# Embeddings

* `EMBEDDINGS_PROVIDER=fastembed` (default): `BAAI/bge-small-en-v1.5`, 384 dims, L2-normalized, model cached under `FASTEMBED_CACHE` (default `.cache/fastembed`).
* `EMBEDDINGS_PROVIDER=hash`: deterministic 384-dim hashed bag-of-words (tests, offline). Lower quality.
* Embeddings are stored with each chunk as JSON float arrays. Queries use the same provider. Changing provider requires `voiceai reindex`.

# Search

`search(tenant_id, doc_ids, query, top_k=4)`:

1. Embed the query; cosine similarity against all chunks of `doc_ids` (NumPy, in memory, cached per doc set and invalidated on doc changes).
2. Keep results with score ≥ `KN_MIN_SCORE` (default **0.60** for fastembed, 0.15 for hash).
3. If none remain → `{"no_answer": true, "message": "No approved information found for this question."}`.
4. Else → `{"results": [{"chunk_id", "doc_id", "title", "heading", "content", "score"}]}`, best first, at most `top_k`; a result from a website page also carries its `url`. `content` is the whole chunk (at most 900 characters, see Chunking); neither search nor the runtime shortens it on its way to the model, so every sentence the chunker stored can be used ([CP-0030](/changes/cp-0030-knowledge-judge-verification-fixes.md)).

The runtime stores each search in the `search_knowledge` tool-result event as `data.retrieval`: `{query, no_answer, chunks: [{chunk_id, doc_id, score}]}`, so [call scoring](/architecture/call-scoring.md) and the call detail can cite the exact chunks.

The runtime treats `no_answer` as a signal for the no-answer streak ([/architecture/escalation.md](/architecture/escalation.md)) and the analysis treats it as evidence of `missing_knowledge`.

# Acceptance

- **KN-01** — Given a Markdown doc with three `##` sections, when ingested, then three chunks are stored with their heading paths.
- **KN-02** — Given a section of 2,000 characters, when chunked, then every chunk is ≤ 900 characters and consecutive chunks overlap.
- **KN-03** — Given an OKF zip containing `index.md`, `log.md` and two concept files, when imported, then exactly two docs are created and frontmatter is stripped from their content.
- **KN-04** — Given a query unrelated to any doc, when searched, then the result is `no_answer`.
- **KN-05** — Given docs not listed in the agent's `knowledge_doc_ids`, when the agent searches, then those docs are never returned.
- **KN-07** — Given a call in which the agent searched knowledge, then the `search_knowledge` tool-result event's `data.retrieval` holds the query and the returned chunk ids and scores (or `no_answer: true` and no chunks).
- **KN-08** — Given a doc whose single chunk is 880 characters long with a fact in its last sentence, when a search returns that chunk, then the result's `content` is the full chunk and the `search_knowledge` tool result the model receives contains the last sentence.
- **KN-09** — Given an HTML page with a `<nav>`, a `<footer>`, an `<h1>` and two `<h2>` sections, when it is imported as a single page, then the doc's content is Markdown with one `#` and two `##` headings and no text from the nav or footer, and its chunks carry the `##` heading paths.
- **KN-10** — Given a local fixture site whose `sitemap.xml` lists four pages under `/help/` and one under `/blog/`, when a `section` source is created for `/help/` with `max_pages` 25, then exactly the four `/help/` pages become docs of the source and the source is `ready` with `page_count` 4.
- **KN-11** — Given the fixture site without a sitemap and a `robots.txt` disallowing `/help/private`, when a `section` source is created, then pages are found by following links to depth 3, `/help/private` is never requested, and URLs differing only by query string or fragment become one doc.
- **KN-12** — Given a `section` source with `max_pages` 2 over four in-scope pages, then two pages are indexed, `found_count` is 4 and the status is `partial`.
- **KN-13** — Given `KNOWLEDGE_ALLOW_PRIVATE_URLS` false, when a URL whose host resolves to `127.0.0.1`, `10.0.0.5` or `169.254.169.254`, or a public URL redirecting to one, is imported or crawled, then no request reaches that address and the result is `blocked_address`; with the setting true, the loopback fixture site is fetched.
- **KN-14** — Given an indexed source, when a sync runs after one page changed, one is unchanged, one is new and one answers 404, then the changed page is re-chunked with a new `content_hash`, the unchanged page keeps its chunk ids, the new page is added, and the 404 page is archived only after the second consecutive sync that sees it missing.
- **KN-15** — Given a published agent with a source in `knowledge_source_ids`, when a sync changes a fact on a page, then a new call's `search_knowledge` returns the new fact without a new agent version, and each result from the source carries its page `url`.
- **KN-06** — Given a doc with status `draft`, when a published version searches, then it is excluded unless the version config lists it explicitly (evaluation candidates only).
