---
type: Component Spec
title: Capability catalog
description: What the supervisor knows about each agent - a capability profile per published, routable agent built from its description, use cases, tools, knowledge and generated examples, indexed for semantic search and kept in sync automatically; plus the tenant's routing suite.
status: stable
tags: [architecture, routing, knowledge, evaluation]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Purpose

The [supervisor](/architecture/supervisor-routing.md) must know what every agent can do, without anyone maintaining a routing table: when a use case, a knowledge article or a tool is added, routing follows. The catalog is derived from what agents already have and rebuilt in the background. Decision: [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# Which agents are in the catalog

An agent is **routable** when it is published, its published snapshot has `routable: true` (default, [/data/agent-config.md](/data/agent-config.md)) and its mode is `inbound` (scope `member`) or `internal` (scope `staff`). Outbound agents and drafts are never in the catalog.

# Capability profile

One `capability_profiles` row per routable agent ([/data/data-model.md](/data/data-model.md)), shaped like an A2A AgentCard:

| Part | Source |
|---|---|
| `name`, `description` | the published snapshot (`description` is now part of the snapshot) |
| `skills` | the agent's use cases ([/product/use-cases.md](/product/use-cases.md)): `{id, title, summary, examples: sample_utterances}` |
| `tools` | name and description of every tool in the snapshot (built-ins excluded) |
| `knowledge` | title of every active knowledge doc in the snapshot's `knowledge_doc_ids` |
| `generated_examples` | 10–20 caller utterances written by the [capability utterances prompt](/prompts/capability-utterances.md) (role `drafting`) from the parts above, so an agent with few use cases is still findable |
| `summary` | ≤ 600 chars, the text a decision model sees for this agent: description, then the use-case titles, then up to 8 tool descriptions, truncated |

`capability_entries` holds one embedded row per searchable text: the description, each use-case title + summary, each sample utterance, each generated example and each tool description. Knowledge is searched through the existing `knowledge_chunks` embeddings of the agent's docs, not copied. Embeddings use the knowledge embedder ([/architecture/knowledge.md](/architecture/knowledge.md)).

# Sync

The job `index_capabilities` (`{agent_id}`) rebuilds one agent's profile. It is queued:

| Change | Agents re-indexed |
|---|---|
| An agent is published | that agent |
| A use case is created, edited or deleted | its agent |
| A knowledge doc is created, re-chunked or archived | every published agent whose snapshot lists it (the profile's titles; searches read chunks live) |
| An agent's mode or `routable` changes (through publish) | that agent; it leaves the catalog if no longer routable |

Tools and skills are part of the published snapshot, so their edits reach the catalog when the agent is published. The job hashes its inputs; an unchanged hash finishes without work. Generated examples are rewritten only when the description, use cases or tools changed. A profile is `indexing` while the job runs and the previous profile keeps serving; a failed job leaves the previous profile and records `error`. After a profile changes, the tenant's routing suite is queued (below).

# Use cases become editable

Use cases were seed-only. They now have create, edit and delete in the API (`/api/use-cases`, [/api/rest-api.md](/api/rest-api.md)) and in the agent builder's **Use cases** tab ([/ui/agent-builder.md](/ui/agent-builder.md)). Use cases are not versioned: a change applies to routing as soon as the re-index finishes.

| Field | Rules |
|---|---|
| `agent_id` | an agent of the tenant |
| `title` | 3–120 chars, unique per agent |
| `summary` | ≤ 600 chars |
| `category` | ≤ 120 chars |
| `channels` | subset of `voice`, `chat`, `phone` |
| `sample_utterances` | 1–20 items, each 3–200 chars |
| `demo_callers` | as seeded (optional) |

# Routing suite

A tenant-level test of the router: **routing cases** (`routing_cases`) of `{utterance, expected_agent_id, scope, source, enabled}`.

* **Generated cases**: for each use case, up to 3 paraphrases written by the capability utterances prompt in test mode. They are never indexed, so the suite does not test the router on its own index. Regenerated when the use case changes; `source: generated`.
* **Manual cases**: added and edited on the Evaluation page's **Routing** view ([/ui/evaluation.md](/ui/evaluation.md)); `source: manual`; at most 500 per tenant.
* A **routing run** (`eval_runs.kind: routing`, no agent) routes every enabled case with the live router (Stage A and Stage B, no clarification) and stores one result per case. Summary: accuracy, accuracy per expected agent, a confusion matrix, the share decided per method, clarification rate (cases below the threshold), Stage B fallbacks and decision latency p50 / p95.
* A **comparison run** (`{compare: true}`) decides every case in both [routing modes](/architecture/supervisor-routing.md), reusing one Stage A ranking and one decision-model call per case, and stores per mode: right first choice, decided without asking, right when decided, vague cases asked about (manual cases whose expected agent is `?`) and latency p50 / p95. Without a configured decision model its row says "Not configured" and the model is not called.
* Runs start after any catalog change (at most one queued run per tenant), on **Run routing suite**, and on a change of the decision target. The run **passes** when accuracy ≥ the front desk's `min_routing_accuracy` (default 0.9, [/architecture/tenant-settings.md](/architecture/tenant-settings.md)). Nothing is blocked by a failing run; the Evaluation page shows it.

# Acceptance

- **CAT-01** — Given an agent published with `routable: true`, then within one job run its profile exists with its description, use cases with their utterances, tool descriptions, knowledge titles and 10–20 generated examples, and its entries are embedded; an unpublished agent, an outbound agent or `routable: false` has no profile.
- **CAT-02** — Given a use case added to a published agent through `POST /api/use-cases`, then `index_capabilities` runs for that agent and a caller utterance equal to the new sample utterance ranks that agent first in Stage A.
- **CAT-03** — Given a knowledge doc attached to a published agent, when the doc is archived, then that agent is re-indexed and the doc's title is gone from its profile.
- **CAT-04** — Given a tool's description changed after publish, then the profile is unchanged until the agent is published again; given two re-index jobs with identical inputs, the second makes no LLM or embedding call.
- **CAT-05** — Given `POST /api/use-cases` with an empty `sample_utterances` list, a duplicate title for the agent, or another tenant's agent, then the response is 422 (404 for the other tenant's agent) and nothing changes.
- **CAT-06** — Given a published version, then its snapshot contains `description` and `routable`; editing the draft description does not change the catalog until publish.
- **CAT-07** — Given generated routing cases, then none of their utterances appears among the indexed entries; a routing run stores one result per enabled case with the chosen agent, method and latency, and its summary holds accuracy, the confusion matrix and passes against `min_routing_accuracy`.
- **CAT-08** — Given a catalog change, then exactly one routing run is queued for the tenant even when several agents are re-indexed together.
- **CAT-09** — Given a comparison run over cases including one vague case and a configured decision model, then the summary has one row per mode with right first choice, decided without asking, right when decided and latency p50 / p95, the `embedding` row reports no decision-model time, and the model is called at most once per case; without a decision model its row is marked not configured and no request is made.
