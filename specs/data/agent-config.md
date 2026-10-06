---
type: Config Schema
title: Agent configuration schemas
description: JSON shapes of the agent draft config, persona, policy, tool and skill definitions, and the immutable version snapshot.
status: stable
tags: [data, config, schema]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Draft config (`agents.draft_config`)

```json
{
  "persona": {
    "name": "Ava",
    "voice": "aura-2-thalia-en",
    "greeting": "Thanks for calling Evergreen Health member services, this is Ava.",
    "disclosure": "I'm a virtual assistant, and this call may be recorded for quality.",
    "style": "Warm, calm and concise. One question at a time. Plain language, no jargon."
  },
  "policy": {
    "rules": ["Verify identity with member ID and date of birth before sharing any member-specific information."],
    "escalate_when": ["The caller wants to file an appeal or grievance."],
    "never": ["Give medical advice or interpret symptoms."],
    "max_turns": 16,
    "handoff_message": "I'm connecting you with a specialist who will have all the details, so you won't need to repeat yourself.",
    "holding_message": "A specialist will be with you shortly. Thanks for your patience.",
    "safety_screen": true,
    "voice_filler": true
  },
  "tool_ids": ["..."],
  "skill_ids": ["..."],
  "knowledge_doc_ids": ["..."],
  "models": { "realtime": null }
}
```

| Field | Rules |
|---|---|
| `persona.name` | 1–40 chars |
| `persona.voice` | Deepgram Aura voice id; default `aura-2-thalia-en` |
| `persona.greeting`, `persona.disclosure` | required, ≤ 300 chars each |
| `policy.max_turns` | 4–40 |
| `policy.rules`, `policy.escalate_when`, `policy.never` | lists of ≤ 300-char strings, ≤ 30 items each |
| `models.realtime` | `null` (role default) or a model ref listed by `GET /api/models` |
| `*_ids` | must reference same-tenant, non-archived objects |

# Tool definition (`tools` row / API body)

```json
{
  "name": "get_claim_status",
  "description": "Look up one claim of the verified member by claim number (e.g. C-20931).",
  "method": "GET",
  "url": "/mock/healthcare/claims/{claim_id}",
  "parameters": {
    "type": "object",
    "properties": { "claim_id": { "type": "string", "description": "Claim number like C-20931" } },
    "required": ["claim_id"]
  },
  "requires_verification": true,
  "is_verification": false,
  "timeout_s": 8
}
```

`name` matches `^[a-z][a-z0-9_]{2,40}$` and is not `search_knowledge`, `escalate_to_human` or `end_call`. `parameters` must be a JSON Schema object with `type: object`.

# Skill definition (`skills` row / API body)

```json
{
  "name": "Claim status",
  "description": "Caller asks whether a claim was paid, denied or is still processing.",
  "instructions": "1. Verify identity.\n2. Ask for the claim number, or list recent claims with get_member_claims.\n3. Look up the claim and explain status, amounts and member responsibility in one or two sentences.",
  "required_tools": ["verify_member", "get_claim_status", "get_member_claims"],
  "escalate_when": "The caller disputes a denial or wants to appeal."
}
```

# Version snapshot (`agent_versions.config`)

The draft config **plus** resolved copies so the version is self-contained and immutable:

```json
{
  "persona": {...}, "policy": {...}, "models": {...},
  "knowledge_doc_ids": ["..."],
  "tools":  [ { "id": "...", ...full tool definition... } ],
  "skills": [ { "id": "...", ...full skill definition... } ]
}
```

Later edits to a tool or skill never change existing versions. Knowledge docs are referenced by id; docs are never edited in place — editing creates a new doc and archives the old one.

# Acceptance

- **DM-04** — Given a draft config with `max_turns: 2`, when saved, then the API returns 422.
- **DM-05** — Given a published version, when the underlying tool is edited, then the version's snapshot still holds the old definition.
