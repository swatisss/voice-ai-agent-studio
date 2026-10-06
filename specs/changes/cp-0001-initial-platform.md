---
type: Change Proposal
title: CP-0001 Initial platform build
description: Build the v1 platform - builder, voice and text test calls, escalation with groundwork packets, fleet learning with eval-gated fixes - for the healthcare & insurance demo.
status: stable
cp_state: implemented
tags: [platform, v1]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Why

Business units want phone-style support automation without months of bespoke work. A human-handled call costs roughly $7–12 versus under $1.20 for an AI-resolved one. See [/product/vision.md](/product/vision.md).

# What changes

A greenfield platform where a business unit (tenant) configures knowledge, tools, skills and a persona, and gets an agent that:

1. resolves routine calls end-to-end (voice in the browser, or text),
2. escalates hard or risky cases with a groundwork packet to a human console,
3. analyzes every call, clusters recurring gaps, drafts fixes, proves them with simulated replays, and ships them after human approval.

# Affected specs

All specs in this bundle are created by this CP.

# Acceptance criteria

Defined in each component spec. The demo-level gate is [/product/demo-script.md](/product/demo-script.md): all three acts must run end-to-end on the seeded data.

# Tasks

See [/build/task-plan.md](/build/task-plan.md) (T01–T22).

# Risks and rollout

* Voice quality depends on third-party STT/TTS latency — text chat is a first-class fallback.
* Groq free-tier limits — enable billing before rehearsals.
* Synthetic data only; no PHI. See [/product/healthcare-compliance.md](/product/healthcare-compliance.md).

# Out of scope

See [/product/scope.md](/product/scope.md).
