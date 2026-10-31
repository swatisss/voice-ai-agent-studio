---
type: Component Spec
title: Agent memory
description: What an agent remembers about a verified member across calls (episodes and facts), how it maintains that memory by itself after each call, how memory reaches the prompt, expiry, erasure and what the Studio shows.
status: stable
tags: [architecture, memory, runtime]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Memory types

| Type | What it holds | Where it lives | Who writes it |
|---|---|---|---|
| **Working** | The state of one call: verification, tools used, streaks | `CallState` ([/architecture/agent-runtime.md](/architecture/agent-runtime.md)) | The runtime, during the call |
| **Episodic** | One short summary per past call with this member: what they wanted, what happened, what was promised | `member_memories`, `kind: episode` | The agent, after the call |
| **Semantic** | Lasting facts learned in conversation: preferences, relationships, commitments, circumstances | `member_memories`, `kind: fact` | The agent, after the call |
| **Procedural** | How the agent handles kinds of requests, learned across many calls | The agent's skills and policy rules | [Fleet learning](/architecture/fleet-learning.md) only, after evaluation and human approval |

Procedural memory is not a new store: it is the skills and policy rules that fleet learning drafts, evaluates and a human approves ([/product/healthcare-compliance.md](/product/healthcare-compliance.md), rule 8). Memory extraction never writes procedural memory.

# Scope

* Episodic and semantic memory belong to one **scope**: tenant + agent + verified member (`member_ref`). Another agent of the same tenant never reads them, and no tenant ever reads another tenant's memory ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)).
* Memory is read and written only for a **verified** member ([/architecture/caller-verification.md](/architecture/caller-verification.md)). An identified but unverified caller gets no memory.
* Every real channel behaves the same: text, cascade voice, realtime voice, inbound, outbound and phone. Simulated and evaluation calls never read or write member memory; a test scenario may give the session stand-in facts instead, which are never stored ([/architecture/test-suites.md](/architecture/test-suites.md), Scenario memory).
* Facts a business API owns (claims, balances, policy details, documents) are **never** stored: the agent fetches them live. Memory holds only what was learned in conversation.

# Builder settings (`config.memory`)

| Field | Default | Rules |
|---|---|---|
| `enabled` | `true` | When false, the agent neither reads nor writes member memory. Existing memory is kept until it expires or is erased. |
| `remember` | "Contact preferences, the best time to call back, family members or representatives who help with the member's requests, what the agent promised to do, and the outcome of each request." | Plain language, ≤ 600 chars. Steers what extraction keeps. |
| `never_remember` | "Diagnoses, symptoms, medications or treatments; payment card or bank details; member IDs, dates of birth or full phone numbers." | Plain language, ≤ 600 chars. Added to the fixed exclusions below. |
| `episode_days` | 90 | 7–365. Episodes expire this many days after they were written. |
| `fact_days` | 365 | 30–730. Facts expire this many days after they were last confirmed. |

**Fixed exclusions** (not configurable, applied in addition to `never_remember`): clinical details of any person; payment, card or bank details; identifiers (member ID, date of birth, full phone number, email address); facts owned by a business API; anything said by or about a caller who was never verified.

# Memory item (`member_memories`)

`kind` (`episode` | `fact`), `category` (`preference` | `relationship` | `commitment` | `circumstance` | `outcome`; episodes use `outcome`), `text` (one plain sentence, ≤ 300 chars), `status` (`active` | `retired`), `valid_at`, `invalid_at` (set when retired), `superseded_by` (the newer item, nullable), `expires_at`, `source_call_id` and `source_seq` (the transcript turn it came from), `embedding`, `prompt_version`. Schema: [/data/data-model.md](/data/data-model.md).

Every change writes a `memory_events` row: `action` (`added` | `superseded` | `confirmed` | `restored` | `expired` | `erased`), the memory id, the actor (`agent` | `studio` | `system`), the call id, and the text before and after. The log is append-only except for erasure and expiry purges, which remove content (below).

# Maintenance after each call (automatic)

When a call ends that was verified, is not an evaluation call and whose agent version has memory enabled, the runtime enqueues `extract_memory` (dedupe key `extract_memory:{call_id}`, [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md)). The job runs two steps with the `analysis` role ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)):

1. **Extract** ([/prompts/memory-extract.md](/prompts/memory-extract.md)) — input: the call transcript, the scope's active memories, the agent's `remember` and `never_remember` text and the fixed exclusions. Output: one episode summary and zero to five candidate facts, each with a category and the transcript turn it came from. Small talk yields no facts.
2. **Decide** ([/prompts/memory-update.md](/prompts/memory-update.md)) — for each candidate fact, the five most similar active facts of the same scope (cosine similarity on the embedding) are shown to the model, which chooses one action:

| Action | Effect |
|---|---|
| `ADD` | A new active fact. |
| `SUPERSEDE` (target id) | The target is retired (`invalid_at` now, `superseded_by` the new fact) and the new fact is added. Used when the new fact contradicts or replaces the old one. |
| `CONFIRM` (target id) | The target's `expires_at` is renewed; nothing new is stored. |
| `NOOP` | Nothing changes. |

The episode is always added. The model never deletes: retiring keeps an automatic decision reviewable and reversible. A candidate that breaks an exclusion is dropped before step 2, whatever the model said.

# Reading memory in a call

When a call becomes verified ([/architecture/caller-verification.md](/architecture/caller-verification.md)) and the agent version has memory enabled:

1. The session loads the scope's active, unexpired memory: up to 10 facts (newest confirmed first) and the 3 most recent episodes.
2. It fetches the member profile from the business API (`GET /mock/healthcare/members/me`, [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md)). The profile is used for this call only and never stored.
3. Both are rendered into the system prompt as `member_profile` and `member_memory` ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)). A realtime call refreshes its instructions, as it already does on verification.
4. A `system` event "Memory loaded" records the ids of the memories used (`data.memory_used`).

The prompt tells the agent to use memory naturally, never before verification, never to read it out or mention "memory", and not to raise sensitive past topics unless the caller does.

# Expiry and erasure

* An item past `expires_at` is never read. A daily `purge_memory` job deletes expired items and replaces the text of their events with a content-free `expired` marker.
* **Erase member** (anyone in the tenant's Studio while v1 has no roles; `POST /api/members/{member_ref}/memory/erase`, [/api/rest-api.md](/api/rest-api.md)): deletes every memory and event of that member in the tenant, across all agents, including embeddings, and leaves one content-free `erased` event (who, when). This is the right-to-erasure path; it does not wait for expiry.
* **Restore**: a retired fact becomes active again (`invalid_at` cleared); its successor stays active.
* **Export**: all memories (active and retired) and events of a member in the tenant as JSON.

# What the Studio shows

* Call detail: **Memory used** (the facts and episodes loaded, linked) and **Memory updated** (what the agent added, superseded or confirmed after the call, with the reason) ([/ui/calls.md](/ui/calls.md)).
* Member memory page: per agent, a timeline of active and retired items; each item shows *why the agent knows this* (a link to the transcript turn) and, if retired, what replaced it; Restore, Erase member and Export ([/ui/member-memory.md](/ui/member-memory.md)).
* Agent builder: a **Memory** tab with the settings above ([/ui/agent-builder.md](/ui/agent-builder.md)).

# Acceptance

- **MEM-01** — Given a verified text call on an agent with memory enabled, when it ends, then exactly one `extract_memory` job is queued; given an unverified call, a simulation or evaluation call, or an agent version with `memory.enabled: false`, no job is queued.
- **MEM-02** — Given a transcript where the verified caller says "please call me back after 5pm, my daughter Ana usually helps with my claims", when extraction runs, then one episode and two active facts are stored (categories `preference` and `relationship`), each with `source_call_id` and the transcript turn, and two `added` events.
- **MEM-03** — Given an active fact "prefers phone calls" and a later call where the caller says "please only email me from now on", when extraction runs, then the old fact is `retired` with `invalid_at` set and `superseded_by` pointing to a new active fact, and a `superseded` event records both texts; no row is deleted.
- **MEM-04** — Given a transcript in which the caller describes chest pain medication and reads out a card number, when extraction runs, then no stored memory contains a symptom, medication or card number, even if the model proposed one.
- **MEM-05** — Given active memory for member EVG-482913 on the Customer Care agent, when a call on the Claims agent of the same tenant is verified for that member, then no memory is loaded; when a Customer Care call is verified for that member, the prompt contains the facts and the 3 most recent episodes, and a `system` event lists their ids.
- **MEM-06** — Given an identified but unverified caller, then the prompt contains no member profile and no memory; after verification it contains both.
- **MEM-07** — Given a fact whose `expires_at` has passed, then it is not loaded into any call, and after `purge_memory` runs its text no longer exists in `member_memories` or `memory_events`.
- **MEM-08** — Given memory for a member on two agents, when the member is erased from the Studio, then no memory, embedding or event content of that member remains in the tenant, one `erased` event without content exists, and the member's next verified call loads no memory.
- **MEM-09** — Given a retired fact, when it is restored from the Studio, then it is active again and loaded in the next verified call, and a `restored` event exists.
- **MEM-10** — Given the same scripted conversation over text, cascade voice and realtime voice, then the same memories are loaded at verification and the same extraction job runs after each call.
- **MEM-11** — Given a member's memory export, then it lists active and retired items with their source calls and all events, and contains nothing from another member or tenant.
