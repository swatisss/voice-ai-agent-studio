---
type: Change Proposal
title: CP-0012 Caller memory with dreaming
description: Verified callers are remembered across calls - a structured note after each call, a background dream that consolidates notes into a versioned profile, recall at call time, and a Memory page to inspect, edit and delete.
status: draft
cp_state: proposed
tags: [memory, runtime, privacy, learning, ui]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Why

The studio has no memory: every call starts from the agent config alone, and the only caller identity (`verified_member_ref`) appears mid-call and is then forgotten (it is stored on `calls.caller_ref` and nothing reads it back). A returning caller must repeat preferences, household details and the status of an open issue every time.

The product owner asked for memory that works like ChatGPT's "dreaming": capture during or after conversations, then consolidate in the background so memory stays deduplicated and current. Public descriptions of that feature (secondary coverage only; OpenAI's own post could not be opened from this environment) say a background process reviews past conversations, merges duplicates, updates stale items and infers patterns. This CP adopts the idea, not any OpenAI-specific detail, and adds what a healthcare product needs on top: verified identity, sensitivity tiers, provenance, deletion that cascades and a staff view.

# What changes

1. **Capture.** After a qualifying call (verified member, memory-enabled agent, not simulation or internal), a `capture_call_note` job stores one small, scrubbed **call note**: a summary and candidate facts.
2. **Dream.** When a member has `dream_after_notes` (default **10**) pending notes, a `dream_profile` job asks the new `memory` LLM role for **changes** (add, update, confirm, retire), validates and applies them in code, and writes a **new versioned profile** plus a `dream_runs` record holding the diff. Failures leave the profile untouched. There is no nightly run; staff can start a dream by hand.
3. **Recall.** The system prompt gains a "What you remember about this caller" block. After verification it holds the member's non-expired facts plus the summaries of up to three newest not-yet-dreamed notes (so a caller is remembered from the very next call, not after ten). Before verification, a **caller-ID hint** (`caller_phone`, stored only as a salted hash) may load only `low`-sensitivity preferences, labelled unverified; names and account facts wait for verification. If the verified member differs from the hint's, the hint is dropped.
4. **Privacy rules in code and prompts.** Identifiers are scrubbed; health facts need an explicit statement and are never inferred; inferred facts are marked and confirmed with the caller before use; facts carry sensitivity, basis, last-confirmed and expiry; retention (default 365 days) is enforced; deleting a member's memory cascades to notes, all versions and runs; a deleted fact is not re-learned.
5. **Memory page and agent setting.** New **Memory** page (list, fact provenance, waiting notes, dream diffs, edit, remove, delete all, "Dream now"), a **Memory tab** in the agent builder, a "Memory used" card in call detail, and an optional Caller phone field in Test call.
6. **Pluggable backend.** The runtime depends on a `MemoryProvider` interface; `SqlMemoryProvider` is the only implementation. mem0 may be added later behind the interface ([ADR-0008](/decisions/adr-0008-caller-memory.md)).

**Before / after (prompt, returning caller).**

Before — Caller verifies, says "Can you call me back after five?" Agent: "I can't schedule that, but I can connect you with a specialist." Next week, the same caller must say it again.
After — Week 1: same exchange; the call note records "Prefers calls after 5 pm" (stated, low sensitivity). After ten calls the dream keeps it, confirmed, with provenance. Week 2, once the caller verifies, the agent already knows and may say "I'll note that you prefer evenings" without being told again; it does not recite the profile and it confirms anything inferred ("I have you down as preferring email — is that still right?").

# Affected specs

* [/architecture/caller-memory.md](/architecture/caller-memory.md) - **new**: capture, dream, recall, retention, MemoryProvider; MEM-01…MEM-19.
* [/decisions/adr-0008-caller-memory.md](/decisions/adr-0008-caller-memory.md) - **new**: why own tables, why notes then dream, why not mem0 as primary.
* [/prompts/memory-capture.md](/prompts/memory-capture.md), [/prompts/memory-dream.md](/prompts/memory-dream.md) - **new** prompts (role `memory`).
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - `caller_memory` variable and the "What you remember about this caller" section.
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - start (hint), verification (load), `end()` (capture), `CallState.memory_level` and `memory_fact_ids`; RT-10.
* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - `memory` role; LG-10 widened, LG-12.
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - three job kinds, `memory` topic; JB-06.
* [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) - isolation rule for memory.
* [/data/data-model.md](/data/data-model.md) - tables `call_notes`, `caller_profiles`, `dream_runs` (23 tables); DM-01 changed.
* [/data/agent-config.md](/data/agent-config.md) - `memory` block and bounds; DM-06.
* [/api/rest-api.md](/api/rest-api.md) - `caller_phone`, `/api/memory/*`, `memory` on call detail; API-05.
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rule 9 and the narrowed production gap; [/product/scope.md](/product/scope.md) - in scope.
* [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) - seed: memory on for the Customer Care Agent, one synthetic profile for `EVG-482913`; MEM-20.
* [/ui/memory.md](/ui/memory.md) - **new** page; [/ui/app-shell.md](/ui/app-shell.md) (navigation, UI-29 changed), [/ui/agent-builder.md](/ui/agent-builder.md) (Memory tab), [/ui/test-call.md](/ui/test-call.md) (Caller phone), [/ui/calls.md](/ui/calls.md) (Memory used card).
* [/process/conventions.md](/process/conventions.md) - acceptance prefix `MEM`.

# Acceptance criteria

New: **MEM-01…MEM-20**, **LG-12**, **JB-06**, **RT-10**, **DM-06**, **API-05**, **UI-38…UI-43**. Changed: **DM-01** (23 tables), **LG-10** (role list gains `memory`), **UI-29** (eight navigation items). **MEM-13** is a prompt behaviour checked by hand with a real model; **UI-38…UI-43** are checked by hand in the browser.

# Tasks

1. Spec edits (done in this CP).
2. Data and config — models `CallNote`, `CallerProfile`, `DreamRun` (`voiceai/models.py`), `memory` block and bounds in the agent schemas (`voiceai/schemas.py`) — covers DM-01, DM-06.
3. Memory package `voiceai/memory/` — `provider.py` (interface), `sql.py`, `scrub.py`, `capture.py`, `dream.py`, `recall.py`; prompts loaded verbatim; `memory` role in `config/models.yaml` and `llm/gateway.py` — covers MEM-01…MEM-08, MEM-15, MEM-16, MEM-18, MEM-19, LG-12.
4. Runtime — hint lookup at `start()`, load on verification (`runtime/tools.py` hook into the session), `caller_memory` in `runtime/prompt.py`, `CallState` fields, `end()` enqueues capture, `calls.meta.caller_phone_hash` — covers MEM-09…MEM-12, RT-10.
5. Jobs — handlers `capture_call_note`, `dream_profile`, `purge_expired_memory`; `memory.updated` events — covers JB-06, MEM-04, MEM-06, MEM-08.
6. API — `caller_phone` on `POST /api/calls`, `memory` on call detail, `/api/memory/*` routes — covers MEM-14, MEM-17, API-05.
7. Seed — enable memory for the Customer Care Agent and seed one profile — covers MEM-20.
8. Web — Memory list and detail pages, agent builder Memory tab, call detail card, Test call field, navigation — covers UI-38…UI-43.
9. Tests in `apps/api/tests/` citing the IDs (fake LLM, fake provider, temp SQLite, no network); add UI-38…UI-43 and MEM-13 to `scripts/acceptance-baseline.txt`.
10. Verify (`python scripts/spec_check.py --ci --base origin/main`, `uv run pytest`, `npm run build`, browser check). Close: specs to `stable`, CP to `implemented`, `specs/log.md`.

# Risks and rollout

* **Personal data.** Memory is stored information about members. v1 remains synthetic-data only; real callers need the production gaps in [/product/healthcare-compliance.md](/product/healthcare-compliance.md) closed first (BAAs for the LLM providers that see call content, audit log, access control on who may view memory).
* **Wrong or stale memory.** Mitigated by stated/inferred marking, confirmation before use, expiry, "caller is believed over memory" in the prompt and staff edit/delete; tested by hand (MEM-13).
* **Cost and latency.** One extra `memory` call per qualifying call and one per ten calls, all in background jobs; recall adds one database read at verification and none per turn.
* **Existing databases** gain three tables on start-up (no migration). Memory is off for every existing agent until enabled.
* **Fallback.** Setting `memory.enabled: false` (or removing the block) returns an agent to today's behavior; stored data stays until deleted.

# Out of scope

* Caller-initiated "forget me" during the call (the agent hands off to a specialist; staff delete via the Memory page).
* A mem0 or other external backend (the interface allows it; a later CP).
* A nightly schedule, cross-tenant memory, memory for `internal` (staff) agents and for unverified callers.
* A phone-number-to-member directory and real telephony caller ID (v1 uses the optional `caller_phone` field and hashes learned from verified calls).
* Using memory to change policy, escalation rules or knowledge; memory only personalises service.
* Authentication or roles for who may open the Memory page (tenant switcher only, as elsewhere in v1).
