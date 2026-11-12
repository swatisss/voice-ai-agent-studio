---
type: Component Spec
title: Agent transfer
description: The built-in transfer_to_agent tool - how an agent hands a conversation to another agent through the supervisor, what carries over, segments, the transfer limit, voice behaviour, and how misroutes are scored and learned from.
status: stable
tags: [architecture, routing, runtime, evaluation]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Purpose

A caller who starts with a claim and then asks about coverage should not be escalated or told to call again. Inside a [conversation](/architecture/supervisor-routing.md), an agent that gets a request outside its scope hands it on; the supervisor, not the agent, picks who takes it. Agents do not know each other. Decision: [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# The tool

Built-in `transfer_to_agent` ([/architecture/agent-runtime.md](/architecture/agent-runtime.md)):

| Parameter | Rules |
|---|---|
| `reason` | ≤ 200 chars: what the caller needs that this agent does not handle |
| `summary` | ≤ 500 chars: what happened so far and what the caller wants, for the next agent; no member identifiers |

* Offered only on a segment of a conversation whose scope has another routable agent; never on a direct Studio or phone call to one agent, an outbound call or a simulation without a conversation.
* The [system prompt](/prompts/agent-system-prompt.md) tells the agent to use it when the request is outside its skills, tools and knowledge and another team may handle it, and to keep escalating to a human for what policy reserves for people.

# Flow

1. The model calls the tool. The runtime ends the turn without another model round (like `escalate_to_human`) and runs the supervisor with trigger `transfer`: input = the caller's last two turns + `reason`; the requesting agent is excluded.
2. **Chosen agent.** The current segment ends with `end_reason: transfer`, `outcome: transferred`. A new segment (call) starts on the chosen agent's published version with `routed_by: transfer`, segment number + 1. The caller hears the agent's `handoff_intro`, then its answer to the caller's last turn.
3. **No agent.** If the supervisor is unsure and clarification is still allowed, the front desk asks once; otherwise, or with no candidate, the current segment escalates to a human with category `transfer_failed` ([/architecture/escalation.md](/architecture/escalation.md)) and its hand-off message.
4. **Limit.** A conversation allows 3 transfers. A fourth request escalates with category `transfer_failed`.
5. Each transfer emits `conversation.transferred` (topics `conversation:{id}` and, for API conversations, the webhook, [/architecture/webhooks.md](/architecture/webhooks.md)).

# What carries over

| Item | Carried | Notes |
|---|---|---|
| Verification | yes | `verified`, `verified_member_ref`, `verification_level`, identification; the new segment's `caller_ref` is set. The receiving agent does not ask again ([/architecture/caller-verification.md](/architecture/caller-verification.md)). |
| Call context | yes | including IVR and API `context` entries |
| Handoff | yes | `reason` and `summary` appear in the receiving agent's prompt as `handoff`; the last 6 caller and agent lines are its history |
| Member memory | no | the receiving agent loads **its own** memory of the member when the segment starts verified ([/architecture/agent-memory.md](/architecture/agent-memory.md)); memory stays per agent |
| Tools, knowledge, skills, policy, model | no | the receiving agent's published version |
| Voice and pipeline | conversation's | one voice and pipeline per conversation; realtime calls get a `session.update` with the new instructions and tools ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)); cascade calls keep the TTS voice |
| Turn and time limits | per segment for turns; per conversation for `max_call_seconds` (the first segment's value) | |

Each segment keeps its own events, escalation, feedback, analysis, scorecard and memory extraction, exactly like a call today. Caller feedback given at the end of a conversation is stored on the last segment.

# Misroutes

* **Scorecard checks** on routed segments ([/architecture/call-scoring.md](/architecture/call-scoring.md)): `routing.early_transfer` (code) fails when a segment ended by transfer within 2 caller turns of starting; `routing.in_scope` (judge) asks whether the caller's request fit this agent's description and use cases. Both are `n/a` on direct calls.
* **Routing summary** on the Evaluation page's Routing view: decisions by method, Stage B and fallback rates, clarification rate, misroute rate (early transfers and calibrated `routing.in_scope` failures), transfers per conversation, decision latency.
* **Learning** ([/architecture/self-learning.md](/architecture/self-learning.md)): misrouted segments are signals for a `routing_update` proposal that adds the misrouted utterances (as examples) to the use case of the agent that finally resolved the conversation, or sharpens its summary; it is gated on the routing suite plus the misrouted utterances and approved by a human.

# Acceptance

- **XFR-01** — Given a verified conversation on Claims & Pre-authorisation and a caller asking what their policy's dental and optical add-on covers, when the agent calls `transfer_to_agent`, then the claims segment ends with `end_reason: transfer` and `outcome: transferred`, a second segment starts on the coverage agent (Customer Care) with `routed_by: transfer`, the caller is not asked to verify again, and the next agent line is its intro followed by an answer about dental coverage.
- **XFR-02** — Given a transfer, then the receiving agent's system prompt contains the `reason` and `summary`, its history contains the last 6 lines, its member memory is its own (never the transferring agent's), and the call context is carried.
- **XFR-03** — Given a direct Studio call or a phone call to an agent number, then the tool list offered to the model does not contain `transfer_to_agent`.
- **XFR-04** — Given a conversation that has transferred 3 times, when an agent requests a fourth transfer, then the segment escalates with category `transfer_failed` and the hand-off message; given a transfer where no candidate remains, the same happens.
- **XFR-05** — Given a transfer request, then the requesting agent is not a candidate for that decision.
- **XFR-06** — Given a realtime voice conversation, when a transfer happens, then one `session.update` with the receiving agent's instructions and tools is sent, the voice stays the same and the socket stays open; given a cascade voice conversation, the TTS voice stays the same.
- **XFR-07** — Given a segment that ended by transfer after one caller turn, then its scorecard has `routing.early_transfer: fail`; given a direct call, both routing checks are `n/a`.
- **XFR-08** — Given a transferred conversation, then each segment has its own scorecard and analysis, the dashboard counts the conversation once with the last segment's outcome, and `GET /api/calls` lists each segment with its conversation id.
