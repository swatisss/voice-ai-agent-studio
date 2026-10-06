---
type: Component Spec
title: Escalation
description: When and how calls are handed to humans - triggers, reason categories, the groundwork packet, the safety screen, and the human console lifecycle.
status: stable
tags: [architecture, escalation, handoff]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Reason categories

| Category | Meaning | Typical source |
|---|---|---|
| `caller_requested` | Caller asked for a person | LLM |
| `policy_required` | Policy says a human must handle it (appeals, grievances, disputes) | LLM, skill `escalate_when` |
| `safety` | Emergency or self-harm language | Safety screen |
| `knowledge_gap` | No approved information to answer | LLM or no-answer streak |
| `capability_gap` | Request needs an action the agent has no tool for | LLM |
| `tool_failure` | Business API errors prevent progress | Tool-error streak |
| `frustration` | Caller is upset and not progressing | LLM |
| `other` | Anything else, incl. max turns and LLM outage | Runtime |

# Triggers

| Trigger | Condition | Category |
|---|---|---|
| Model decision | Model calls `escalate_to_human` | as given |
| Safety screen | Caller text matches a safety phrase (below) | `safety` |
| No-answer streak | `no_answer_streak` ≥ 2 | `knowledge_gap` |
| Tool-error streak | `tool_error_streak` ≥ 2 | `tool_failure` |
| Max turns | `turns` ≥ `policy.max_turns` (default 16) | `other` |
| LLM outage | Gateway fails after fallback | `other` |

Safety phrases (case-insensitive substring): `suicide`, `kill myself`, `end my life`, `hurt myself`, `want to die`, `overdose`, `chest pain`, `can't breathe`, `cannot breathe`, `stroke`, `unconscious`, `severe bleeding`, `heart attack`.

# Escalation procedure

1. If already escalated, do nothing (idempotent).
2. Set call status `escalated`; create the `escalations` row: `status: waiting`, category, detail, `packet_status: pending`.
3. Speak/return the handoff message (`policy.handoff_message`, or the safety message for `safety`).
4. Publish `escalation.created` to topic `console` and `call.escalated` to `call:{id}`.
5. Build the packet **immediately** in a background task (not the job queue): LLM `analysis` role with [/prompts/escalation-packet.md](/prompts/escalation-packet.md) over transcript + state. On success `packet_status: ready`; on failure the deterministic fallback packet with `packet_status: fallback`. Publish `escalation.updated`.
6. The call stays open in *holding* mode (holding message on further caller turns) until the caller hangs up.

# Groundwork packet

```json
{
  "summary": "2–3 sentences a human can read in 10 seconds",
  "intent": "snake_case intent, e.g. claim_appeal",
  "entities": { "claim_id": "C-31544", "member_ref": "EVG-337120" },
  "already_tried": ["Verified identity (member ID + DOB)", "Looked up claim C-31544: denied, out-of-network facility"],
  "escalation_reason": { "category": "policy_required", "detail": "Caller wants to appeal a denied claim" },
  "sentiment": { "start": "neutral", "end": "frustrated", "trend": "declining" },
  "suggested_next_action": "One sentence for the human",
  "caller_verified": true
}
```

Allowed sentiment values: `positive`, `neutral`, `frustrated`, `angry`, `distressed`; trend: `improving`, `stable`, `declining`.

**Fallback packet** (no LLM): `summary` = last two caller utterances joined; `intent` = `unknown`; `entities` = `{member_ref}` if verified; `already_tried` = `tools_used[].summary`; reason from the escalation row; sentiment `neutral/neutral/stable`; `suggested_next_action` = "Review the transcript and confirm the caller's request."

# Console lifecycle

`waiting` → (`POST /accept`, sets `assignee`, `accepted_at`) → `accepted` → (`POST /resolve` with `disposition` + `resolution_note`) → `resolved`.

Dispositions: `resolved_by_human`, `appeal_filed`, `callback_scheduled`, `transferred_department`, `no_action_needed`, `other`.

The `resolution_note` is required (min 10 characters) — it is the evidence fleet learning drafts fixes from ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)).

# Acceptance

- **ES-01** — Given a caller says "I have chest pain", when the turn runs, then no LLM request is made, the safety message is returned and an escalation with category `safety` is created.
- **ES-02** — Given two consecutive `search_knowledge` results with `no_answer`, when the turn ends, then the call is escalated with category `knowledge_gap`.
- **ES-03** — Given two consecutive agent-tool errors, when the turn ends, then the call is escalated with category `tool_failure`.
- **ES-04** — Given an escalation, when created, then a `console` event is published within the same request and the packet becomes `ready` or `fallback` without waiting for the job worker.
- **ES-05** — Given the packet LLM fails, when the packet is built, then the fallback packet is stored with `packet_status: fallback` and `already_tried` lists the tools used.
- **ES-06** — Given an escalation in `waiting`, when resolve is called without accept, then the API returns 409.
- **ES-07** — Given resolve with a note shorter than 10 characters, then the API returns 422.
- **ES-08** — Given the model calls `escalate_to_human` twice, then only one escalation row exists.
