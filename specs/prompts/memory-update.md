---
type: Prompt
title: Memory update decision
description: For one candidate fact, decide against the most similar remembered facts whether to add it, let it supersede an old fact, confirm an old fact, or do nothing.
status: stable
tags: [prompt, memory, analysis]
llm_role: analysis
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Variables

| Variable | Source |
|---|---|
| `candidate` | one fact from [/prompts/memory-extract.md](/prompts/memory-extract.md) |
| `similar` | up to five active facts of the same scope, most similar first, one `- [id] (date) text` line each, or `- (none)` ([/architecture/agent-memory.md](/architecture/agent-memory.md)) |

# Prompt

```text
You keep an agent's memory of one member accurate. A new fact was learned in today's call:
{{candidate}}

Facts already remembered that may be related:
{{similar}}

Choose exactly one action:
- ADD: the new fact is new information.
- SUPERSEDE: the new fact contradicts or replaces one remembered fact (for example a changed preference). Give that fact's id; it will be retired, not deleted.
- CONFIRM: the new fact says the same as one remembered fact. Give that fact's id.
- NOOP: the new fact is not worth keeping next to what is remembered.

Return JSON only: {"action": "ADD|SUPERSEDE|CONFIRM|NOOP", "target_id": "<id or null>", "reason": "<one short sentence>"}
```
