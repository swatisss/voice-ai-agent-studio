---
type: Change Proposal
title: CP-0026 Agent-to-agent transfer
description: A built-in transfer_to_agent tool lets an agent hand a conversation to another agent chosen by the supervisor - new segment, verification and context carried over, own memory, same voice, at most 3 transfers - with misroute checks, a routing summary and nightly routing proposals.
status: stable
cp_state: implemented
tags: [routing, runtime, voice, evaluation, learning]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

Callers change topic. Today an agent can only answer or escalate to a human. The product owner chose a `transfer_to_agent` tool (Q8, Q27). Fourth CP of [ADR-0012](/decisions/adr-0012-public-api-and-supervisor-routing.md).

# What changes

* Built-in `transfer_to_agent(reason, summary)`, offered only inside conversations that have another routable agent.
* The supervisor (excluding the requester) picks the next agent; the current segment ends `transfer` / `transferred`; a new segment starts. Verification, member reference, call context, the reason, the summary and the last 6 lines carry over; memory is the receiving agent's own; the voice and pipeline stay.
* At most 3 transfers; no candidate or the limit → escalate with a new category `transfer_failed`.
* Realtime calls swap instructions and tools with one `session.update`.
* **Misroutes**: checks `routing.early_transfer` (code) and `routing.in_scope` (judge) on routed segments; a routing summary on the Evaluation page; a nightly `routing_update` proposal kind gated on the routing suite.
* Dashboards count a conversation once (its last segment's outcome); the Calls explorer links segments.

# Affected specs

* New: [/architecture/agent-transfer.md](/architecture/agent-transfer.md) (XFR-01…XFR-08).
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - built-in tool, turn ends after it (RT-16).
* [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) - reserved name (TS-10).
* [/architecture/escalation.md](/architecture/escalation.md) - category `transfer_failed` (ES-10).
* [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md) - end reason `transfer`, outcome `transferred`.
* [/architecture/call-scoring.md](/architecture/call-scoring.md) - group `routing`, two checks (SC-13).
* [/architecture/self-learning.md](/architecture/self-learning.md) - misroute signals, `routing_update` (SL-13).
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md), [/architecture/agent-memory.md](/architecture/agent-memory.md), [/architecture/caller-verification.md](/architecture/caller-verification.md) - transfer notes.
* [/data/data-model.md](/data/data-model.md) - enums (`end_reason` `transfer`, `outcome` `transferred`, `fix_proposals.kind` `routing_update`).
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - variables `transfer_instructions` and `handoff` (text below, applied with the implementation).
* [/ui/calls.md](/ui/calls.md) (UI-61), [/ui/dashboard.md](/ui/dashboard.md), [/ui/evaluation.md](/ui/evaluation.md) (routing summary).
* [/product/glossary.md](/product/glossary.md), [/process/conventions.md](/process/conventions.md) (prefix `XFR`).

# Acceptance criteria

New: XFR-01…XFR-08, RT-16, TS-10, ES-10, SC-13, SL-13, UI-61.

# Prompt change: agent system prompt

Two variables are added. `transfer_instructions` is empty unless the tool is offered; then it is:

```text
# Other teams
Other assistants handle other kinds of requests. If the caller needs something that is outside your skills, tools and knowledge, and it is not something your policy says a human must handle, call transfer_to_agent with a short reason and a summary of what the caller wants (no member numbers or dates of birth). Do not guess which team; do not tell the caller you are an AI handing over to another AI; just say you will connect them.
```

`handoff` is empty unless the segment started from a routing or transfer; then it is:

```text
# How this caller reached you
{{handoff_reason_line}}
Summary from the previous assistant: {{handoff_summary}}
Do not greet the caller again and do not ask again for anything already verified. Answer their last request.
```

Both are inserted after `{{mode_instructions}}`. Before: an off-topic request ended in `escalate_to_human` with `capability_gap`. After: the agent calls `transfer_to_agent` and the caller keeps talking to the right agent.

# Tasks

1. Spec edits (this CP).
2. Runtime: the built-in tool (offered conditionally), `CallState.transfer_requested`, a `Decision` path in `_turn` and `tools_finished`, the supervisor call with exclusion, segment switch in `AgentSession` (settings, tool executor rebuilt with the same state, memory reload) — RT-16, XFR-01, XFR-02, XFR-05.
3. Voice: segment switch on the running pipeline; realtime `session.update`, cascade keeps the voice — XFR-06.
4. Limit and failure escalation; category `transfer_failed` — XFR-04, ES-10; reserved name — TS-10; tool absent on direct calls — XFR-03.
5. Scoring checks, routing summary endpoint, dashboard counting by conversation — SC-13, XFR-07, XFR-08.
6. Self-learning: misroute signals and `routing_update` proposals gated on the routing suite — SL-13.
7. Prompt text above applied to [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md).
8. Web: Calls segments and transfer notices, Evaluation routing summary — UI-61.
9. Tests citing the IDs.

# Risks and rollout

* Agents may over-use the tool instead of answering; `routing.early_transfer` and `routing.in_scope` measure it, and the limit caps loops.
* Per-segment turn limits restart on each transfer; the conversation's call length does not.
* The dashboard changes its unit from calls to conversations for routed traffic; seeded history has no conversations, so its numbers do not move.

# Out of scope

Transfers to a different tenant; warm transfer with both agents present; letting an agent name its target.
