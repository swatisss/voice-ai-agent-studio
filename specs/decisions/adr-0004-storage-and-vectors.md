---
type: Decision Record
title: ADR-0004 Storage and vectors
description: SQLite locally and Postgres in the cloud behind SQLAlchemy; embeddings from local fastembed stored as JSON; similarity computed in-process with NumPy.
status: stable
tags: [decision, storage, embeddings]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Context

The development machine has no Docker; the hackathon needs zero-infrastructure startup. Knowledge bases and clusters are small (hundreds to low thousands of chunks per tenant). Embedding APIs add keys, cost and latency.

# Decision

* SQLAlchemy 2 async with `aiosqlite` by default and `asyncpg` when `DATABASE_URL` points to Postgres (Cloud SQL). Portable column types only.
* Embeddings from `fastembed` (`BAAI/bge-small-en-v1.5`, 384-d, CPU, free), stored as JSON arrays.
* Search and clustering use NumPy cosine similarity over vectors loaded per agent doc set (cached, invalidated on change).

# Consequences

* `uv run voiceai serve` works on a bare machine; tests run with the `hash` embedder and no downloads.
* Fine up to roughly 50k chunks per agent; beyond that, move to pgvector (a CP: add a vector column, an index and a query path).
* The fastembed model (~70 MB) downloads on first use locally and is baked into the container image.
