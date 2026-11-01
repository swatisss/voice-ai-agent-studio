---
type: Prompt
title: Router decision prompt
description: The LLM decision target of the supervisor - picks one agent from a shortlist of capability summaries, or none, with a confidence and a short reason.
status: deprecated
tags: [prompt, routing]
llm_role: router
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

Deprecated by [CP-0028](/changes/cp-0028-routing-strategies-and-local-laya.md): the LLM router is no longer a decision target. Kept for the history of CP-0025.

# Variables

| Variable | Source |
|---|---|
| `tenant_name` | `tenants.name` |
| `audience` | `members of the health plan` (scope `member`) or `staff of the health plan` (scope `staff`) |
| `request` | the routing input ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)): caller text, and for a transfer `Previous assistant could not help because: <reason>` |
| `agents` | one block per shortlisted agent: `- id: <agent_id>` then `  <profile summary>` |

# Output

`{"agent_id": "<one of the ids>" | null, "confidence": 0.0-1.0, "reason": "<= 120 chars"}`; an id that is not listed counts as an invalid answer (failover).

# Prompt

```text
You route requests for {{tenant_name}}. The people asking are {{audience}}. Pick the one assistant below that is set up to handle the request. Each assistant is described by what it handles.

Request:
{{request}}

Assistants:
{{agents}}

Rules:
- Choose by what the request is about, not by single words. "My claim was denied and I want to know what my plan covers" is about coverage if the question is what is covered, about claims if the question is the claim.
- If the request fits none of them, or is too vague to tell (for example only "hello" or "I have a question"), answer agent_id null.
- confidence is your probability that the chosen assistant is right: above 0.9 only when the request clearly matches one assistant's described work; below 0.6 when two could fit.
- reason: one short sentence naming what in the request decided it. Do not repeat member numbers, dates of birth or other identifiers.

Return JSON with the fields agent_id, confidence and reason.
```
