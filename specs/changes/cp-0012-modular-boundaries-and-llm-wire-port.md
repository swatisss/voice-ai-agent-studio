---
type: Change Proposal
title: CP-0012 Modular boundaries, ports and the LLM provider wire port
description: "Layer the backend into ports, adapters, core, eight modules and a composition root, enforce the boundaries in CI, and make adding an LLM provider a configuration change."
status: stable
cp_state: implemented
tags: [architecture, modularity, llm, tenancy]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-08T00:00:00Z" }
---

# Why

The service works, but after eleven change proposals an architecture review found that nothing inside the backend package declared an interface: a repo-wide search for `Protocol`, `ABC` or `abstractmethod` returned zero results. Every seam was duck typing plus a module-global lazy singleton. That produced concrete problems, each verified against the code:

1. **"Switch the LLM provider by configuration" was only half true.** It held for providers that happen to speak the OpenAI wire protocol, because a single client was re-pointed by `base_url`. Two hardcoded provider lists (one in the gateway's key lookup, one in `/healthz`) and one vendor response quirk (`x_groq`) meant a fourth provider needed Python edits, and a provider with its own protocol was impossible without rewriting the gateway. The settings class also had one field per provider key.
2. **A route handler was imported and called as a library function by another route** — the dashboard called the insights cluster handler directly — and a second route imported a third's serialiser. These break outright the day the two live in different services.
3. **Fleet-learning code imported the demo business fixture** to pick a caller identity, so production evaluation depended on demo data.
4. **Fix approval wrote five tables it did not own**: the agent draft, tools, skills, and a knowledge document's status.
5. **Three unrelated places knew the `analyze_call` job kind and its dedupe-key convention**, and the handlers were registered only as an import side effect of one module. A dropped import failed silently — the job recorded "no handler", retried to exhaustion and gave up, taking the analysis → cluster → proposal chain with it. The `chat` command already had this bug: it drains the queue but never imported the handler modules.
6. **Tenant isolation was manual.** Child rows were fetched by id alone, trusting that a parent had been checked. Not exploitable today, but the invariant was implicit, and this is a healthcare product.
7. **An invariant three stable specs assert — only `voiceai/voice/` may import Pipecat — was checked by nothing.**
8. Agent-configuration code reached into the voice package for a value object; the simulated business API, a stand-in for systems outside the product, was imported by the seeder and by learning.

None of 2–8 is a live defect. All of them are reasons a second process could not be carved out later, and each gets more expensive with every feature. The beneficiaries are whoever adds the next provider, whoever later splits a service, and the reviewer who has to believe the tenancy claim.

# What changes

1. **Adding an LLM provider becomes a configuration change.** A provider that speaks a wire we already have is one `providers:` entry in `models.yaml` plus its API key environment variable — no Python edit anywhere. A provider with its own protocol is one adapter file in `voiceai/adapters/llm/`. Per-provider quirks are declared as `options:` data instead of branches on a provider name.
2. **`/healthz` reports whichever providers `models.yaml` declares.** Its `providers` object gains a key when a provider is added, instead of listing three fixed names.
3. **A `wire` with no adapter, or whose SDK is absent, is skipped exactly like a missing API key** — the next fallback ref answers and start-up is unaffected. Adapter modules load lazily, so an unused provider's SDK is never imported.
4. **The package is layered** into `ports/`, `adapters/`, `core/`, eight `modules/` and `composition/`. A module names a capability through a Protocol, or another module through that module's `contract`; only the composition root constructs an adapter. Cross-module calls become the functions that later become HTTP clients.
5. **The boundaries are enforced in CI** by a new `scripts/arch_check.py`, including the Pipecat confinement that nothing checked, and that every module names a governing spec that exists.
6. **A missing job handler is a start-up error**, not a job that silently retries to failure. `voiceai chat` now registers handlers, so the analysis it drains actually runs.
7. **Tenant-owned rows are fetched through one shared helper** that requires a tenant and treats another tenant's id exactly like a missing one.

Nothing about the deployment changes: one process, one origin, one Cloud Run service.

# Affected specs

* [/architecture/modular-structure.md](/architecture/modular-structure.md) - new: the layers, the eight modules, the port and contract catalogue, the extraction order, MOD-01…MOD-08
* [/decisions/adr-0008-modular-monolith.md](/decisions/adr-0008-modular-monolith.md) - new: the decision, the alternatives rejected, the consequences
* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - `wire:` and `options:` on provider entries, a new "Adding a provider" section, quirks restated as configuration, LG-12…LG-15
* [/decisions/adr-0003-llm-gateway.md](/decisions/adr-0003-llm-gateway.md) - amendment: the one client became one adapter behind a port
* [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) - the shared owned-row helper, child rows filter on their own `tenant_id`, MT-05
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - explicit handler registration; the bus is best-effort and MUST NOT trigger durable work
* [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) - execution goes through the `ToolCaller` port; transport is adapter configuration
* [/architecture/knowledge.md](/architecture/knowledge.md) - the two embedders are adapters behind the `Embedder` port
* [/architecture/system-overview.md](/architecture/system-overview.md) - the components map onto the eight modules
* [/architecture/deployment.md](/architecture/deployment.md) and [/build/runbook-gcp.md](/build/runbook-gcp.md) - `/healthz` provider keys come from `models.yaml`
* [/process/conventions.md](/process/conventions.md) - register the `MOD` acceptance prefix; the `Spec:` docstring rule is now enforced

# Acceptance criteria

New: **MOD-01…MOD-08** in [/architecture/modular-structure.md](/architecture/modular-structure.md), **LG-12…LG-15** in [/architecture/llm-gateway.md](/architecture/llm-gateway.md), **MT-05** in [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md). All automated. No existing ID changes meaning; LG-08's `/healthz` assertion is now derived from configuration rather than a fixed three-key object.

# Tasks

1. Spec edits above, the `MOD` prefix registration and the [log](/log.md) entry (done in this CP).
2. `scripts/arch_check.py` with all seven static rules, wired into `.github/workflows/ci.yml`; tested on synthetic package trees so the rules are proven before the folders exist — covers MOD-01…MOD-07.
3. `ports/llm.py` and `adapters/llm/{registry,openai_compatible}.py`; the gateway keeps its whole public surface and delegates the wire; `config.py` resolves any provider's key by the name its entry declares; `/healthz` derives its provider list; `models.yaml` gains `wire:` and `options:` — covers LG-12…LG-15.
4. Explicit job-handler registration in the composition root and in `voiceai chat` — covers MOD-08.
5. One shared tenant-scoped owned-row helper — covers MT-05.
6. Move the infrastructure into `core/`, `ports/`, `adapters/` and `composition/`; delete the global application reference behind the `ToolCaller` port.
7. Create the eight modules with their contracts, and resolve the eight cross-module tangles with the ports and contracts the structure spec names.
8. Move business logic out of route handlers into module services.
9. Split the ORM tables per module.
10. Close: specs to `status: stable`, this CP to `implemented`, [log](/log.md) entry, repo map in `AGENTS.md`.

Tasks 6–9 change no behaviour and ship as `[no-spec]` commits after this one, per [/process/sdd-workflow.md](/process/sdd-workflow.md).

# Risks and rollout

* **No data migration.** No table, column or payload changes. `models.yaml` stays backward compatible: `wire` defaults to `openai` and the pre-`options` spelling of `stream_usage` is still read, so an unedited configuration behaves identically.
* **Demo impact: none intended.** The fake LLM short-circuits at the role level, before any wire is chosen, so tests and the scripted demo exercise no adapter.
* **The risk that matters is the move itself** (tasks 6–9): roughly 17 test modules change import paths. Mitigated by running the suite after each file move rather than at the end of a phase, and by `arch_check` failing the moment a boundary is crossed. The table split (task 9) has one real hazard — a `tables.py` that nothing imports disappears from the schema silently; the existing table-count assertion is the guard and is annotated as load-bearing.
* **Fallback**: tasks 2–5 are independent of 6–9. If the move has to be abandoned, the provider port, the CI rules, the handler registration and the tenancy helper all stand on their own.

# Out of scope

* **Horizontal scaling.** [ADR-0005](/decisions/adr-0005-single-service.md) still holds and still requires its own CP: a durable event bus, a separate worker and session affinity. This CP builds the seams that CP will plug into and delivers none of it. The live-session registry and live voice-controls map stay process-local on purpose — distributed session state is a problem, not a refactor.
* **Database migrations.** There are none: `init_db` creates tables. Every change here is schema-neutral, so nothing forces the issue, but this CP does not deliver migrations and nobody should read it as having done so.
* **The per-process knowledge search cache.** After the split it is reached through a contract, which hides the fact that a published article would be invisible to a second process until restart. The fix (a version row or a TTL) is a separate CP.
* **Publishing an event before its transaction commits.** Pre-existing: call analysis announces itself on the bus before the caller commits, so a rollback can leave an event claiming work that never happened. Separate CP.
* **A production adapter for a non-OpenAI wire.** The port, the registry and a test-registered wire prove the seam offline; a real Anthropic or Bedrock adapter is one file and is not written here.
* **The web app.** Its own gaps — untyped API responses at 23 call sites and a 461-line agent editor — are real but need response models on the API first. Separate CP.
