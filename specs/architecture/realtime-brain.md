---
type: Component Spec
title: Realtime brain
description: "How a video call runs on one OpenAI Realtime model inside the existing Pipecat, LiveKit and Simli pipeline: which stages leave, what stays ours and runs on top of the model's events, and how it fails."
status: draft
tags: [architecture, video, avatar, realtime, openai, latency]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# What this is for

A call feels live when few steps stand between the caller's voice and the agent's face. The `pipeline` brain has six in series. The `realtime` brain has one model doing listening, thinking and speaking, and the Simli face and LiveKit after it. The decision and the alternatives are in [ADR-0013](/decisions/adr-0013-openai-realtime-brain.md).

It is a **brain** for `channel: "video"` calls on the LiveKit engine. The room, tokens, frame tap, Simli stage and browser are unchanged ([/api/media-protocol.md](/api/media-protocol.md), [/architecture/avatar.md](/architecture/avatar.md)). Voice and text calls are unaffected.

# Topology

```
LiveKit input ─▶ FrameTap ─▶ user aggregator ─▶ OpenAI Realtime service ─▶ Simli avatar ─▶ LiveKit output ─▶ assistant aggregator
 (caller audio)  (video held,   (context)         │  server voice-activity detection         (face + audio)
                  never sent)                     │  caller transcription
                                                  ├─ function calls ─▶ conversation executor (our tools, identity gate)
                                                  └─ transcripts, usage, speech boundaries ─▶ RealtimeBrain (ours)
                                                      welcome · safety · clocks · ending · call events · fixed audio
```

| Leaves the video pipeline | Why |
|---|---|
| Silero voice-activity detector, Deepgram speech-to-text | The model hears the audio and detects the turn itself |
| `TurnAggregator` | Its 700 ms silence wait and its transcripts are exactly what this removes |
| `BrainProcessor`, Deepgram text-to-speech | The model replies and speaks |

The Pipecat pieces stay in the `voice` module (MOD-04). The service emits the same `TTSAudioRawFrame`, `TTSStartedFrame` and `TTSStoppedFrame` the Simli stage already consumes, so AV-03 to AV-05 hold unchanged: if the face fails, the model's speech passes through and is still heard.

# Availability and choice

`VIDEO_BRAIN` is `auto` (default), `realtime` or `pipeline`. The realtime brain is **available** when `OPENAI_API_KEY` is set, the Pipecat OpenAI Realtime service imports, and the `speech` role in `models.yaml` resolves to an OpenAI model. Anything less makes it unavailable, which is not an error: the call uses the `pipeline` brain and the reason is logged. `auto` picks `realtime` when available. `POST /api/calls` reports the choice as `media.brain` (RB-01). A call keeps its brain for its whole life.

| Setting | Meaning |
|---|---|
| `speech` role | The model id and its price per million tokens (text and audio priced separately) in `config/models.yaml`; never a literal in code ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)) |
| `REALTIME_VOICE` | One voice for every agent in this change |
| `VIDEO_BRAIN` | As above |

# What stays ours

The model decides what to say; the product's rules do not move into a prompt.

| Concern | How it holds on this brain |
|---|---|
| Instructions | The agent's rendered system prompt ([/prompts/agent-system-prompt.md](/prompts/agent-system-prompt.md)) followed by [/prompts/realtime-session-addendum.md](/prompts/realtime-session-addendum.md) (RB-05) |
| Tools and the identity gate | The agent's built-ins and tools are registered as functions. A call is executed by the conversation module's tool executor, the one the text runtime uses; `tool_call` and `tool_result` events are recorded in order and call state updates. A `requires_verification` tool is refused before the caller is verified ([/product/healthcare-compliance.md](/product/healthcare-compliance.md) rule 3). `look_at_camera` is offered on a video call only, as today (RB-05). |
| Transcripts | A finished caller transcript is a `user` event; a finished reply is an `assistant` event with `latency_ms` from end of caller speech to the first audio frame. Analysis, feedback, the console and the explorer need no change (RB-08). |
| Turn detection | `vad` mode becomes the model's server detection with `silence_duration_ms` = the agent's `min_silence_ms`; `semantic` mode becomes its semantic detection. `max_extra_wait_ms` has no equivalent and is ignored. The live switch updates the session ([/architecture/turn-detection.md](/architecture/turn-detection.md), RB-07). |
| Persona | The persona's style is in the instructions. Its Deepgram voice and speed are ignored. A live persona switch updates the instructions only (RB-10). |
| Safety screen | Each final caller transcript is checked against the safety phrase list ([/architecture/escalation.md](/architecture/escalation.md)). On a match the response in progress is interrupted, the call is escalated with category `safety`, the fixed safety message is recorded and **rendered by our text-to-speech and pushed as audio**, not spoken by the model, so its wording is exact. The transcript arrives after the model has begun to answer, so the screen **cannot prevent the first words of a reply**; it stops it (RB-06). |
| Welcome | When the caller has joined and the face is ready (or 5 s have passed, CP-0017), the model is instructed to say the greeting from `AgentSession.start()` once. It is protected as VO-08 is: caller audio is not passed to the model and no caller turn is answered until it finishes or 15 s pass (RB-03). |
| Instructed lines | The welcome, the silence reminder, the closing line and the hand-off line are recorded and shown exactly and are spoken by the model from instruction, so their audio wording is not guaranteed verbatim (RB-04). |
| Ending and clocks | `end_call`, a farewell, `escalate_to_human`, idle and maximum duration end the call with the reasons they always had. The closing words finish first (at most 10 s, CE-06). The silence and length clocks use the policy values of CE-04 and CE-05 (RB-09, RB-11). |
| Camera | Unchanged: the frame tap holds one frame and drops video from the pipeline, so nothing reaches the model; `look_at_camera` describes through the `vision` role (VI-03). |
| Cost | The model's usage, text and audio tokens, is priced from the `speech` role and added to the call's tokens and `llm_cost_usd` (RB-12). |

# When it fails

The realtime connection failing at start, or dropping mid-call, ends the call with reason `error`, shows the caller a message, keeps the transcript so far and queues the analysis. Nothing waits longer than 10 s and no second brain takes over, because the caller would meet an agent that had forgotten the conversation (RB-13). A face that fails does not end the call (AV-05).

# Latency

The step count falls from six to four. Simli's rendering stays in the path. The intent is a clear improvement over the chain; how much is measured by the spike (CP-0019, T36) and by hand, and is not a criterion.

# Acceptance

- **RB-01** — Given `VIDEO_BRAIN` is `auto`, `OPENAI_API_KEY` is set, the realtime service imports and the `speech` role resolves, when `POST /api/calls` is called with `channel: "video"`, then `media.brain` is `realtime`; and given any of them absent, then it is `pipeline` and the call is still created; and given `VIDEO_BRAIN` is `pipeline`, then the chain is used whatever else is configured.
- **RB-02** — Given a video call on the realtime brain, when its pipeline is built, then it contains the realtime service, the frame tap, the avatar stage when present and the transport output in that order, and contains no speech-to-text, turn aggregator, text-to-speech or voice-activity stage; and given the chain brain, then its processor order is exactly that of CP-0013 and CP-0014.
- **RB-03** — Given the realtime brain with the caller joined, when the welcome is due, then the model is instructed to say the greeting exactly once; and given the caller speaks during it, then that audio is not passed to the model and no turn is answered until it finishes or 15 s pass.
- **RB-04** — Given the welcome, a silence reminder, a closing line or a hand-off line, then the exact text is recorded as an `assistant` event and sent to the page, and the model is instructed to say precisely that text.
- **RB-05** — Given a session on the realtime brain, when it is configured, then its instructions are the agent's system prompt followed by the realtime addendum, every agent tool and built-in is registered, and `look_at_camera` is registered only on a video call; and the model id comes from configuration.
- **RB-06** — Given a final caller transcript that matches the safety phrase list, then the response in progress is interrupted, the call is escalated with category `safety`, the fixed safety message is recorded, and exactly that text is rendered by the text-to-speech provider and delivered as audio, not spoken by the model; the call then ends `handoff`; and given text-to-speech is unavailable, then the message is still recorded and shown and the model is instructed to say it.
- **RB-07** — Given an agent with `mode: vad` and `min_silence_ms: 500`, then the session's detection is server voice-activity detection with a 500 ms silence duration; and given `mode: semantic`, then it is semantic detection; and given a live change of either, then the session is updated and the call continues.
- **RB-08** — Given finished caller and reply transcripts, then one `user` and one `assistant` event are recorded in order, `turn_count` increases, and the `assistant` event carries `latency_ms`.
- **RB-09** — Given the caller says nothing, then the reminder is spoken after `policy.silence_reminder_s` and the call ends `idle` after `policy.silence_end_s`, neither clock runs during the welcome, while the agent speaks or while a reply is being produced; and given `policy.max_call_seconds` passes, then the call ends `max_duration`.
- **RB-10** — Given a live persona switch on a realtime call, then the instructions are updated, a `system` event "Persona switched to ..." is recorded, the greeting is not repeated, and the voice does not change.
- **RB-11** — Given the model calls `end_call`, `escalate_to_human`, or the caller says a farewell phrase, then the closing words finish first (at most 10 s), the call ends with the matching reason, and the analysis job is queued once.
- **RB-12** — Given the session reports usage, when a response completes, then the call's `tokens_in`, `tokens_out` and `llm_cost_usd` increase by it, priced from the `speech` role with audio and text tokens separately; and given a model with no configured price, then the cost counts as zero and a warning is logged, not an error.
- **RB-13** — Given the realtime connection cannot be opened or drops mid-call, then the call ends with reason `error`, the caller sees a message, the transcript is kept, nothing waits longer than 10 s, and no other brain takes over.
- **RB-14** — Given `OPENAI_API_KEY` or any credential, when any API response, log line, call event or message to the browser is produced during a realtime call, then it appears in none of them.
