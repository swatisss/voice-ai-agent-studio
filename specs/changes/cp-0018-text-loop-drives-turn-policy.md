---
type: Change Proposal
title: CP-0018 The text loop drives the turn policy
description: respond() becomes one more driver of the turn-policy events, so each turn rule and each stored event shape exists once; text calls store the same event data as realtime calls.
status: stable
cp_state: implemented
tags: [architecture, runtime]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-28T00:00:00Z" }
---

# Why

The architecture review of 2026-10-28 found that CP-0016 shared only part of the turn rules. `AgentSession._turn()`, the loop behind `respond()` for text, cascade voice and simulation calls, still does by hand what the turn-policy events already do:

* usage accumulation (`_turn` adds each round's tokens itself; *reply finished* does it in `_record_reply`);
* recording the assistant line with its latency (twice, with different `data`);
* the goodbye after `end_call` (`_turn` yields and records it itself; *reply finished* uses `_end_call_decision`);
* the hand-off after `escalate_to_human` (`_turn` records it itself; *tools finished* announces it);
* the tool-round count (a local `rounds` in `_turn`, `_tool_rounds` for the events) — on implementation this turned out not to be a duplicate; see *Clarifications*.

RT-15 exists only to check that the two copies still agree, and it compares event kinds and texts but not their `data`, which already differ. A fix to one rule has to be made twice, and the realtime and text transcripts of the same conversation are not identical.

# What changes

* `respond()` drives the same four events as the realtime bridge (*caller turn*, *tool call requested*, *reply finished*, *tools finished*) and carries out the decisions itself. The turn rules, their order and the shape of every stored event exist once, in the turn policy.
* What a caller hears does not change. What changes is the `data` of some stored events on text, cascade voice and simulated calls, which now match realtime calls:
  * the hand-off line after the model calls `escalate_to_human` is stored with `{"handoff": true}` (today `{}`);
  * the goodbye after `end_call`, when the model said nothing, is stored as an announced line (`data` without `latency_ms`, `tokens_in`, `tokens_out`), as on realtime calls;
  * text the model spoke before calling `escalate_to_human` is stored with token counts as well as latency.
* RT-15 is tightened: the event `data` must match too, apart from timestamps and measured latencies.

# Affected specs

* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - Turn algorithm: `respond()` is a driver of the turn policy; RT-15 compares event data.

# Acceptance criteria

* RT-15 (changed, in [/architecture/agent-runtime.md](/architecture/agent-runtime.md)): the parity check also compares each event's `data` (apart from timestamps and measured latencies), and covers a turn that ends with a model hand-off and one that ends with `end_call` and no spoken text.

# Tasks

1. Spec edits (done in this CP): agent-runtime.md Turn algorithm note and RT-15.
2. Backend: rewrite `AgentSession._turn()` as a driver of `caller_turn`, `tool_requested`, `reply_finished`, `tools_finished` and `commit`; remove the duplicated usage, recording, goodbye, hand-off and round-count code — covers RT-15.
3. Tests: extend the RT-15 parity test to compare `data` and to cover the hand-off and silent-`end_call` paths; adjust any test that asserts the old `data`.

# Risks and rollout

* Stored events of calls made before the change keep their old `data`; nothing reads the changed fields except the call detail view, which shows them as they are.
* Insights and analysis read event kinds and texts, not these `data` fields; to be confirmed while implementing.
* The cascade voice pipeline streams text from `respond()`; streaming must keep working with the loop restructured (covered by the existing voice tests).

# Clarifications (while implementing)

* **Tool rounds stay in the loop.** RT-04 limits the text loop to 4 *model rounds*, each of which may request several tools at once; RT-12 limits an externally driven turn to 4 *tool calls*. Merging the two would change RT-04, so `_turn` keeps its round count and runs tools through the same execution path (`_run_tool`: gate, events, state) without the per-call limit.
* **`end_call` lets the model finish its round.** A realtime service reports *tools finished* and the session closes there; the text loop asks its model once more after the tools, as before, and takes the decision at *reply finished*. What callers hear is unchanged.
* **Order of a silent `end_call` and a post-turn trigger in the same turn.** The turn algorithm runs the post-turn triggers (step 9) before ending (step 10), as the turn-policy table does. The old loop said the goodbye before the hand-off in that rare case; it now says only the hand-off, like realtime calls.
* **Latency of text spoken before a model hand-off** now counts toward the call's latencies, as on realtime calls (the call state must match, RT-15).

# Out of scope

* Changing what any caller hears, or the order of rules.
* Moving the timing rules (welcome, silence, maximum duration) into the turn policy; they live in the call floor shared by both voice pipelines.
