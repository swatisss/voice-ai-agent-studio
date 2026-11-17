---
type: Component Spec
title: Escalation
description: When and how calls are handed to humans - triggers, reason categories, the groundwork packet, the safety screen, and the human console lifecycle.
status: draft
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
| `verification_failed` | Three failed identity-verification attempts in one call ([/architecture/caller-verification.md](/architecture/caller-verification.md)) | Runtime |
| `transfer_failed` | An agent asked for a transfer but no other agent fits, or the conversation reached 3 transfers ([/architecture/agent-transfer.md](/architecture/agent-transfer.md)) | Runtime |
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

**History is not an emergency** ([CP-0042](/changes/cp-0042-safety-and-transfers-at-the-front-desk.md)). The three medical-history phrases `chest pain`, `heart attack` and `stroke` do not match when the same line carries a history marker: `last year`, `last month`, `years ago`, `months ago`, `weeks ago`, `history of`, `when I was`, `previously`, `in the past`, or `in` followed by a year (`19xx`, `20xx`). A present-tense cue in the line (`right now`, `at the moment`, `having a`, `i'm having`, `i am having`) matches even with a marker. Every other phrase, and every Hindi phrase ([/architecture/languages.md](/architecture/languages.md)), matches as before. Underwriting and claims conversations mention past conditions; a sales call must be able to hear "I had a heart attack last year" without ending.

**A request for a person** ([CP-0048](/changes/cp-0048-live-conversation-qa-fixes.md), ES-13). A caller line that asks for a person ("I want to speak to a human", "agent please", "get me a manager", "can I talk to someone real", "put me through to a representative") escalates at once with category `caller_requested` and the policy's hand-off line, on every agent turn and at the front desk; the model is not asked. "Talk to someone" alone does not match, and neither does a person mentioned in passing ("a person who died"). Hindi and Hinglish requests are left to the model.

The screen runs on every agent turn (ES-01) and, in a routed conversation, at the front desk before routing ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md), step 0, RTE-21).

**Categories** ([CP-0046](/changes/cp-0046-final-qa-fixes.md), QA-06): `caller_requested` only when the caller asked for a person; `knowledge_gap` when there is no approved answer; `capability_gap` when no tool or skill exists; `policy_required` when a rule sends it to a person; `frustration` when the caller is upset. The groundwork packet's `entities` never list the emergency numbers (999, 116 123) the safety message speaks (QA-14).

# Escalation procedure

1. If already escalated, do nothing (idempotent).
2. Set call status `escalated`; create the `escalations` row: `status: waiting`, category, detail, `packet_status: pending`.
3. Speak/return the handoff message (`policy.handoff_message`, or the safety message for `safety`).
4. Publish `escalation.created` to topic `console` and `call.escalated` to `call:{id}`.
5. Build the packet **immediately** in a background task (not the job queue): LLM `analysis` role with [/prompts/escalation-packet.md](/prompts/escalation-packet.md) over transcript + state. On success `packet_status: ready`; on failure the deterministic fallback packet with `packet_status: fallback`. Publish `escalation.updated`.
6. **The AI call ends** once the handoff (or safety) message has been delivered, with reason `handoff` ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-01), as virtual-agent platforms do when a conversation is handed to a human. The escalation stays `waiting` for the console; the caller is then offered the feedback prompt like any ended call (not on a phone call, which has no page). On a phone call whose agent has `telephony.transfer_to`, the live call is also redirected to that destination after the message ([/architecture/telephony.md](/architecture/telephony.md), TEL-07). The *holding* reply (policy `holding_message`) survives only as a fallback for a session that is escalated yet still open. **A text conversation created through the public API stays open** after the hand-off so the customer and the specialist can exchange messages; resolving the escalation ends it ([/architecture/human-message-channel.md](/architecture/human-message-channel.md), [CP-0049](/changes/cp-0049-external-chat-app.md)).

**Voice in a media room** ([CP-0050](/changes/cp-0050-livekit-live-handover.md)). For a call with transport `livekit`, step 6 differs: after the hand-off message the call is **not** ended; it stays `escalated`, the escalation carries `voice_state: waiting`, the AI stays silent and a specialist may take the voice call, after which the AI segment ends `handoff` and the call continues between the caller and the specialist ([/architecture/hosted-media-room.md](/architecture/hosted-media-room.md), LKH-05, LKH-08). Steps 1 to 5 and the lifecycle below are unchanged; the console event adds `voice`.

Evaluation (simulated) calls also create an escalation row so judging can see the outcome, but they never reach the human console: no `console` events, no packet LLM call (deterministic fallback packet), and `GET /api/escalations` excludes them.

# Groundwork packet

```json
{
  "summary": "2–3 sentences a human can read in 10 seconds",
  "intent": "snake_case intent, e.g. claim_dispute",
  "entities": { "claim_id": "CL-70640", "member_ref": "NGH-714560" },
  "already_tried": ["Verified identity (member ID + DOB)", "Looked up claim CL-70640: declined, lower back conditions excluded"],
  "escalation_reason": { "category": "policy_required", "detail": "Caller disputes a declined claim" },
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
- **ES-09** — Given three verification results with `verified: false` in one call, then exactly one escalation with category `verification_failed` exists and the call ends `handoff`.
- **ES-08** — Given the model calls `escalate_to_human` twice, then only one escalation row exists.
- **ES-10** — Given a conversation with 3 transfers, when the agent calls `transfer_to_agent` again, then exactly one escalation with category `transfer_failed` is created, the hand-off message is delivered and the segment ends `handoff`.
- **ES-11** — Given the lines "I had a heart attack last year and I'm on blood thinners", "history of stroke", "chest pain when I was 40" and "I had chest pain in 2019", then `safety_match` is false; given "I have chest pain right now", "I'm having a heart attack", "I think I'm having a stroke", "I had a heart attack" (no marker) and "I want to end my life, it was last year too", then it is true ([CP-0042](/changes/cp-0042-safety-and-transfers-at-the-front-desk.md)).
- **ES-13** — Given any agent, when the caller says "I want to speak to a human", "agent please", "get me a manager right now" or "can I talk to someone real, this bot is useless", then the call escalates with `caller_requested` and the hand-off line without a model reply; "can I talk to someone about adding my baby" and "my aunt, a person I care for, died" do not escalate.
- **ES-12** — Given any agent and a caller turn "Full medical underwriting please, I had a heart attack last year", then the model is called, no escalation is created and the call continues ([CP-0042](/changes/cp-0042-safety-and-transfers-at-the-front-desk.md)).
- **LKH-17** — Given an escalation on a call with transport `livekit`, then after the hand-off message the call is not ended (status `escalated`, `voice_state: waiting`); the same escalation on a WebSocket, WebRTC, phone or text call ends the call `handoff` as before (CE-01). (Numbered in the `LKH` series to avoid clashing with other change proposals' ES numbers.)
