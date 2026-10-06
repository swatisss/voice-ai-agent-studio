---
type: Prompt
title: Cluster naming prompt
description: Produces a short name and one-sentence description for a cluster of similar escalation gaps.
status: stable
tags: [prompt, drafting, learning]
llm_role: drafting
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Variables

`gap_summaries` (bullet list, up to 5), `root_causes` (counts).

# Output

`{"name": "<3-6 words, sentence case>", "description": "<one sentence>"}`

# Prompt

```text
These are short descriptions of why several phone calls to a health insurer's AI assistant had to be escalated to humans:

{{gap_summaries}}

Root causes: {{root_causes}}

Return JSON with:
- name: a 3-6 word sentence-case label for the shared topic (for example "Adding a newborn to coverage").
- description: one sentence describing what callers need that the assistant could not provide.
```
