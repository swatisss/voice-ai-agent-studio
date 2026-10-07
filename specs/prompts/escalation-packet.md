---
type: Prompt
title: Escalation packet prompt
description: Turns the call transcript, tools used and escalation reason into the structured groundwork packet a human reads in ten seconds.
status: stable
tags: [prompt, analysis, escalation]
llm_role: analysis
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Variables

`transcript` (lines `Caller: ...` / `Agent: ...` / `Tool get_claim_status → {...}`), `tools_used` (bullet list of summaries), `reason_category`, `reason_detail`, `verified` (`yes`/`no`), `member_ref`.

# Output

JSON matching the packet schema in [/architecture/escalation.md](/architecture/escalation.md).

# Prompt

```text
You prepare handoff notes for a human customer-support specialist who is about to take over a call from an AI assistant. The specialist must understand the situation in ten seconds and must not need to ask the caller to repeat anything.

Escalation reason: {{reason_category}} — {{reason_detail}}
Caller identity verified: {{verified}} {{member_ref}}

Tools the assistant used:
{{tools_used}}

Transcript:
{{transcript}}

Return JSON with exactly these fields:
- summary: 2-3 plain sentences: who is calling, what they want, what has happened so far.
- intent: snake_case label for the caller's main goal (for example claim_appeal, claim_status, add_dependent_newborn, prior_auth_status).
- entities: object of identifiers mentioned or found (claim_id, auth_id, member_ref, provider, dates, amounts). Only include values that appear in the transcript or tool results.
- already_tried: list of short past-tense steps the assistant completed, including results (for example "Looked up claim C-31544: denied, out-of-network facility").
- escalation_reason: {category, detail} — use the category given above; write a clear one-sentence detail.
- sentiment: {start, end, trend} where start/end are one of positive, neutral, frustrated, angry, distressed and trend is one of improving, stable, declining.
- suggested_next_action: one sentence telling the specialist the most useful next step. Do not promise outcomes to the caller.
- caller_verified: true or false.

Use only information from the transcript and tool results. Do not invent facts.
```
