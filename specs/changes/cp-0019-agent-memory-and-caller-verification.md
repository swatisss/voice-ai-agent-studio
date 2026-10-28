---
type: Change Proposal
title: CP-0019 Agent memory and caller verification
description: Agents remember verified members across calls (episodes and facts) and maintain that memory themselves after each call; a registered phone number identifies the caller and the date of birth verifies them; the Studio shows and erases what agents remember.
status: stable
cp_state: implemented
tags: [memory, verification, runtime, telephony, ui]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Why

Every call starts from nothing. A member who called yesterday about a claim, said they prefer a call back after 5pm, or that their daughter helps with paperwork, has to repeat it all, and the agent cannot follow up on what it promised. Callers also have to read out a member ID even when they call from the number on their record. Builders are non-technical and cannot curate memory by hand, so the agent has to maintain it itself, safely: the members are health-insurance customers.

Decided in the design session of 2026-10-28 (questions Q1–Q26), with research in [ADR-0009](/decisions/adr-0009-agent-memory.md) and [ADR-0010](/decisions/adr-0010-caller-verification.md).

# What changes

* **Four memory types.** Working memory stays `CallState`. New **episodic** (one summary per call) and **semantic** (facts learned in conversation) memory per tenant + agent + verified member. **Procedural** memory is the skills and policy rules fleet learning already drafts, evaluates and a human approves; nothing new is written automatically there.
* **The agent maintains memory itself.** After each verified call a background job extracts an episode and up to five facts, then for each fact decides ADD, SUPERSEDE (retire the old fact, keep it for audit), CONFIRM or NOOP. Nothing is hard-deleted except by expiry (90 days for episodes, 365 for facts, editable) and by **Erase member**.
* **Memory reaches the prompt after verification** on every real channel (text, cascade, realtime, inbound, outbound, phone), together with a live **member profile** from the business API that is never stored. The agent uses it naturally and never reveals it.
* **Memory is declared like the rest of the agent** (persona, OKF knowledge, tools, skills, policy): plain-language settings in the agent config, versioned on publish, no code. One toggle, "Remember things like…", "Never remember…" (with health-insurer defaults), two retention periods. Clinical details, payment details, identifiers and business-system facts are never stored, whatever the builder writes.
* **Two verification flows.** A call from a registered number is *identified* (first name) and verified with the date of birth; any other call uses member ID and date of birth. Caller ID never verifies alone. Three failed attempts hand the call to a human (`verification_failed`). An opt-in, demo-only setting lets a US call with full carrier attestation use read-only tools before the date of birth. Requests to change contact or identity details go to a human.
* **The Studio shows it**: a Memory card on call detail (used, updated), a member memory page with the source of each memory, retired items, restore, erase and export, a Memory tab in the builder, and a **Call from** choice on Test call to exercise both flows without a phone.
* The mock API gains registered phone numbers, an identify endpoint, date-of-birth-only verification for identified calls and a member profile endpoint; seed data includes memories for three members.

# Affected specs

* New: [/architecture/agent-memory.md](/architecture/agent-memory.md), [/architecture/caller-verification.md](/architecture/caller-verification.md), [/prompts/memory-extract.md](/prompts/memory-extract.md), [/prompts/memory-update.md](/prompts/memory-update.md), [/ui/member-memory.md](/ui/member-memory.md), [/decisions/adr-0009-agent-memory.md](/decisions/adr-0009-agent-memory.md), [/decisions/adr-0010-caller-verification.md](/decisions/adr-0010-caller-verification.md).
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - call state fields, `extract_memory` on end, profile and memory after verification.
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - verification instruction per flow, change requests go to a human, the member profile and memory block.
* [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) - `X-Identified-Ref`, uniform failure result (TS-09).
* [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) - identify, date-of-birth-only verify, member profile (MOCK-15…17).
* [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) - registered numbers, seeded memory.
* [/data/data-model.md](/data/data-model.md) - `member_memories`, `memory_events`, `meta.identification`; DM-01 now 25 tables.
* [/data/agent-config.md](/data/agent-config.md) - `memory` and `verification` settings (DM-07).
* [/architecture/escalation.md](/architecture/escalation.md) - category `verification_failed` (ES-09).
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - `extract_memory`, `purge_memory`.
* [/architecture/telephony.md](/architecture/telephony.md) - identification in the webhook.
* [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) - isolation rule 8 (MT-13).
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rules 9 and 10, production gaps.
* [/api/rest-api.md](/api/rest-api.md) - `caller_number`, call detail `identification` and `memory`, member memory endpoints (API-05…07).
* [/ui/agent-builder.md](/ui/agent-builder.md) (UI-42), [/ui/test-call.md](/ui/test-call.md) (UI-43), [/ui/calls.md](/ui/calls.md) (UI-46).
* [/build/runbook-phone.md](/build/runbook-phone.md) - testing identification with Dev Phone or the Calls API.
* [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefixes `MEM`, `IDV`), index files.

# Acceptance criteria

New: MEM-01…MEM-11 and IDV-01…IDV-07 (in the new specs), TS-09, MOCK-15…MOCK-17, DM-07, ES-09, MT-13, API-05…API-07, UI-42…UI-46. Changed: DM-01 (25 tables). Each is written in its spec.

# Tasks

1. Spec edits (done in this CP).
2. Mock API: registered numbers, `/identify`, date-of-birth-only `/verify`, `/members/me` — covers MOCK-15…17.
3. Data: `member_memories`, `memory_events`, config defaults and validation — covers DM-01, DM-07.
4. Verification: identification in the Twilio webhook and `POST /api/calls`, call-state levels, `X-Identified-Ref`, uniform failure, attempt limit and `verification_failed`, attestation setting, prompt variables — covers IDV-01…07, TS-09, ES-09, API-05.
5. Memory read path: load at verification on every channel (realtime refresh included), profile fetch, prompt block, "Memory loaded" event — covers MEM-05, MEM-06, MEM-10, MT-13.
6. Memory write path: `extract_memory` job with the two prompts, exclusion filter, supersede/confirm, events; `purge_memory` daily job — covers MEM-01…04, MEM-07.
7. Memory API: list, restore, erase, export; call detail `memory` — covers MEM-08, MEM-09, MEM-11, API-06, API-07.
8. Web: builder Memory tab, Test call **Call from**, call detail Memory card, member memory page — covers UI-42…46.
9. Seed: registered numbers and seeded memories; runbook section.

# Risks and rollout

* **Schema change**: two new tables, created on start for existing databases (DM-01); demo data needs `seed --reset` for the seeded memories.
* **Wrong extraction**: a model may keep something it should not. Mitigation: fixed exclusions filtered in code after the model, retire instead of delete, everything visible and erasable in the Studio.
* **Cost**: at most six `analysis` calls per verified call, off the call path.
* **Caller ID spoofing**: identification only reveals a first name; the shortcut that skips the date of birth is off by default, US-only in practice, and limited to read-only tools.
* **No roles in v1**: anyone in a tenant's Studio can erase or export member memory (listed as a production gap).

# Out of scope

* A `recall_memory` tool, memory written during the call, and memory shared between agents.
* One-time codes or other step-up factors; lockout across calls after failed verification.
* Automatic procedural memory: lessons keep going through fleet learning's evaluation and approval.
* Graph or temporal queries over memory.
