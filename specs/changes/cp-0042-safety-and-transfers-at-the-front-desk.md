---
type: Change Proposal
title: CP-0042 Safety and transfers at the front desk
description: The front desk screens emergency and self-harm language before routing, a transfer inside the first routed text turn reaches the caller, and a medical phrase said as history no longer trips the safety screen.
status: stable
cp_state: implemented
tags: [routing, runtime, safety, compliance]
generated: { by: "claude-code/claude-fable-5-1", at: "2026-11-13T23:30:00Z" }
---

# Why

A pre-demo QA pass on 2026-11-13 (51 utterances through the Full-flow front desk, twice; 26 adversarial typed calls; Jev decision model, gpt-4.1-mini agents) found three failures that end a call the wrong way:

1. **Emergency language at the front desk is not screened.** "I have chest pain and I can't breathe properly" as the first line of a Full-flow conversation got "Are you calling about an appointment, a claim status, or a new quote?" in both runs. The decision model answered `none` with 0.99 confidence; the embedding had no clear win; the front desk asked its clarifying question. The safety screen ([/architecture/escalation.md](/architecture/escalation.md), ES-01) runs only in an agent turn; `front_desk_turn` routes first. The public API ([/api/public-api.md](/api/public-api.md)) and front-desk phone numbers take the same path, so a real caller in an emergency would be asked to pick a topic.
2. **A transfer in the first routed text turn gives the caller silence.** Routed to Customer Care after a clarification ("I have a question." / "about adding my partner to my policy"), the agent called `transfer_to_agent` in its first answer. The Sales segment was created with no events and the turn's `messages` ended at Customer Care's intro. `routed_text_turn` returns the first segment's chunks and never looks at `session.transferred_to`; `message()` and the voice session (`_follow_transfer`) both do.
3. **Medical history trips the safety screen.** On Health Cover Sales, "Full medical underwriting please, I had a heart attack last year and I'm on blood thinners" matched `heart attack`, the 999 message was spoken and the call was escalated and ended. Underwriting asks for exactly this kind of history; a sales call that mentions a past stroke, heart attack or chest pain cannot finish.

# What changes

1. **The front desk screens every caller line before routing.** When a line matches a safety phrase, the supervisor is not asked. The conversation opens its first segment at once on the scope's default agent, or on the Stage A leader when there is no default, with `method: safety` and `reason: "Emergency or self-harm language"`. That agent's own safety rule then applies to the line: the fixed safety message in the caller's language, an escalation with category `safety`, the segment ends `handoff`. No model call is made for that line. The segment's handoff summary carries the caller's front-desk lines as for any routed segment. A clarifying answer that matches a safety phrase is screened the same way. With no routable agent in the scope, today's behaviour stands (`no_routable_agents` at creation; `kind: none` later).
2. **A transfer inside the first text turn is followed.** After the first segment's first answer, `routed_text_turn` (and `_open_text`, for a conversation opened with `agent_id` and a `message`) follows `session.transferred_to` exactly as `message()` does: the receiving agent's intro and its answer to the caller's last line are appended to the same turn's `messages`, the create response carries `transferred: true`, and the segments and notices are recorded as for any transfer.
3. **A medical phrase said as history does not trigger the screen.** `chest pain`, `heart attack` and `stroke` do not match when the same line carries a history marker: `last year`, `last month`, `years ago`, `months ago`, `weeks ago`, `history of`, `when I was`, `in 19xx` or `in 20xx`, `previously`, `in the past`. The self-harm phrases, `can't breathe`, `unconscious`, `severe bleeding` and `overdose` match as before, and a line with a present-tense cue (`right now`, `at the moment`, `having a`, `I'm having`) matches even with a marker. Hindi phrases are unchanged.

# Affected specs

* [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md): Decision step 0 (safety screen before candidates), `method: safety` in the routing record; RTE-21.
* [/architecture/escalation.md](/architecture/escalation.md): the safety screen's history markers and present-tense cues; trigger row wording; ES-11, ES-12.
* [/architecture/agent-transfer.md](/architecture/agent-transfer.md): flow step 2 covers the first routed text turn; XFR-10.
* [/api/public-api.md](/api/public-api.md): no change in shape; a safety line on `POST /v1/conversations` returns the first segment with the safety message (covered by RTE-21).

# Acceptance criteria

New, written out in the specs:
* RTE-21 in [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md): a safety phrase at the front desk is never routed; the default agent (or the Stage A leader) opens the segment with `method: safety` and speaks the safety message; an escalation with category `safety`; the Hindi message for a Devanagari line.
* XFR-10 in [/architecture/agent-transfer.md](/architecture/agent-transfer.md): a transfer in the first text turn (routed, or opened with `agent_id` and a `message`) carries the next agent's intro and answer in the same turn, `transferred: true`, both segments stored.
* ES-11 and ES-12 in [/architecture/escalation.md](/architecture/escalation.md): the history markers and present-tense cues for `chest pain`, `heart attack` and `stroke`; an underwriting answer with a past heart attack continues the call.

Unchanged: ES-01 (the agent-turn screen), RTE-05 and RTE-18..RTE-20 (clarification and the leader rule apply only to lines that pass the screen).

# Tasks

1. Spec edits (this CP): supervisor routing step 0 and RTE-21; escalation markers, ES-11, ES-12; agent transfer step 2 and XFR-10; log entry.
2. `conversations.front_desk_turn`: safety match before `supervisor.route`; a `safety` record; open the segment on the default agent or the Stage A leader; the agent session answers the line through its caller rule. Covers RTE-21.
3. `conversations.routed_text_turn`: follow `transferred_to` with `_answer`, as `message()` does. Covers XFR-10.
4. `runtime/escalation.safety_match`: history markers and present-tense cues for the three medical phrases. Covers ES-11, ES-12.
5. Tests on the fake LLM in `tests/test_front_desk_safety.py` (RTE-21, XFR-10) and `tests/test_escalation.py` additions (ES-11, ES-12).

# Risks and rollout

* **A false negative is worse than a false positive.** The history rule is narrow (three phrases, listed markers, present-tense cues override) and written in the spec so compliance can read it; self-harm phrases never relax. [/product/healthcare-compliance.md](/product/healthcare-compliance.md) rule 6 is unchanged in substance.
* **The safety segment opens on the default agent**, which may not be the agent the caller would have reached. The agent only speaks the fixed line and hands over; the groundwork packet carries the caller's words either way.
* **Demo impact**: Act 9's "say I have chest pain" works in Full flow as well as Single agent; Act 3 can mention a cardiac history without ending the call.

# Out of scope

* An out-of-scope line for the front desk ("we're a health insurer; I can help with…") and acknowledgement sentences before the hand-off line (roadmap).
* A third-party rule in the default policy (roadmap).
* A grounding check in code for amounts stated without a tool result (roadmap).
