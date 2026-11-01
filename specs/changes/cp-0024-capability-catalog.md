---
type: Change Proposal
title: CP-0024 Capability catalog and routing suite
description: Use cases become editable, the agent description and a routable flag join the published snapshot, every published routable agent gets an automatically re-indexed capability profile, and a tenant-level routing suite measures routing accuracy.
status: stable
cp_state: implemented
tags: [routing, knowledge, evaluation, builder]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

The supervisor (CP-0025) must know what each agent handles, and the product owner rejected a routing table: "every agent will be adding new use cases every time … a kind of sync should happen with the router". Use cases, the natural source, are seed-only today, and the agent description is not versioned. Second CP of [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# What changes

* **Use cases** get create, edit and delete (API and a builder **Use cases** tab). They stay unversioned.
* The **published snapshot** carries `description`, `routable` (default true) and `handoff_intro` (the line an agent says when it receives a routed conversation, default "You're now with our {agent name} team.").
* A **capability profile** per published, routable inbound or internal agent: description, use cases with utterances, tool descriptions, knowledge titles and 10–20 generated example requests, embedded for search. A background job re-indexes an agent on publish and on use-case and knowledge changes, skipping when nothing changed.
* A **routing suite** per tenant: generated held-out paraphrases plus manual cases (utterance → expected agent), run after every catalog change and on demand, reported with accuracy, a confusion matrix, methods, fallbacks and latency on the Evaluation page's new **Routing** view.

# Affected specs

* New: [/architecture/capability-catalog.md](/architecture/capability-catalog.md) (CAT-01…CAT-08), [/prompts/capability-utterances.md](/prompts/capability-utterances.md).
* [/data/agent-config.md](/data/agent-config.md) - `routable`, `handoff_intro`, snapshot `description` (DM-11).
* [/data/data-model.md](/data/data-model.md) - `capability_profiles`, `capability_entries`, `routing_cases`; `eval_runs.kind: routing` with nullable `agent_id`; `eval_results.case_type: routing`; `use_cases.updated_at` (DM-01: 35 tables).
* [/product/use-cases.md](/product/use-cases.md) - editable (UC-07).
* [/api/rest-api.md](/api/rest-api.md) - use-case CRUD, routing cases and runs (API-11).
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md), [/api/events.md](/api/events.md) - `index_capabilities`, `run_routing_suite`, `catalog.updated`, `routing_run.finished`.
* [/ui/agent-builder.md](/ui/agent-builder.md) (UI-59), [/ui/evaluation.md](/ui/evaluation.md) (UI-62, Routing view).
* [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefix `CAT`).

# Acceptance criteria

New: CAT-01…CAT-08, DM-11, UC-07, API-11, UI-59, UI-62. Changed: DM-01 (35 tables, counting CP-0023's four). The routing-run parts of CAT-07 and UI-62 need the router of CP-0025 and are tested with it.

# Tasks

1. Spec edits (this CP).
2. Snapshot fields and validation; seed: `handoff_intro` for the five demo agents — DM-11, CAT-06.
3. Use-case CRUD routes with validation; queue re-index on change — UC-07, CAT-05, API-11.
4. `voiceai/routing/catalog.py`: profile build, input hash, generated examples (prompt, role `drafting`), entries and embeddings; `index_capabilities` job; triggers on publish, use cases and knowledge — CAT-01…CAT-04.
5. Routing cases (generated test paraphrases never indexed, manual CRUD), `run_routing_suite` job and summary; one queued run per tenant — CAT-07, CAT-08.
6. Web: builder Use cases tab, Overview description/routable/intro; Evaluation Routing view (cases, runs, confusion matrix) — UI-59, UI-62.
7. Tests citing the IDs; the DM-01 test at 35 tables.

# Risks and rollout

* Generated examples cost one `drafting` call per agent change (not per knowledge change); seeded tenants are indexed once at seed.
* Use-case edits change routing without a publish. This is deliberate (routing knowledge, not agent behaviour) and visible in the routing suite run that follows.
* A low-quality description routes badly; the routing suite and the Routing view make that visible.

# Out of scope

Versioning use cases; per-agent negative examples; multilingual routing beyond what the embedder and target support.
