---
type: Decision Record
title: ADR-0001 Spec-driven development with OKF
description: Specs live in an Open Knowledge Format bundle in the repo, are the source of truth, and ship in the same commits as code.
status: stable
tags: [decision, sdd, okf]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Context

The platform is built largely by coding agents. Agents need precise, navigable context; humans need to review intent rather than thousands of lines of code. Changes must stay traceable after the hackathon.

# Decision

* Specs are Markdown concepts with YAML frontmatter in an **OKF v0.2** bundle at `specs/` — plain files, readable on GitHub, parseable without an SDK, with `index.md` files for progressive disclosure.
* The workflow in [/process/sdd-workflow.md](/process/sdd-workflow.md) is mandatory and enforced by `scripts/spec_check.py` and git hooks.
* Prompts are specs and are loaded verbatim by the code.
* The platform can import OKF bundles as knowledge, so the same format serves product knowledge and engineering specs.

# Consequences

* Every behavior change costs a spec edit first — slower for trivial changes, much faster review and onboarding.
* Spec drift is caught mechanically (spec-first rule, acceptance-ID citations) rather than by memory.
* OKF is an early draft standard; we use only its stable core (frontmatter `type`, `index.md`, `log.md`, links) and keep extra fields (`status`, `cp_state`) as permitted extensions.
