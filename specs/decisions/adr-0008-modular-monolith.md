---
type: Decision Record
title: ADR-0008 Modular monolith with ports and adapters
description: "One deployable still, but layered into ports, adapters, core, eight modules and a composition root, with the dependency rules enforced in CI."
status: stable
tags: [decision, architecture, modularity]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-08T00:00:00Z" }
---

# Context

[ADR-0005](/decisions/adr-0005-single-service.md) chose one process, and that choice still holds: the demo must stay cheap, reliable and quick to deploy. But it left the inside of the service unlayered, and after eleven change proposals that showed:

* Nothing in the package declared an interface. Swappability was duck typing plus module-global lazy singletons, so "switch the LLM provider by configuration" was only true for providers that happened to speak the OpenAI wire, and two hardcoded provider lists plus one vendor response quirk sat in Python.
* One route handler was imported and called as a library function by another.
* Fleet-learning code imported the demo business fixture.
* Three unrelated places knew a background job's kind string and its dedupe convention, and the handlers themselves were registered only as an import side effect, so losing one failed silently.
* Agent-configuration code reached the voice package for a value object; learning wrote five tables it did not own.

None of these is a bug today. All of them are reasons a second process could not be carved off later, and each is the kind of coupling that gets worse with every feature.

# Decision

Keep one deployable. Layer the package into `ports/`, `adapters/`, `core/`, `modules/` and `composition/`, with eight modules drawn where a service would be cut, as specified in [/architecture/modular-structure.md](/architecture/modular-structure.md).

* A module names a capability through a Protocol in `ports/`, or another module through that module's `contract` module. It never names an adapter.
* `composition/` is the only place an adapter is constructed, so which implementation runs is a configuration question.
* The module graph over `contract` imports is acyclic. A mutual dependency is broken with a port, not negotiated.
* Every rule is checked by `scripts/arch_check.py` in CI. Rules over folders that do not exist yet pass vacuously, so the ratchet is in place before the code moves.

# Alternatives considered

* **Leave it as it is and split later.** Rejected: the couplings above are cheap to remove now and get more expensive per feature. The LLM provider list in particular was already blocking a stated requirement.
* **Split into services now.** Rejected: ADR-0005's reasons stand, and the in-process event bus, the live-session registry and the per-process knowledge cache would all have to be solved at once.
* **Enforce the boundaries by review.** Rejected on evidence: three stable specs already assert that only `voiceai/voice/` may import Pipecat, and nothing checked it. A rule that is not executed is a wish.
* **A full hexagonal rewrite with a unit-of-work abstraction.** Rejected as ceremony: `Depends(get_session)` and the session factory already give two working seams, and a unit of work would rewrite every background call site and the test fixtures to say the same thing.

# Consequences

* Adding an LLM provider is a `models.yaml` entry plus an environment variable; a new wire protocol is one adapter file. Nothing else changes.
* `/healthz` reports whichever providers `models.yaml` declares, so its `providers` keys are data rather than a fixed list.
* A missing job handler is a start-up error instead of a job that silently retries to failure.
* Cross-module calls go through a `contract` function, which is what later becomes an HTTP client.
* New code costs more ceremony: a capability needs a Protocol and a wiring line, not just an import. That is the price of the seam, and `arch_check` makes it non-optional.
* Horizontal scaling is still out of scope and still needs the CP ADR-0005 asks for. This decision builds the seams that CP will plug into; it does not deliver it. Database migrations are likewise untouched — `init_db` still creates tables.
