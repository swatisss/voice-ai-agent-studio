---
type: Decision Record
title: ADR-0009 Agent memory - our own mem0-style maintenance that retires instead of deleting
description: Member memory is extracted after each call and maintained automatically by the agent (add, supersede, confirm, no-op) in our own store; nothing is hard-deleted except by expiry or erasure. Records the research behind the choice.
status: stable
tags: [decision, memory]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Context

Builders are non-technical: they describe agents in plain language and should not curate memory by hand. Agents should remember a verified member across calls (episodes, facts) and the platform already has a governed path for procedural learning ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)). Memory about health-insurance members is sensitive (GDPR Art. 9 special category; HIPAA verification before disclosure), so automatic maintenance must stay reviewable and a deterministic erase must exist. Storage today is SQLite/Postgres with NumPy search over local `bge-small` embeddings ([ADR-0004](adr-0004-storage-and-vectors.md)); models are reached only through gateway roles ([ADR-0003](adr-0003-llm-gateway.md)).

Research (2026-10-28):

* **mem0** (paper, 2025): extraction from the latest exchange, a rolling summary and recent messages; then, per candidate fact, the 10 most similar memories and an LLM tool call choosing ADD / UPDATE / DELETE / NOOP; reported ~90% fewer context tokens than full history and p95 latency 1.44 s vs ~17 s. https://arxiv.org/abs/2504.19413
* **mem0 changed course in April 2026**: single-pass, add-only extraction; an old fact and its replacement both stay and the reader resolves which is current, because the reconcile step "was slow and sometimes erased useful information". https://mem0.ai/blog/mem0-the-token-efficient-memory-algorithm · https://docs.mem0.ai/migration/
* **Retire, don't delete** is where the field converged: Zep/Graphiti invalidates contradicted facts with validity intervals (https://arxiv.org/abs/2501.13956); Mem0g marks graph relations invalid; Google Agent Engine Memory Bank stores immutable revisions with rollback (https://docs.cloud.google.com/agent-builder/agent-engine/memory-bank/revisions).
* **SaaS builders expose very little**: Microsoft Copilot Studio customer-conversation memory has one toggle, up to 5 plain-language parameters (Replace or Append), 30-day retention and identified customers only (https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/memory-overview-customer-conversation); Intercom Fin Memory keeps episodes 45 days and facts 180 days, identified users only, and logs "Fin referenced memory" (https://fin.ai/help/en/articles/16004462-fin-memory). Several voice platforms (ElevenLabs, Vapi, Retell) have no native per-caller memory.
* **Erasure**: derived memories outlive transcripts; deleting only the vector entry is not enough (secondary sources; legal review needed): https://gdpr-text.com/en/read/article-17/
* mem0 is Apache-2.0 and embeddable, but defaults to Qdrant and its own LLM clients; no SQLite vector store or fastembed embedder was found. https://github.com/mem0ai/mem0

# Options

1. **Adopt the mem0 library** — fast start; adds a second store and its own model clients (against ADR-0003) and an algorithm that has already changed once.
2. **mem0-paper algorithm with hard DELETE** — what was first asked for; loses information the model wrongly discards, and nothing can be reviewed afterwards.
3. **Add-only (mem0 2026)** — never loses anything, but every reader must resolve contradictions and the prompt grows.
4. **Our own mem0-style extraction with ADD / SUPERSEDE / CONFIRM / NOOP** — the model maintains memory by itself; a superseded fact is retired with a pointer to its successor; expiry and an explicit erase are the only deletions.

# Decision

Option 4, run after the call (no latency in the call), with the `analysis` role and the existing embedder; builders get one toggle, two plain-language fields and two retention periods; procedural memory stays with fleet learning. See [/architecture/agent-memory.md](/architecture/agent-memory.md).

# Consequences

* Automatic decisions are visible and reversible in the Studio (retired items, reasons, restore); erasure removes content everywhere and leaves a content-free tombstone.
* Two `analysis` calls per verified call (extract, then one decision per candidate fact) — at most six model calls, off the call path.
* Moving to a graph or temporal-query model later (Graphiti-style) needs a new CP; `valid_at` / `invalid_at` keep that door open.
