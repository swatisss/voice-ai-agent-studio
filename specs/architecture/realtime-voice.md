---
type: Component Spec
title: Realtime speech-to-speech voice
description: The optional per-agent voice pipeline that sends caller audio straight to the OpenAI Realtime model and plays its audio back - streaming, latency, how the shared runtime is still used, deterministic wording, evaluation trade-offs and cost.
status: stable
tags: [architecture, voice, realtime, openai]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-16T00:00:00Z" }
---

# Why an optional second pipeline

The default voice pipeline is a cascade: speech-to-text, then the text brain, then text-to-speech ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md)). Every hop waits for the previous one, and the caller hears nothing until the first sentence is ready. A speech-to-speech ("realtime") model takes audio in and produces audio out over one streaming connection, so there is no separate transcription or synthesis wait and the voice can carry tone. The cost is less control over exact wording and a higher price per minute. The platform therefore offers it **per agent**, off by default.

| | `cascade` (default) | `realtime` |
|---|---|---|
| Models | Deepgram STT, text LLM role `realtime`, Deepgram TTS | one OpenAI Realtime model (gateway role `speech`) |
| Keys needed | `DEEPGRAM_API_KEY` + an LLM key | an OpenAI key only: the tenant's own, or the platform `OPENAI_API_KEY` ([/architecture/tenant-settings.md](/architecture/tenant-settings.md)) |
| Who decides the words | the text brain, sentence by sentence | the speech model, within our prompt |
| Turn end | our TurnAggregator (normal or semantic) | the service's server-side turn detection, configured from the same settings |
| Voice | persona voice (Deepgram Aura) | `voice.realtime.voice` (an OpenAI voice) |
| Typical latency | higher (hops add up) | lower; target below |
| Evaluation by simulation | faithful (same text brain) | approximate (text brain stands in), see below |

Choice and rationale: [/decisions/adr-0008-telephony-and-realtime-voice.md](/decisions/adr-0008-telephony-and-realtime-voice.md).

# Selecting the pipeline

`voice.pipeline` in the agent config ([/data/agent-config.md](/data/agent-config.md)): `cascade` (default, also when the field is absent) or `realtime`. `realtime` is available only to tenants whose settings allow it; save, publish and call start enforce this ([/architecture/tenant-settings.md](/architecture/tenant-settings.md)). It is part of the published version snapshot, so a call uses the pipeline of the version it runs. The voice WebSocket for browser calls ([/api/voice-protocol.md](/api/voice-protocol.md)) and the Twilio stream ([/architecture/telephony.md](/architecture/telephony.md)) pick the pipeline from the call's version; the wire formats do not change, which is why a realtime agent can be tried from the Test call page before any phone is involved.

# Topology

```
browser (PCM16 16 kHz)  ─┐                                   ┌─▶ browser (PCM16 24 kHz)
                          ├─▶ Pipecat transport + serializer ─┤
Twilio (mu-law 8 kHz)   ─┘            │             ▲         └─▶ Twilio (mu-law 8 kHz)
                                      ▼             │ audio deltas, streamed as they arrive
                         OpenAI Realtime service (WebSocket to the provider)
                              │ transcripts         │ function calls
                              ▼                     ▼
                       RealtimeBridge  ──────▶  AgentSession  (prompt, tools, gates, state, events, escalation)
```

The transport, serializers, welcome protection and ending logic are shared with the cascade ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md)); the cascade's STT, TurnAggregator, BrainProcessor and TTS are not used. Pipecat and the provider's socket stay inside `voiceai/voice/` ([/decisions/adr-0002-voice-pipeline.md](/decisions/adr-0002-voice-pipeline.md)). Our code between the service and the runtime is the **RealtimeBridge**.

# What is reused from the shared runtime

The realtime model replaces how audio becomes words and back. It does not replace the brain. The bridge drives the same `AgentSession` ([/architecture/agent-runtime.md](/architecture/agent-runtime.md)) through two methods, so the behavior rules are written once:

| Piece | In realtime mode |
|---|---|
| **System prompt** | The session instructions are the assembled system prompt of [/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md) (persona, mode instructions, policy, skills, call context) **plus** [/prompts/realtime-addendum.md](/prompts/realtime-addendum.md). Prompts are loaded verbatim from `specs/prompts/`; nothing is copied into code. |
| **Tools** | Built-in tools and the agent's HTTP tools are given to the service as functions (same JSON schemas). A function call runs through `AgentSession.run_tool`, which applies the verification gate, executes the tool, records `tool_call`/`tool_result` events, updates call state and triggers escalation or ending exactly as in a text turn ([/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)). At most **4** tool rounds per caller turn; a fifth call gets `{"error":"tool_round_limit"}`. |
| **Knowledge** | `search_knowledge` is one of the tools; the agent's own documents only ([/architecture/knowledge.md](/architecture/knowledge.md)). |
| **Transcripts and events** | The service's final user transcript becomes a `user` event and increments `turns`; each completed reply becomes an `assistant` event with `latency_ms` and usage. Fleet learning, the Calls page, escalation packets and feedback read these events and need no change. |
| **Escalation** | `escalate_to_human` and the deterministic triggers ([/architecture/escalation.md](/architecture/escalation.md)) work unchanged. |
| **Policy timers** | Silence reminder, silence end and maximum duration ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md)) run in the bridge with the same defaults and wording. |

## Deterministic wording

With a text brain the platform speaks fixed lines itself (welcome, farewell, safety message, hand-off message, silence prompts, closing lines). A speech model would paraphrase them. The bridge therefore speaks these as **exact text**: it cancels any in-flight model response, then asks the service to say precisely the given text and nothing else (the model's `response.create` with an instruction to read the text verbatim). Consequences:

* The welcome (greeting + disclosure, or the persona opening for outbound) is spoken once when the pipeline is ready and is protected from interruption exactly like VO-08.
* A caller turn matching the farewell rule ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-02) or a safety phrase ([/architecture/escalation.md](/architecture/escalation.md)) is detected on the **final transcript**, which arrives after the caller stopped speaking. The model may already have started answering; the bridge cancels that response before speaking the fixed line, so up to a fraction of a second of the model's own speech can be heard first. This is the main behavioral difference from the cascade and is accepted for the lower latency.
* The `escalate_to_human` tool result tells the model to say the hand-off message verbatim; the bridge then ends the call after the speech finished (CE-01).

# Streaming and latency

* Audio is **streamed end to end**: caller audio goes to the service as it is captured (no waiting for a turn), and the model's audio deltas are forwarded to the caller as they arrive, frame by frame. Nothing waits for a complete reply. Transcript text for events is assembled alongside and never delays playback.
* Barge-in: when the service reports the caller started speaking, queued playback is dropped (`interrupt` to the browser, `clear` to Twilio) and the in-flight reply is cancelled; the assistant event is stored with `[interrupted]` as in VO-03.
* **Target**: p50 time from end of caller speech to first agent audio below **0.8 s**, p95 below 1.5 s, measured at the server (end of the service's speech-stopped event to first forwarded audio frame) over at least 20 turns per path. This is a target to verify in spike S4, not a guarantee, and it excludes the caller's network and the phone network. `assistant` events store `latency_ms` measured this way for realtime calls.
* Tool turns add the tool's own time (default 8 s timeout, [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md)); the addendum asks the model to say one short phrase before a slow tool, the realtime counterpart of `policy.voice_filler`.
* Keep the Cloud Run region close to the provider (default `us-central1`) and the service warm (min instances 1, [/architecture/deployment.md](/architecture/deployment.md)).

# Turn detection mapping

The agent's `voice.turn_detection` ([/architecture/turn-detection.md](/architecture/turn-detection.md)) is translated, since the service detects turns itself:

| Setting | Realtime service |
|---|---|
| `mode: vad` | server voice-activity turn detection; `min_silence_ms` is the silence duration before the turn ends |
| `mode: semantic` | the service's semantic turn detection |
| `max_extra_wait_ms`, `evaluator` | ignored (the service decides; the Voice tab says so for realtime agents) |
| `allow_interruptions` | whether caller speech interrupts the reply (`false` holds the caller's turn until the reply ends, as in the cascade) |

Live controls on the Test call page for turn detection and persona ([/architecture/personas.md](/architecture/personas.md)) apply to cascade calls only; on a realtime call they are disabled with a note, and `PATCH /api/calls/{id}/live` returns 409 `realtime_pipeline` (RV-15).

# Configuration

* `voice.realtime.voice`: one of the voices listed under the `speech` role in `models.yaml` ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)); default is that role's first voice. The persona's Deepgram voice and speed are ignored in realtime mode.
* `models.speech`: `null` (role default) or a speech model ref; chat models are rejected.
* Model IDs, voices, the transcription model and prices live only in `apps/api/config/models.yaml`; the model ID is Pipecat 1.12's default Realtime model and the prices are placeholders to confirm in the OpenAI console (spike S4 could not reach it).
* `OPENAI_REALTIME_URL` (default `wss://api.openai.com/v1/realtime`) overrides the endpoint, for tests and proxies.
* The OpenAI key for a realtime call is resolved per tenant: the tenant's own key, else the platform `OPENAI_API_KEY` when the tenant allows the fallback ([/architecture/tenant-settings.md](/architecture/tenant-settings.md)); the source is chosen once per call by [call admission](/architecture/call-admission.md). No usable key → the voice socket closes with 4500 `voice_unavailable`, the API stays healthy (RV-03). `DEEPGRAM_API_KEY` is not needed for a realtime agent.

# Cost

The service reports token usage per response, split into text and audio tokens. The bridge adds it to the call's `tokens_in`, `tokens_out` and `llm_cost_usd` using the audio and text prices of the speech model in `models.yaml`. An unknown model costs 0 with a warning, as for chat models. Realtime audio is priced well above the cascade's text tokens plus Deepgram minutes; the Dashboard's cost figures stay correct only while the price table is.

# Failures

* The provider socket cannot be opened → the voice socket closes with 4500.
* The provider socket drops or errors mid-call → the caller hears nothing more; the call ends with reason `error` and is escalated with category `other` (the realtime counterpart of RT-06; a phone call is transferred if `telephony.transfer_to` is set).
* There is no automatic fallback to the cascade within a call. An operator switches an agent back by republishing it with `voice.pipeline: cascade`.

# Evaluation and learning trade-offs

* **Simulation uses the text brain.** Evaluation runs ([/architecture/evaluation.md](/architecture/evaluation.md)) drive `AgentSession` as a text channel with the chat role `realtime` (or the agent's `models.realtime`), because a simulated caller has no voice. For a realtime agent this exercises the prompt, tools, skills, knowledge and guards, which are shared, but not the speech model's wording, turn-taking or interruptions. Results are labelled **text approximation** in the run summary and must not be read as proof of spoken quality; real calls are the evidence.
* **Fleet learning works on real calls.** Realtime calls store the same events, so call analysis, clustering, impact and fix drafting need no change. Transcripts come from the service's transcription of the caller, which can differ slightly from the cascade's.
* **Fixes still land in knowledge, skills and rules**, which both pipelines share, so one approved fix improves both.

# Acceptance

- **RV-01** — Given an agent config with `voice.pipeline: "realtime"` or `"cascade"` or no value, when saved, then it is accepted and absent means `cascade`; any other value returns 422; the value is part of the published version snapshot.
- **RV-02** — Given a published realtime agent and a published cascade agent, when each opens its voice socket, then the realtime agent builds the realtime pipeline (no Deepgram service constructed) and the cascade agent builds the unchanged Deepgram pipeline; the wire protocol of the browser socket is identical for both.
- **RV-03** — Given a realtime agent whose tenant has no OpenAI key of its own and `OPENAI_API_KEY` unset, when its voice socket opens, then it closes with 4500 `voice_unavailable` and `/healthz` stays `ok`; with `DEEPGRAM_API_KEY` unset and `OPENAI_API_KEY` set the same agent connects.
- **RV-04** — Given a realtime call, when the session is configured, then its instructions equal the assembled system prompt for that agent version followed by the realtime addendum, and its function list equals the built-in tools plus the agent's tools with the same schemas as the text channel.
- **RV-05** — Given a function call from the service for a tool marked `requires_verification` on an unverified call, then no business-API request is made, the model receives `identity_not_verified`, and the `tool_call` and `tool_result` events are stored in order; after `verify_member` succeeds the same tool runs; a fifth tool call in one turn returns `tool_round_limit`.
- **RV-06** — Given a final user transcript and the completed reply, then a `user` event and an `assistant` event (with `latency_ms`) are stored in order and `turns` increases by one; a reply cut off by the caller is stored with the `[interrupted]` suffix.
- **RV-07** — Given a realtime call whose pipeline is ready, then the welcome is spoken exactly once as exact text and sound from the caller during it neither cancels it nor is answered; after it finishes, caller speech interrupts as configured.
- **RV-08** — Given a final caller transcript that is a farewell phrase or contains a safety phrase while the model is already replying, then the in-flight response is cancelled and the fixed line (closing line, or safety message with a `safety` escalation) is spoken verbatim; no further model reply is requested for that turn.
- **RV-09** — Given `escalate_to_human`, then the tool result carries the hand-off message, the bridge has it spoken verbatim, the call ends with reason `handoff` after the speech finished, and exactly one escalation row exists (ES-08).
- **RV-10** — Given `voice.turn_detection` of `mode: vad`, `min_silence_ms: 700`, `allow_interruptions: false` and then `mode: semantic`, then the service session is configured with server turn detection at 700 ms and no interruption, and with semantic turn detection; `evaluator` and `max_extra_wait_ms` have no effect.
- **RV-11** — Given a realtime call, when the caller is silent past `policy.silence_reminder_s` and `policy.silence_end_s`, or the call reaches `policy.max_call_seconds`, then the reminder, the closing line and the end reasons `idle` and `max_duration` are the same as in CE-04 and CE-05, and neither timer runs during the welcome, while the agent speaks or while a tool runs.
- **RV-12** — Given a response with reported usage of text and audio tokens, then the call's `tokens_in`, `tokens_out` and `llm_cost_usd` increase by the cost computed from the speech model's text and audio prices.
- **RV-13** — Given the provider socket fails to open, then the voice socket closes with 4500; given it drops mid-call, then the call ends with reason `error` and is escalated with category `other`.
- **RV-15** — Given a running realtime call, when `PATCH /api/calls/{id}/live` is sent, then the response is 409 `realtime_pipeline` and nothing changes; the same request on a cascade call still succeeds.
- **RV-16** — Given two tenants that both allow realtime, tenant A with its own OpenAI key and tenant B without one and with fallback on, when each places a realtime call, then A's provider connection authenticates with A's key and B's with the platform key, and each call's `settings.openai_key_source` is `tenant` and `platform` respectively.
- **RV-14** — Given a realtime agent, when an evaluation run is started, then the simulated calls use the text channel with the chat role `realtime`, no speech-model request is made, and the run summary carries `pipeline: "realtime"` and `fidelity: "text_approximation"`.
