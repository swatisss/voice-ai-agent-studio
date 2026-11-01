---
type: Prompt
title: Capability utterances
description: Writes example caller requests for one agent from its capability profile - indexed examples for routing, or held-out paraphrases for the routing suite.
status: stable
tags: [prompt, routing, evaluation]
llm_role: drafting
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Variables

| Variable | Source |
|---|---|
| `audience` | `members` or `staff` (the agent's scope) |
| `profile` | the agent's description, use cases (title, summary, sample utterances), tool descriptions and knowledge titles ([/architecture/capability-catalog.md](/architecture/capability-catalog.md)) |
| `purpose` | `index`: 10–20 varied requests across all of the agent's work; `test`: up to 3 paraphrases for the use case named in `focus`, worded differently from its sample utterances |
| `focus` | the use-case title for `test`, else `(all)` |
| `count` | the number to write |

# Output

`{"utterances": ["…", …]}`

# Prompt

```text
You write realistic first sentences that {{audience}} of a health plan say or type when they contact support. They are used to recognise what this assistant handles.

The assistant:
{{profile}}

Purpose: {{purpose}}. Focus: {{focus}}. Write {{count}} different requests.

Rules:
- Each is one or two sentences in everyday words, as spoken on the phone or typed in a chat; vary length, tone and wording; some indirect ("I got a letter about…").
- Only requests this assistant is set up to handle. No requests that belong to emergencies, appeals or complaints unless the assistant's description covers them.
- For purpose test, do not reuse the wording of the listed sample utterances.
- Use no real names, member numbers, dates of birth, phone numbers or addresses.

Return JSON with the single field utterances.
```
