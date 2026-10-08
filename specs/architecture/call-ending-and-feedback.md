---
type: Component Spec
title: Call ending and caller feedback
description: Every way a call ends in voice and chat (goodbye, farewell phrase, hand-off to a human, silence, maximum duration, hang-up), and the thumbs up or down feedback a caller leaves afterwards, which feeds Insights.
status: stable
tags: [architecture, lifecycle, feedback, learning]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-07T00:00:00Z" }
---

# Why calls must end by themselves

A voice call that never closes keeps the microphone open, bills minutes, and tells the caller nothing. The practice across voice-agent platforms is to combine several independent triggers so one failing never leaves a call hanging:

| Trigger | Practice elsewhere | Here |
|---|---|---|
| Agent ends the call after a goodbye | Retell and Vapi give the agent an *end call* tool; the farewell is always spoken before hanging up | `end_call` tool (RT-05), now guided by the prompt to use it on "thank you / that's all / bye" |
| Farewell phrases | Vapi `endCallPhrases` end the call on fixed phrases, no model decision needed | **Farewell phrase** rule below (CE-02) |
| Hand-off to a human | The AI leg leaves: Dialogflow CX `END_FLOW_WITH_HUMAN_ESCALATION` ends the virtual-agent session, Amazon Connect `TransferContactToAgent` ends the bot flow | **Hand-off ends the AI call** (CE-01) |
| Silence | Vapi `silenceTimeoutSeconds` (default 30 s); Retell reminds once after 10 s of silence, then ends | **Silence reminder and end** (CE-04) |
| Maximum length | Vapi `maxDurationSeconds` (default 600 s); Retell max call duration | **Maximum duration** (CE-05) |
| Caller hangs up | always | unchanged |

Survey practice: ask for feedback only after the issue is dealt with, never before; voice CSAT is either an in-call question or a message afterwards, chat uses a thumbs widget. Here the prompt is shown after the call has ended.

References: https://docs.vapi.ai/documentation/assistants/conversation-behavior/call-timeout-settings · https://docs.retellai.com/build/single-multi-prompt/end-call · https://docs.cloud.google.com/agent-assist/docs/handoff-cx · https://docs.aws.amazon.com/connect/latest/devguide/contact-actions-transfercontacttoagent.html · https://www.verint.com/blog/top-10-best-practices-for-optimising-post-call-interaction-surveys-using-ivr

# End reasons

`calls.end_reason` and the `end` message of the voice protocol use these values:

| Reason | Meaning |
|---|---|
| `end_call` | the model called `end_call` after a goodbye |
| `farewell` | the caller said a farewell phrase (CE-02) |
| `handoff` | the call was escalated and the hand-off message has been delivered (CE-01) |
| `idle` | the caller stayed silent (voice, CE-04) |
| `max_duration` | the maximum call length was reached (voice, CE-05) |
| `hangup` | the caller or the page ended the call |
| `error` | an unrecoverable failure |

The earlier reason `timeout` is replaced by `idle` and `max_duration`. Whatever the reason, `AgentSession.end(reason)` runs once ([/architecture/agent-runtime.md](/architecture/agent-runtime.md), RT-08), sets `status: ended`, queues `analyze_call` and publishes `call.ended`.

# Rules

1. **Hand-off ends the AI call (CE-01).** When a call is escalated by any trigger ([/architecture/escalation.md](/architecture/escalation.md)), the handoff (or safety) message is delivered as before, and then the session ends with reason `handoff`. The call's `outcome` is `escalated`; the escalation row stays `waiting` for the human console, which is unaffected. In voice the message is spoken in full before the socket closes. The call no longer sits in a "holding" state; the holding message is only a fallback for a session that is escalated yet still open.
2. **Farewell phrase (CE-02).** Before the model runs, a caller turn is a *farewell* when, lower-cased and stripped of punctuation, it has at most 8 words, contains no question mark, contains one of: `goodbye`, `bye`, `bye bye`, `that's all`, `that is all`, `that's it`, `that is it`, `that's everything`, `nothing else`, `i'm all set`, `i am all set`, `have a good day`, `talk to you later` — and every other word is polite filler (`no`, `okay`, `thanks`, `thank`, `you`, `so`, `well`, `please`, `all`, `right`, `i`, `just`, `need`, `needed`, `that`, `was`, `now`, `for`, `your`, `the`, `help`, `today`, `a`, `very`, `much`, `great`, `good`, `take`, `care`, `have`, `day`, `and`, and the like). So "That's all wrong, can you check?" is not a farewell. A bare "thank you" is not a farewell. The runtime then says the closing line "Thank you for calling. Take care!", records it, and ends with reason `farewell`; no LLM request is made. A farewell does not end an escalated or already ended call.
3. **Model-driven end (CE-03).** After resolving a request the agent asks once whether there is anything else. When the caller thanks it, says they need nothing else, or says goodbye, it gives a short goodbye and calls `end_call` ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)). This is a prompt rule; the deterministic rules above are the safety net when the model does not.
4. **Silence (voice only, CE-04).** The silence clock starts when the agent stops speaking and stops whenever the caller starts speaking. After `policy.silence_reminder_s` (default 10 s) of silence the agent says once "Are you still there?". Both times are measured from the start of the silence, so after `policy.silence_end_s` (default 30 s) of total silence the agent says "I haven't heard anything, so I'll end the call now. Thank you for calling." and the call ends with reason `idle`. Neither timer runs while the welcome plays ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), VO-08) or while the agent is speaking or thinking.
5. **Maximum duration (voice only, CE-05).** After `policy.max_call_seconds` (default 600) the agent says "We've reached the maximum call length, so I'll end the call now. Thank you for calling." and the call ends with reason `max_duration`.
6. **Text chat.** Rules 1–3 apply to chat too; the reply to the last message carries `ended: true` and the page closes the conversation. There is no automatic idle timeout in chat: the tester ends it.
7. **The page follows the server.** When the server ends a voice call, the browser stops the microphone and shows the end-of-call banner without the tester doing anything ([/api/voice-protocol.md](/api/voice-protocol.md)).

# Caller feedback

After a call has ended, the Test call page asks **"Was this helpful?"** with two labelled buttons, **Yes** (thumbs up) and **No** (thumbs down). **No** reveals an optional comment box ("What went wrong?", up to 300 characters). It is shown for every ended test call, whatever the reason it ended, voice or chat; never while the call is running.

* **Storage**: one row per call in `call_feedback` ([/data/data-model.md](/data/data-model.md)) — `rating` `up` or `down`, optional `comment`. Submitting again replaces the earlier answer.
* **API**: `POST /api/calls/{id}/feedback` ([/api/rest-api.md](/api/rest-api.md)); the call summary and detail carry the rating; `GET /api/calls?feedback=` filters.
* **Learning signal**: a thumbs **down** makes the call a candidate for fleet learning even when it was `resolved` ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)). The call is re-analysed once with the feedback; the analysis must then name what the caller was probably unhappy about; that call joins a cluster like an escalation would, counts toward "ready for a fix", and appears in the cluster's evidence with the comment. A thumbs **up** is stored and shown but does not create work.
* Feedback is never required to end the call, never shown for simulation calls, and never changes `outcome`.

# Configuration (agent `policy`, [/data/agent-config.md](/data/agent-config.md))

| Field | Default | Bounds |
|---|---|---|
| `silence_reminder_s` | 10 | 5–60 |
| `silence_end_s` | 30 | 10–300, and greater than `silence_reminder_s` |
| `max_call_seconds` | 600 | 60–3600 |

# Acceptance

- **CE-01** — Given an inbound call in voice or text, when the model escalates (or a safety, streak or max-turn trigger fires), then after the handoff message is delivered the call ends with reason `handoff`, its `outcome` is `escalated`, the escalation is still `waiting` and visible in the console, and a further caller turn is not processed.
- **CE-02** — Given a caller turn "No, that's all, thank you.", when it is handled, then no LLM request is made, the closing line is recorded and the call ends with reason `farewell`; given "Thank you." alone, or "That's all wrong, can you check again?", the call continues.
- **CE-03** — Given the system prompt, then it tells the agent to ask once whether there is anything else and to give a goodbye and call `end_call` when the caller thanks it, needs nothing else or says goodbye. (Prompt text; behavior is checked by hand with a real model.)
- **CE-04** — Given a voice call where the agent has finished speaking, when the caller stays silent for `silence_reminder_s`, then the agent says the reminder once; when total silence reaches `silence_end_s`, then it says the closing line and the call ends with reason `idle`; when the caller speaks at any point before that, then both timers reset; and while the welcome plays neither timer runs.
- **CE-05** — Given a voice call that reaches `policy.max_call_seconds`, then the agent says the closing line and the call ends with reason `max_duration`.
- **CE-06** — Given any end reason, when a voice call ends from the server side, then the browser receives `{"type":"end","reason":<reason>}` after the closing speech has finished (at most 10 s), and the socket closes.
- **CE-07** — Given `silence_reminder_s`, `silence_end_s` or `max_call_seconds` outside the bounds (or `silence_end_s` not greater than `silence_reminder_s`), when an agent draft is saved, then the API returns 422.
- **FB-01** — Given an ended call, when `POST /api/calls/{id}/feedback` is sent with `rating: "down"` and a comment, then it is stored, returned by `GET /api/calls/{id}` and shown as `feedback` in the call summary; sending again replaces it.
- **FB-02** — Given a running call, an unknown call, a simulation call, a rating other than `up`/`down`, or a comment over 300 characters, then the API returns 409 `call_active`, 404, 409 `not_ratable`, 422 and 422.
- **FB-03** — Given a resolved call, when a thumbs down arrives, then `analyze_call` is queued once more, its prompt input contains the rating and comment, and the stored analysis has a non-`none` root cause and a non-empty `gap_summary`; a thumbs up queues nothing.
- **FB-04** — Given a resolved call with a thumbs down and a non-empty `gap_summary`, when it is clustered, then it joins or creates a cluster like an escalated call, and counts toward the cluster's "ready for a fix" size; the dashboard's escalation root-cause chart still counts escalations only.
- **FB-05** — Given calls with different feedback, when `GET /api/calls?feedback=down` is called, then only thumbs-down calls are returned (`up`, `none` likewise).
