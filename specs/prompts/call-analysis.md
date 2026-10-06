---
type: Prompt
title: Call analysis prompt
description: Post-call structured judgment - outcome, intent, root cause, fixability, generic gap summary, caller goal and resolution summary.
status: stable
tags: [prompt, analysis, learning]
llm_role: analysis
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Variables

`transcript`, `escalation` (category, detail, disposition, resolution note — or `none`), `search_results_summary` (count of `no_answer` searches and queries), `tools_available` (names + descriptions of the agent's tools).

# Output

JSON with the fields of `call_analyses` in [/architecture/fleet-learning.md](/architecture/fleet-learning.md) (`fixable` is computed by code, not the model).

# Prompt

```text
You review completed calls between callers and an AI phone assistant for a health insurer, so the platform can learn which gaps cause escalations.

Tools the assistant had:
{{tools_available}}

Knowledge searches with no approved answer: {{search_results_summary}}

Escalation: {{escalation}}

Transcript:
{{transcript}}

Return JSON with:
- outcome: "resolved" if the assistant fully handled the caller's request without a human; "escalated" if the call was handed to a human; "abandoned" if the caller left before resolution without escalation.
- intent: snake_case label of the caller's main goal (claim_status, benefits_deductible, id_card_replacement, find_provider, claim_appeal, add_dependent_newborn, prior_auth_status, ...).
- root_cause: for resolved calls "none". Otherwise exactly one of:
  missing_knowledge (the assistant lacked approved information to answer),
  missing_skill (the request needed an action or lookup the assistant had no tool for),
  tool_error (a business system failed),
  policy_required (policy requires a human, e.g. appeals, grievances, disputes),
  safety (emergency or self-harm),
  caller_requested (caller asked for a person without a deeper unmet need),
  asr_error (speech was misrecognized),
  agent_error (the assistant had what it needed but behaved incorrectly),
  other.
- gap_summary: for escalated or abandoned calls, one generic sentence naming what was missing, written so similar calls produce similar sentences (for example "How to add a newborn to an existing plan" or "Checking the status of a prior authorization"). Empty string for resolved calls.
- caller_goal: one sentence describing what the caller wanted, written as an instruction for someone role-playing this caller (for example "You recently had a baby and want to know how to add her to your health plan").
- resolution_summary: what actually resolved the request: the assistant's answer, or the human specialist's resolution note. Empty string if unresolved.
- sentiment_start and sentiment_end: one of positive, neutral, frustrated, angry, distressed.
```
