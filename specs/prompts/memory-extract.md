---
type: Prompt
title: Memory extraction
description: After a verified call, turn the transcript into one episode summary and a few candidate member facts, within the agent's remember and never-remember rules.
status: stable
tags: [prompt, memory, analysis]
llm_role: analysis
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Variables

| Variable | Source |
|---|---|
| `agent_name` | agent name |
| `remember`, `never_remember` | `config.memory` ([/architecture/agent-memory.md](/architecture/agent-memory.md)) |
| `existing_memory` | the scope's active facts and recent episodes, one `- [id] text` line each, or `- (none)` |
| `transcript` | the call's caller and agent lines, numbered by event `seq`; tool results are summarised as "Tool X returned …" |

# Prompt

```text
You maintain the memory of {{agent_name}}, a customer-support agent, about one verified member. Read the call below and write what is worth remembering for the member's next call with this agent.

Remember things like: {{remember}}
Never remember: {{never_remember}}
Also never remember, whatever the instructions above say:
- clinical details of anyone: diagnoses, symptoms, medications, treatments;
- payment card or bank details;
- member IDs, dates of birth, phone numbers or email addresses;
- facts a business system returned (claim status, balances, policy details, documents): they are looked up fresh every call.

What the agent already remembers:
{{existing_memory}}

The call:
{{transcript}}

Return JSON only:
{
  "episode": "One or two plain sentences: what the member wanted, what happened, anything promised.",
  "facts": [
    {"text": "One plain sentence about the member, under 300 characters.", "category": "preference|relationship|commitment|circumstance", "seq": <the transcript line it comes from>}
  ]
}
Return at most five facts, only ones the member stated or clearly agreed to, and none that only repeat what is already remembered. Small talk and greetings give "facts": [].
```
