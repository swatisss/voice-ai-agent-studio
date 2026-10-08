---
type: Architecture
title: Modular structure
description: "The backend's layers, the eight modules, the ports and contracts between them, and the CI rules that keep the boundaries where a service could later be cut."
status: stable
tags: [architecture, modularity, ports, boundaries]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-08T00:00:00Z" }
---

# Why this exists

The service is one deployable and stays one ([/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)). What this spec fixes is the *inside*: where the seams are, which direction each dependency points, and what is swappable by configuration. A boundary nobody checks erodes, so every rule here is enforced by `scripts/arch_check.py` in CI rather than by review habit.

See [/decisions/adr-0008-modular-monolith.md](/decisions/adr-0008-modular-monolith.md) for the decision and its alternatives.

# Layers

Code lives in one of five layers. The layer decides what a file may import, and nothing else.

| Layer | Holds | May import |
|---|---|---|
| `ports/` | Protocols and the data classes they pass. No behaviour, no I/O. | standard library, pydantic, `ports` |
| `adapters/` | One implementation of one port against one external thing. | `ports`, `core.config`, `core.errors` |
| `core/` | Cross-cutting infrastructure with no domain knowledge: settings, database, errors, tenancy, prompt loading, the event bus accessor, the job queue, the LLM gateway. | `ports`, `adapters`, `core` |
| `modules/` | The product, in eight modules. Each owns its rules, its HTTP surface and a documented set of tables. | `ports`, `core`, other modules **through their `contract` module only** |
| `composition/` | The assembly: it builds the FastAPI app, chooses every adapter from configuration, registers job handlers and seeds demo data. | everything |

Only `composition/` knows which adapter is in use. A module names a capability it needs; it never names the thing that provides it.

# Modules

Each module is a folder with the same shape. Not every module needs every file.

| File | Holds |
|---|---|
| `domain.py` | Pure rules and value objects. No database, no network, no clock. |
| `tables.py` | The module's own ORM tables, once it has them — see **Tables** below. |
| `repo.py` | Row access. Every helper for a tenant-owned table takes `tenant_id` as a required argument. |
| `service.py` | Use cases. All business logic lives here, never in a route handler. |
| `api.py` | A thin FastAPI router: parse, call the service, serialise. |
| `contract.py` | The module's only public entry point for other modules. |

| Module | Responsibility | Tables |
|---|---|---|
| `agentcfg` | Agents, drafts, versions and snapshots, personas, tools, skills, use cases. | `agents`, `agent_versions`, `personas`, `tools`, `skills`, `use_cases` |
| `conversation` | The turn loop, call lifecycle, tool execution, transcripts, caller feedback. Shared by voice, text and simulation. | `calls`, `call_events`, `call_feedback` |
| `voice` | The Pipecat pipeline, turn aggregation, live voice controls. The only module with a volatile third-party blast radius. | — |
| `knowledge` | Ingestion, chunking, embedding, search with a no-answer threshold. | `knowledge_docs`, `knowledge_chunks` |
| `handoff` | The human console: queue, groundwork packet, accept, resolve. Implements the `HandoffDesk` port the turn loop announces to. | `escalations` |
| `learning` | Analysis, clustering, impact, fix drafting, evaluation. | `call_analyses`, `clusters`, `fix_proposals`, `eval_runs`, `eval_results`, `eval_scenarios` |
| `analytics` | Dashboard read model. It reads across modules and owns no tables — which is exactly why it has a name: without one, the dashboard reaches into another module's internals. | — |
| `businessmock` | The simulated insurer and healthcare systems the demo calls. It stands in for systems outside the product, so nothing in the product may depend on it. | — |

`tenants` and `jobs` belong to `core`, not to a module.

# Tables

The table column above is **ownership, not file layout**. All twenty tables are declared centrally in `core/tables.py` today, and that is deliberate.

Splitting them into a `tables.py` per module was tried and reverted. The reason is concrete: twenty-eight places read another module's tables, and almost all of them are SQL joins — the call explorer joins four tables across three modules, the dashboard joins three across three. Routing those through contracts turns one join into several round-trips, which is a real performance change dressed as a refactor, and it buys nothing until a module actually leaves the process. On the day one does, its tables move with it and its callers lose the join they can no longer make anyway.

What holds now, and keeps that day cheap:

* Ownership is written down above, so there is no argument about which module a table belongs to.
* A module reads another's tables only to **read**. Writing another module's table goes through that module's `contract` — `apply_fix_and_publish` exists for exactly this reason.
* Cross-table links are id columns with string `ForeignKey` targets. There is not one `relationship()` in the codebase, which is what makes a later split a move rather than a redesign. MOD-07 holds that line from the moment a module gets its own `tables.py`.
* `core/db.register_tables()` names every table module explicitly, because a table module nobody imports vanishes from the schema with no error. The table count asserted in `tests/test_agents_tenancy.py` is the guard.

Escalation *triggers* (the safety screen, the repeated-no-answer and tool-failure rules) stay inside `conversation`'s turn loop. They cannot leave it. `handoff` begins where a human does.

# Ports and contracts

Both are declared boundaries; the difference is which way the dependency points.

* A **contract** is for a dependency that stays a call after a split: it becomes a request to a known service. The callee owns `contract.py`.
* A **port** is for a dependency that must *invert*, because the caller may not know the callee exists, or because the implementation is the thing being swapped. `ports/` owns the Protocol and `composition/` injects an implementation.

| Port | Need it covers | Adapters |
|---|---|---|
| `llm.ChatClient` | One LLM provider's wire protocol. | `openai_compatible` (Groq, OpenRouter, OpenAI and anything else speaking it) |
| `embeddings.Embedder` | Turning text into vectors. | `fastembed`, `hash` |
| `toolcaller.ToolCaller` | Executing an agent's HTTP tool. Also where a future MCP transport plugs in. | `http`, `asgi`, `routing` |
| `eventbus.EventBus` | Fan-out of live updates. Sync, non-blocking and best-effort by contract, so a remote adapter must buffer locally instead of adding latency to a turn or awaiting inside an open transaction. | `inprocess` |
| `postcall.PostCallAnalysis` | Asking for a finished call to be analysed. | `learning` |
| `handoff.HandoffDesk` | Handing a live call to a human, and reading what became of it. Carries the category vocabulary, since the caller must name one. | `handoff` |
| `callerdirectory.CallerDirectory` | Identities for simulated callers. | `businessmock`, `anonymous` |
| `voicecontrol.VoiceControl` | Changing voice or turn detection on a running call. | `voice` |

Three of these are ports for the same structural reason: `conversation` is upstream of everything that reacts to a call. `learning` names it (to drive simulated calls and read transcripts), `handoff` names it (to build a packet from a transcript), and `voice` names it (to run the brain). So `conversation` must name none of them back, or the module graph cycles — and each thing it genuinely needs from them is a port instead. The asymmetry is the design, not an accident.

Running a simulated call, by contrast, is a plain `conversation` **contract** call: the dependency points the way it already points, and that function is what becomes an HTTP client if fleet learning is extracted. A port there would have been ceremony.

Note what a port costs: the capability is reached through an accessor in `core/` rather than by importing the implementing module. That indirection is the price of the acyclic graph, and `arch_check` is what makes it non-optional.

Post-call analysis MUST NOT be triggered through the event bus. The bus drops events when a subscriber is full, which is right for a live feed and wrong for durable work.

# Adding a provider, adapter or module

* A provider speaking a wire we already have: one `providers:` entry in `apps/api/config/models.yaml` and its API key environment variable. No Python change. See [/architecture/llm-gateway.md](/architecture/llm-gateway.md).
* A new wire: one module in `voiceai/adapters/llm/` named after the wire, exposing `build(cfg)`.
* Any other adapter: implement the port, then choose it in `composition/`.
* A new module: a folder with a `contract.py`, and an entry in the table above.

# Extraction order

When a module does leave the process, these come out most easily first, because each already depends only on ports and contracts for everything but reads: `businessmock`, then `knowledge`, then `voice` (ADR-0005 already names a sticky voice tier), then `learning`. Anything before that needs the horizontal-scaling CP that ADR-0005 requires: a durable event bus, a separate worker, and session affinity.

# Acceptance

- **MOD-01** — Given a module that imports another module by any path other than that module's `contract`, or two modules whose `contract` imports form a cycle, when `arch_check` runs, then it fails and names the offending import or the cycle.
- **MOD-02** — Given a module that imports anything under `adapters/`, when `arch_check` runs, then it fails and says to depend on a port instead; and given the same import from `composition/` or `core/`, then it passes.
- **MOD-03** — Given a file under `ports/` that imports any `voiceai` path other than `voiceai.ports`, when `arch_check` runs, then it fails.
- **MOD-04** — Given a Pipecat import anywhere outside the voice module, when `arch_check` runs, then it fails.
- **MOD-05** — Given a non-empty module whose docstring has no `Spec:` line, or whose `Spec:` line names a spec file that does not exist, when `arch_check` runs, then it fails and names the file.
- **MOD-06** — Given a module other than `businessmock` that imports `businessmock`, even through its `contract`, when `arch_check` runs, then it fails; and given the same import from `composition/`, then it passes.
- **MOD-07** — Given a module's `tables.py` that calls `relationship()`, when `arch_check` runs, then it fails and says to link modules by id column instead; and given the word only in prose, then it passes.
- **MOD-08** — Given the application is built, when the registered job handlers are inspected, then they are exactly the kinds the service declares, and a declared kind whose module failed to register raises at start-up instead of failing silently when the job runs.
