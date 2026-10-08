---
type: Change Proposal
title: CP-0011 Calls close properly and callers rate them
description: Voice and chat calls end by themselves after a goodbye, a farewell phrase, a hand-off to a human, silence or the maximum length, and when a call has ended the caller gives a thumbs up or down that feeds Insights and self-improvement.
status: stable
cp_state: implemented
tags: [runtime, voice, ui, learning, feedback]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-07T00:00:00Z" }
---

# Why

Product-owner feedback from a real test: after the issue was resolved ("thank you") or the call was escalated to a human, **the voice call kept listening**. Reading the code and specs:

* A resolved call ends only if the model chooses to call `end_call`. The prompt says to do so once the caller "confirms they need nothing else"; a plain "thank you" does not, so the agent answers "You're welcome, anything else?" and waits.
* An **escalated** call is kept open on purpose ("holding mode until the caller hangs up", [escalation](/architecture/escalation.md) step 6), and `end_call` is explicitly ignored once escalated. In voice that means a live, listening microphone after "a specialist will be with you".
* There is no silence timeout and no maximum length for voice; the socket only dies at the 3,600 s server limit.
* Chat has no end-of-conversation signal for the caller either, and nothing records whether the caller was happy. A call can be "resolved" and still have left the caller dissatisfied; today Insights can never see that.

What the industry does (researched for this CP): Retell and Vapi give the agent an **end-call tool** and always speak the farewell first; Vapi also has **fixed end phrases**, a **silence timeout** (default 30 s) and a **maximum duration** (default 600 s); Retell sends one reminder after about 10 s of silence and then ends; Dialogflow CX and Amazon Connect **end the bot's session when the call is handed to a human agent**, so the AI leg leaves; survey guidance is to ask for feedback only after the caller's issue is dealt with, as a short thumbs or yes/no question in chat and an in-call or follow-up question in voice. Sources are in [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md).

# What changes

1. **Hand-off ends the AI call.** After the handoff (or safety) message is delivered, the session ends with reason `handoff`; outcome `escalated`; the escalation stays `waiting` for the human console, which is unaffected. In voice the message is spoken in full first. (Replaces the "holding mode".)
2. **Farewell phrases end the call without the model.** A short caller turn such as "no, that's all", "bye" or "that's it" gets the closing line "Thank you for calling. Take care!" and ends the call (`farewell`). A bare "thank you" does not.
3. **The prompt asks once "anything else?"** and tells the agent to say goodbye and call `end_call` when the caller thanks it, needs nothing more, or says goodbye. Before/after example below.
4. **Voice silence and length limits**, as agent policy with industry-style defaults: one reminder "Are you still there?" after 10 s of silence, end after 30 s of silence (`idle`), end after 600 s in total (`max_duration`), each with a spoken closing line. Timers are paused while the welcome plays and reset whenever the caller speaks.
5. **The page follows the server.** When the server ends a voice call, the browser gets `end` with the reason, stops the microphone and shows the end-of-call banner; in chat the last reply carries `ended: true` and the input is replaced by the banner.
6. **Feedback after the call.** The end-of-call banner on Test call gains **"Was this helpful?" Yes / No**; **No** opens an optional comment (300 characters). New `POST /api/calls/{id}/feedback`, a new table `call_feedback` (a new table, so existing local databases need no migration), `feedback` on call summaries and detail, `GET /api/calls?feedback=`. Shown for voice and chat, never for simulation calls, never while a call is running.
7. **Feedback feeds learning.** A thumbs down on a call makes it a candidate for Insights even when it was resolved: the call is re-analysed once with the feedback ([call analysis prompt](/prompts/call-analysis.md) gains a `caller_feedback` input and must then give a root cause and a generic gap summary), clustered like an escalation, counted toward "ready for a fix", and listed in the cluster evidence with the comment. Calls explorer shows a 👍/👎 badge and a feedback filter; the cluster list shows how many thumbs-down calls each cluster holds. Thumbs up is stored and displayed only.

**Before / after (prompt, resolved call).**

Before — Caller: "That's what I needed, thank you." Agent: "You're welcome! Let me know if you need anything else." (call stays open)
After — Caller: "That's what I needed, thank you." Agent: "Glad I could help. Is there anything else I can help with today?" Caller: "No, that's all." → farewell phrase rule: "Thank you for calling. Take care!" and the call ends. If the model answers "Thanks, bye" with its own goodbye and `end_call`, the result is the same.

# Affected specs

* [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md) - **new**: end reasons, rules, feedback, configuration; CE-01…CE-07, FB-01…FB-05.
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - turn algorithm (farewell rule, hand-off ends), `end(reason)` values, `end_call` and escalation tool text.
* [/architecture/escalation.md](/architecture/escalation.md) - procedure step 6: the call ends instead of holding.
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) - silence and maximum-duration timers, closing speech, `end` message for every reason.
* [/api/voice-protocol.md](/api/voice-protocol.md) - `end` reasons.
* [/api/rest-api.md](/api/rest-api.md) - feedback endpoint, `feedback` fields, `feedback` filter, cluster `dislike_count` and `signal_count`.
* [/data/data-model.md](/data/data-model.md) - table `call_feedback` (20 tables), `end_reason` values.
* [/data/agent-config.md](/data/agent-config.md) - `policy.silence_reminder_s`, `silence_end_s`, `max_call_seconds` and their bounds (CE-07).
* [/architecture/fleet-learning.md](/architecture/fleet-learning.md) - clustering membership and readiness count thumbs-down calls; re-analysis on thumbs down.
* [/prompts/call-analysis.md](/prompts/call-analysis.md) and [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) - the two prompt changes.
* [/ui/test-call.md](/ui/test-call.md), [/ui/calls.md](/ui/calls.md), [/ui/insights.md](/ui/insights.md) - end-of-call banner and feedback prompt, feedback badge and filter, cluster evidence and counts; UI-10 changed, UI-34…UI-37 new.
* [/process/conventions.md](/process/conventions.md) - new acceptance prefixes `CE` and `FB`.

# Acceptance criteria

New: **CE-01…CE-07**, **FB-01…FB-05** (automated), **UI-34…UI-37** (by hand in the browser). Changed: **UI-10** (escalation now ends the call), **RT-02** (the holding reply remains only for a session that is escalated yet open), **DM-01** (20 tables). **CE-03** is a prompt rule checked by hand with a real model.

# Tasks

1. Spec edits (done in this CP).
2. Runtime, `apps/api/voiceai/runtime/session.py` and `voiceai/runtime/escalation.py` - farewell rule before the LLM, end after hand-off (all channels), new end reasons, `end_call` no longer ignored after escalation - covers CE-01, CE-02, CE-06 (reasons).
3. Voice, `apps/api/voiceai/voice/processors.py` and `pipeline.py` - silence and maximum-duration timers in `BrainProcessor` (paused during the welcome, reset on caller speech and on agent speech), closing lines, `end` message with the reason - covers CE-04, CE-05, CE-06.
4. Config and prompts - `policy` fields with bounds ([schemas](/data/agent-config.md)), the two prompt files loaded verbatim - covers CE-03, CE-07.
5. Feedback - model `CallFeedback`, `POST /api/calls/{id}/feedback`, `feedback` in call summary/detail/filter, re-analysis on thumbs down, `caller_feedback` in the analysis input, clustering and readiness counting, cluster `dislike_count` and `signal_count` - covers FB-01…FB-05.
6. Tests in `apps/api/tests/` citing CE- and FB- IDs, and DM-01 with 20 tables (frame-driven timer tests with tiny durations; no network; fake LLM).
7. Web - Test call (banner, feedback prompt, voice end handling, chat input closed), Calls (badge, filter, detail), Insights (evidence column, counts) - covers UI-10, UI-34…UI-37.
8. Verify in the browser (chat and voice with a headset); add UI-34…UI-37 to `scripts/acceptance-baseline.txt`; `npm run build`, `uv run pytest`, `python scripts/spec_check.py --ci --base origin/main`.
9. Close: specs to `status: stable`, CP to `implemented`, `specs/log.md` entry.

# Risks and rollout

* **The hand-off message says "connecting you…" and then the call closes.** In this product the human works from the console and there is no live bridge to the caller, so closing is accurate for a callback but the default `handoff_message` wording ("I'm connecting you with a specialist…") may now sound like a transfer that never comes. Wording is configurable per agent; changing the seeded text is left to a follow-up.
* **Farewell phrases can misfire** ("that's it? no, I meant…" is excluded by the question mark and length rule; "bye" inside a longer sentence is not a farewell). The list is a constant and short; it is the safety net, not the primary mechanism.
* **Simulation calls end at hand-off too**, because runtime behavior must not differ by channel. Evaluation code that waited for an escalated-but-open call must be checked (RT-07 and the evaluation tests).
* **Idle timers and echo.** With open speakers the agent's own voice can look like the caller speaking and keep resetting the silence clock; the welcome is already protected (VO-08), later echo is not addressed here (a headset avoids it).
* **Existing databases**: only a new table is added, so `create_all` creates it; no column changes. Old calls simply have no feedback.
* **Cost**: one extra analysis run per thumbs-down call.

# Out of scope

* A spoken in-call survey ("press 1 / say yes") and SMS follow-ups for real telephony; the test page prompt is the only surface.
* Idle timeout for chat, and a "reopen the conversation" button.
* Showing thumbs-up counts on the dashboard, a satisfaction score, or putting feedback into the dashboard (the owner keeps the dashboard to four tiles, [CP-0009](/changes/cp-0009-simplified-ui-sidebar-and-branding.md)).
* Exposing the three new policy fields in the Agent builder form (they are settable through the API and the JSON draft); changing the seeded `handoff_message`; seeding demo thumbs-down calls.
* A live bridge or call transfer to the human.
