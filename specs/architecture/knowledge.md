---
type: Component Spec
title: Knowledge
description: Knowledge ingestion from text, files, URLs and OKF bundles; heading-aware chunking; local embeddings; cosine search with a no-answer threshold.
status: stable
tags: [architecture, knowledge, rag, okf]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Sources

| `source_type` | Input | Notes |
|---|---|---|
| `text` | title + Markdown/plain text body | Pasted in the builder |
| `file` | `.md`, `.txt`, `.pdf` upload (≤ 5 MB) | PDF text via `pypdf` |
| `url` | http(s) URL | Fetched with `httpx` (10 s timeout), HTML tags stripped, `<title>` used as title |
| `okf` | `.zip` of an OKF bundle, or a server path (seed only) | Every non-reserved `.md` with frontmatter becomes one doc; `title` from frontmatter (else filename); `type`, `tags`, `description` stored in `doc.meta`; frontmatter removed from content |

Docs belong to a tenant. An agent uses the docs listed in its config `knowledge_doc_ids`. Doc `status`: `active` (usable), `draft` (only visible to evaluation candidates), `archived`.

# Chunking

1. Split on Markdown headings (`#`–`###`); each chunk keeps its heading path (e.g. `Claims > Timelines`) in `heading`.
2. Sections longer than 900 characters are split on paragraph boundaries into ≤ 900-character pieces with 120 characters of overlap.
3. Chunks shorter than 40 characters are merged into the previous chunk.
4. The text embedded is `"{doc title} — {heading}\n{content}"`.

# Embeddings

* `EMBEDDINGS_PROVIDER=fastembed` (default): `BAAI/bge-small-en-v1.5`, 384 dims, L2-normalized, model cached under `FASTEMBED_CACHE` (default `.cache/fastembed`).
* `EMBEDDINGS_PROVIDER=hash`: deterministic 384-dim hashed bag-of-words (tests, offline). Lower quality.
* Embeddings are stored with each chunk as JSON float arrays. Queries use the same provider. Changing provider requires `voiceai reindex`.
* Both are adapters behind the `Embedder` port, chosen by `EMBEDDINGS_PROVIDER` in the composition root ([/architecture/modular-structure.md](/architecture/modular-structure.md)); a third embedder is a new adapter and a configuration value, with no change to ingestion or search.

# Search

`search(tenant_id, doc_ids, query, top_k=4)`:

1. Embed the query; cosine similarity against all chunks of `doc_ids` (NumPy, in memory, cached per doc set and invalidated on doc changes).
2. Keep results with score ≥ `KN_MIN_SCORE` (default **0.60** for fastembed, 0.15 for hash).
3. If none remain → `{"no_answer": true, "message": "No approved information found for this question."}`.
4. Else → `{"results": [{"doc_id", "title", "heading", "content", "score"}]}`, best first, at most `top_k`, content trimmed to 700 chars.

The runtime treats `no_answer` as a signal for the no-answer streak ([/architecture/escalation.md](/architecture/escalation.md)) and the analysis treats it as evidence of `missing_knowledge`.

# Acceptance

- **KN-01** — Given a Markdown doc with three `##` sections, when ingested, then three chunks are stored with their heading paths.
- **KN-02** — Given a section of 2,000 characters, when chunked, then every chunk is ≤ 900 characters and consecutive chunks overlap.
- **KN-03** — Given an OKF zip containing `index.md`, `log.md` and two concept files, when imported, then exactly two docs are created and frontmatter is stripped from their content.
- **KN-04** — Given a query unrelated to any doc, when searched, then the result is `no_answer`.
- **KN-05** — Given docs not listed in the agent's `knowledge_doc_ids`, when the agent searches, then those docs are never returned.
- **KN-06** — Given a doc with status `draft`, when a published version searches, then it is excluded unless the version config lists it explicitly (evaluation candidates only).
