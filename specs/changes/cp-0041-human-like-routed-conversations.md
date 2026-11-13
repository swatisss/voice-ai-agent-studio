---
type: Change Proposal
title: CP-0041 Human-like routed conversations
description: The caller's request survives routing and verification, a clarified call goes to the agent that was leading, the caller sees their words as they speak, the filler is only said while waiting, and the front desk becomes Eva, warm and upbeat.
status: stable
cp_state: implemented
tags: [routing, runtime, prompt, voice, ui, demo-data]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-13T00:00:00Z" }
---

# Why

The owner made a full-flow voice test call on 2026-11-13 (conversation `05add28a35b047ab888dd9c66d729adb`, cascade pipeline, Northgate Health, synthetic member Emma Clarke). It went like this:

| # | Speaker | Line |
|---|---|---|
| 1 | Front desk (Olivia) | Thanks for calling Northgate Health, this is Olivia. … How can I help you today? |
| 2 | Caller | I'm waiting to hear if my shoulder operation has been approved. |
| 3 | Front desk | Hi! Are you asking about getting your shoulder surgery approved, checking the status of a pre-authorisation, or something else? |
| 4 | Caller | Yes. |
| 5 | Customer Care | You're now with our member services team. Could you please provide your membership number and date of birth to verify your identity? |
| 6 | Caller | (member ID and date of birth) |
| 7 | Customer Care | One moment while I check that. Thank you, Emma. How can I assist you with your Northgate Complete plan today? |

The caller had to start again. Four causes, all visible in the stored record:

1. **Routing after the clarification fell to the default agent.** Stage A put Claims & Pre-authorisation first both times: 0.815 before the question (lead 0.096, just under `clear_margin` 0.10, so unsure) and 0.796 after "Yes." (under `clear_win` 0.80, so unsure again). With one clarification used, the rule sends an unsure answer to the default agent, so the call went to Customer Care, which has no pre-authorisation tools (CLM-04). The agent that led throughout was never chosen.
2. **The request was not handed over.** The front desk starts the first segment with `handoff: {reason: "", summary: ""}` and gives the agent only the current caller line ("Yes.") as the turn to answer. The original question is somewhere in the history, but nothing in the prompt points at it.
3. **Verification resets the conversation.** The prompt says to verify and has a "how can I help" habit, but nothing says to go back to the request afterwards. So line 7 asks the caller to repeat themselves, the opposite of what a person on a phone line would do.
4. **The filler is glued to a fast answer.** "One moment while I check that." is said before every first tool round, even when the lookup returns in a few hundred milliseconds, and the transcript shows it stuck to the answer.

Two more observations from the same call:

* **The caller's words appear late.** Deepgram sends interim transcripts, but the turn aggregator drops them (`InterimTranscriptionFrame` is consumed and ignored), and the `user` event is stored only once the turn is complete. The tester talks for several seconds with nothing on screen.
* **The front desk sounds flat.** Olivia is "warm, calm and concise". For the voice that opens every routed call, the owner wants someone warmer, more upbeat and happier: **Eva**.

# What changes

1. **Clarified routing keeps the leader.** After a clarifying question, if the answer still gives no clear win but Stage A's leader is the same agent that led before the question, the conversation goes to that agent (`method: clarified`, `decided_by: leader`). A plainly negative answer ("no", "neither", "something else") still goes to the default agent. "Yes." to a question built around the leading agent now reaches that agent.
2. **The routed segment knows what the caller asked.** The front desk fills the first segment's handoff: `reason` "Routed by the front desk" and `summary` set to the caller's front-desk lines in order (≤ 500 chars), e.g. `I'm waiting to hear if my shoulder operation has been approved. / Yes.` The agent's first answer is to that request, not just to the last line.
3. **One handoff block for routed and transferred segments**, with explicit rules: never ask the caller to repeat themselves; if verification is needed, say why in one sentence, and once verified go straight back to the request; transfer if it is not yours. A new ground rule applies to every agent, routed or not: after verification, carry on with what the caller already asked, and ask "how can I help" only if they have not said yet.
4. **The filler only fills a wait.** On the cascade, "One moment while I check that." is spoken only if the first tool round is still running after 700 ms. When it is spoken, it is stored as its own `assistant` event, so the transcript reads as two separate lines.
5. **Live caller text.** On both voice pipelines, the caller's words show in the Test call transcript as they speak, as a provisional bubble that updates live and is replaced by the final caller message. Interim text is published on the call's SSE topic as `call.partial` and is never stored, so learning, scoring and the Calls page don't change.
   * **Cascade:** Deepgram interims.
   * **Realtime:** `conversation.item.input_audio_transcription.delta`. If the transcription model sends no deltas, the bubble shows "…" from the moment speech starts.
6. **Eva replaces Olivia** as the persona of the front desk and of Customer Care: "Hi, thanks for calling Northgate Health, this is Eva." The style is warm, upbeat and happy, still British English, short sentences, one question at a time, plain language. The voice stays a British female Aura-2 voice at speed 1.05. The data is synthetic.

# Affected specs

* [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md): step 4 keeps the leader after a clarification; the front desk fills the routed segment's handoff; RTE-07 answers the whole request; RTE-18..RTE-20.
* [/architecture/agent-transfer.md](/architecture/agent-transfer.md): the handoff row covers routed segments too, using one prompt block; XFR-09.
* [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md): the handoff block text is written out here; new ground rule "after verification, go back to the request".
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md): filler after 700 ms, stored as its own event; RT-18.
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md): interims published as `call.partial`; VO-09.
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md): transcription deltas and speech start published as `call.partial`; RV-17.
* [/api/events.md](/api/events.md) and [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md): the new transient `call.partial` event.
* [/ui/test-call.md](/ui/test-call.md): the provisional caller bubble, in single-agent and Full flow; UI-75.
* [/demo-data/northgate-health.md](/demo-data/northgate-health.md): Eva replaces Olivia; UC-10 reworded; UC-12.

# Acceptance criteria

New, written out in the specs:
* RTE-18, RTE-19, RTE-20 in [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md): after "Yes." the leading agent (Claims & Pre-authorisation) is chosen, not the default agent; a plain "no" still goes to the default agent; the routed segment's handoff carries the caller's front-desk lines and the agent answers the whole request.
* XFR-09 in [/architecture/agent-transfer.md](/architecture/agent-transfer.md): routed and transferred segments get the Handoff block word for word, and direct calls get the "after verification" ground rule.
* RT-18 in [/architecture/agent-runtime.md](/architecture/agent-runtime.md): no filler when the tool round returns within 700 ms; otherwise the filler is stored as its own line.
* VO-09 in [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) and RV-17 in [/architecture/realtime-voice.md](/architecture/realtime-voice.md): interim caller text is published as `call.partial` and never stored.
* UI-75 in [/ui/test-call.md](/ui/test-call.md): a provisional caller bubble in single-agent and Full flow.
* UC-12 in [/demo-data/northgate-health.md](/demo-data/northgate-health.md): Eva, and an existing Olivia is renamed in place.

Changed: UC-10 (the front desk uses Eva); RTE-07 (the agent answers the routed request, all of the front-desk lines).

# Tasks

1. Spec edits (this CP).
2. Routing: in `front_desk_turn` (`conversations.py`) and `supervisor`, keep the leader after a clarification and treat a plain negative as a no; record `decided_by: leader`. Covers RTE-18, RTE-19.
3. Handoff: the front desk fills `meta.handoff` with the caller's front-desk lines; `ConversationSession` (`routing/voice_session.py`) and the text path give the agent the joined request as its first turn; `runtime/prompt.py` `handoff_block` renders the spec block; new ground rule in the system prompt. Covers RTE-20, XFR-09.
4. Filler: `runtime/session.py` waits 700 ms before yielding `FILLER` and stores it as its own event; keep `respond()` and the turn-policy path producing the same events (RT-15). Covers RT-18.
5. Live caller text: `voice/processors.py` publishes throttled interims; `voice/realtime.py` handles `input_audio_transcription.delta` and `speech_started`; bus event `call.partial` (not stored). Covers VO-09, RV-17.
6. Web: `app/test-call/page.tsx` and `components/full-flow.tsx` render the provisional bubble from `call.partial`. Covers UI-75.
7. Seed: Eva replaces Olivia in the Northgate seed and the front desk; the seeder renames an existing Olivia persona of `northgate-health` in place (same id), so existing databases update without `--reset`. Covers UC-10, UC-12.
8. Tests with the fake LLM and typed (text) conversations: the shoulder-operation case end to end (clarify, "Yes.", leader routed, handoff summary in the prompt, the first model turn carries the request), and a verify-then-continue case on Customer Care. Hand check: live transcript on a voice call. A live typed run with real (paid) LLM calls only with the owner's go-ahead.

# Risks and rollout

* **Keeping the leader can pick wrong** when the clarifying answer is vague and the leader was wrong. The receiving agent can still transfer (CP-0026), and an early transfer is scored as a misroute, which feeds the nightly routing proposals. That is better than the default agent, which here could not help at all.
* **Changing the filler moves events.** RT-15 requires `respond()` and the turn-policy path to store the same sequence, so both must apply the 700 ms rule identically. Fake-LLM tests use an instant tool, so they get no filler, plus one slow-tool case.
* **`call.partial` adds SSE traffic.** It is throttled to 150 ms and only sent to subscribers of `call:{id}`. It is not part of the public webhook set.
* **The persona rename touches demo scripts.** The demo walkthrough and the demo script mention Olivia; they are updated in task 7.

# Out of scope

* Choosing a different Deepgram or realtime voice for Eva. The voice stays pandora until the owner picks another one in the persona editor.
* Rewriting the clarify prompt ([/prompts/router-clarify.md](/prompts/router-clarify.md)). Its questions can still offer two options from the same agent; the leader rule makes that harmless.
* Changing the realtime filler: it stays model-driven via the addendum.
* Separate verification for the Oakhaven Dental kit after a transfer. It is a different business with its own patient IDs, so asking again is correct.
