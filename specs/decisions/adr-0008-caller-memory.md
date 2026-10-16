---
type: Decision Record
title: ADR-0008 Caller memory with offline consolidation
description: Own versioned tables as the memory source of truth, notes captured per call and consolidated by a background dream, behind a MemoryProvider interface with mem0 as a possible later backend.
status: draft
tags: [decision, memory, privacy]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Context

Agents forget every caller between calls. The product owner wants returning callers to be recognised and served with what earlier calls taught the bot, and asked for the approach popularised as memory "dreaming": record cheaply during or after a conversation and consolidate offline, so the memory stays deduplicated and current. The platform is healthcare-adjacent ([/product/healthcare-compliance.md](/product/healthcare-compliance.md)), self-hosted, spec-driven (models and prompts live in `models.yaml` and `specs/prompts/`), and runs jobs in-process ([/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)).

# Decision

* **Capture, then dream.** One structured note per verified call; a dream job rewrites the caller's profile as a new version once `dream_after_notes` (default 10) notes wait. No nightly schedule.
* **The model proposes changes, code applies them.** The dream returns a change list; deterministic code validates, scrubs and caps. The profile is never replaced wholesale by model output.
* **Own tables are the source of truth** (`call_notes`, versioned `caller_profiles`, `dream_runs`) behind a `MemoryProvider` interface. Versioning, a diff per dream, per-fact provenance, tenant isolation and cascading deletion are plain SQL and testable; a dedicated `memory` LLM role and two prompt specs keep the repo rule that models and prompts live only in config and specs.
* **Identity:** memory is keyed by verified `member_ref`. Caller ID (hashed) only unlocks a low-sensitivity hint.
* **Recall adds the newest pending notes** to the consolidated profile, because with a threshold of 10 a profile-only recall would forget a caller for ten calls.
* **Self-hosted, synthetic data only in v1.**

# Alternatives

| Option | Why not (now) |
|---|---|
| mem0 as the primary store (self-hosted or cloud) | Inline add/update consolidation instead of an offline pass; no versions, diffs or provenance without bolting them on; its own LLM and prompt configuration conflicts with this repo's rules; hosted mode sends call content to a third party. Kept possible as a later backend behind `MemoryProvider`. |
| Per-turn memory writes during the call | Adds latency and cost on the hot path and stores unreviewed facts. |
| Vector search over raw transcripts | Large, hard to delete precisely, surfaces stale or sensitive text. |
| Nightly consolidation only | Not needed at demo volumes; the notes threshold is simpler and testable. |

# Consequences

* Three new tables (23 in total) and three job kinds; existing databases gain tables on start-up without migration.
* One more LLM role and two prompts, with a small recurring cost per call (capture) and per ten calls (dream).
* Stored memory is personal data about members. v1 stays synthetic-data only; production needs the gaps in the compliance note closed (BAAs, audit log, formal retention policy) before real callers.
* A future mem0 (or other) backend is a CP: implement `MemoryProvider`, keep the tests (MEM-18) as the contract.
