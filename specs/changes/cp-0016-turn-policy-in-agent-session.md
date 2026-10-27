---
type: Change Proposal
title: CP-0016 Turn policy inside AgentSession
description: AgentSession takes conversation events in and returns decisions (say this exact line, let the model answer, tool result, end, escalate), so the cascade text loop and the realtime bridge stop re-implementing the turn rules and their ordering.
status: stable
cp_state: implemented
tags: [architecture, runtime, realtime]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Why

The architecture review of 2026-10-27 found the turn rules spread over the session and its callers:

* `runtime/session.py` `_turn` re-implements inline the same checks the session also exposes as `screen()` (escalated → holding line, farewell, safety) and `post_turn()` (no-answer streak, tool-error streak, max turns).
* `voice/realtime.py` `RealtimeBridge` must call seven session methods in a fixed order (`record_user` → `screen` → `apply` → `run_tool`… → `record_reply` → `post_turn` → `announce`), keep its own 4-round tool counter (`_tool_rounds`, `MAX_TOOL_ROUNDS`), refresh the provider instructions when `verified_member_ref` changes, and wait for the user event to be stored before the reply.
* "Say goodbye after `end_call` when the model said nothing" exists three times (`_turn`, `RealtimeBridge._after_tools`, `RealtimeBridge._after_reply`); the hand-off line default "I'm connecting you with a specialist." is written four times.

A rule change (a new trigger, a different closing line) has to be made in two pipelines, and RT-10 can only check parity by running the same scenario through both.

# What changes

* The session's interface for a turn becomes **events in, decisions out** ([/architecture/agent-runtime.md](/architecture/agent-runtime.md), Turn policy). Events: a final caller turn, a model reply finished (text, latency, usage, interrupted or not), a tool call requested. Decisions: say this exact line (optionally then end with a reason, optionally escalating), let the model answer, here is the tool result (and whether the model's instructions must be refreshed), end the call with a reason.
* The tool-round limit, the instruction refresh after verification, goodbye-after-`end_call`, the hand-off and closing line defaults all live in the session.
* The cascade turn loop (`respond`) and the realtime bridge become adapters: the cascade loop is the session driving its own text model; the bridge translates provider events into session events and decisions into provider commands.
* No observable call behaviour changes: RV-04…RV-09, RT-01…RT-09, CE-01, CE-02, ES-01…ES-03 hold as written.

# Affected specs

* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - Session API: `run_tool`/`record_turn` replaced by the turn-policy events and decisions; RT-10 retired; RT-11…RT-15
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md) - "What is reused" describes the bridge as an adapter over the turn policy

# Acceptance criteria

New: RT-11…RT-15. Retired: RT-10 (its parity claim becomes RT-15).

# Tasks

1. Spec edits (this CP).
2. Turn policy in `runtime/session.py`: the decisions for caller turn, reply finished and tool requested; `_turn` uses it — covers RT-11, RT-12, RT-13, RT-14.
3. `RealtimeBridge` reduced to an adapter over the policy; its tool counter, goodbye copies and hand-off default removed — covers RT-15, RV-05, RV-08, RV-09.
4. Tests: decision-table tests for the policy (no pipeline, no Pipecat); the realtime parity test rewritten against RT-15; `test_realtime_config.py` citation of RT-10 moved.

# Risks and rollout

* **Easier after the call-clock refactor** (a `[no-spec]` change in progress that moves welcome/silence/max-length timing out of both pipelines); do this CP second.
* The bridge's timing-sensitive parts (cancelling an in-flight response before a fixed line, waiting for the user transcript) stay in the bridge: they are about the provider, not the rules. Getting that split wrong could reorder events; RT-15 guards it.

# Out of scope

* Changing any rule, line text, trigger threshold or the 4-round limit.
* The call clock (welcome, silence, maximum length) and call admission (CP-0015).
* Evaluation and simulation drivers beyond keeping RT-07 green.
