---
type: Glossary
title: Glossary
description: Shared vocabulary used across specs, code and UI labels.
status: stable
tags: [product, glossary]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

| Term | Meaning |
|---|---|
| **Tenant** | A business unit using the platform (e.g. *Evergreen Health · Member Services*). All data is scoped to one tenant. |
| **Agent** | A configured AI agent: persona + policy + knowledge + tools + skills + model choice. Has an editable **draft** and published **versions**. |
| **Agent version** | Immutable snapshot of an agent's config. Every call records the version that handled it. |
| **Persona** | Name, voice, greeting, speaking style and disclosure line. |
| **Policy** | Rules, escalation conditions, things the agent must never do, max turns, handoff and holding messages. |
| **Tool** | A callable HTTP API with a JSON-schema parameter list (e.g. `get_claim_status`). |
| **Skill** | A plain-English procedure for one kind of request: when it applies, steps, which tools it uses, when to escalate. |
| **Knowledge article / doc** | A document the agent can search. Split into chunks and embedded. |
| **Call** | One conversation (channel `voice`, `text` or `simulation`). |
| **Turn** | One caller utterance plus the agent's response. |
| **Containment** | A call resolved without a human. |
| **Escalation** | Handing a call to a human, with a reason category. |
| **Groundwork packet** | Structured handoff: summary, intent, entities, what was tried, reason, sentiment, suggested next action. |
| **Disposition** | The human's outcome code when closing an escalation. |
| **Call analysis** | Post-call structured judgment: outcome, intent, root cause, gap summary. |
| **Root cause** | Why a call was escalated: `missing_knowledge`, `missing_skill`, `tool_error`, `policy_required`, `safety`, `caller_requested`, `asr_error`, `agent_error`, `other`. |
| **Fixable** | Root causes the platform may propose a fix for: `missing_knowledge`, `missing_skill`, `agent_error`. |
| **Cluster** | A group of calls sharing a similar gap. Has a name, size, cost impact and status. |
| **Fix proposal** | A drafted change (knowledge article or skill + tool) for a cluster. |
| **Eval run** | Simulated replay of a cluster's cases plus regression scenarios against the current version (baseline) and the proposal (candidate), graded by a judge. |
| **Regression scenario** | A saved caller goal the agent already handles; must keep passing. |
| **Role (LLM)** | A job the LLM does: `realtime`, `analysis`, `drafting`, `simulator`, `judge`. Each maps to a provider + model. |
| **OKF** | Open Knowledge Format — Markdown + YAML frontmatter bundle format used for these specs and importable as knowledge. |
