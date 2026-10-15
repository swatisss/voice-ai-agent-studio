---
type: Change Proposal
title: CP-0019 OpenAI Realtime brain for video calls
description: "Video calls can run on one OpenAI Realtime speech-to-speech model inside the existing Pipecat, LiveKit and Simli pipeline, replacing speech-to-text, our turn wait, the text model and text-to-speech, with our tools, safety screen and call rules kept on top."
status: draft
cp_state: proposed
tags: [video, avatar, realtime, openai, latency, architecture]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# Why

After CP-0016 and CP-0017 the video call no longer drifts and loads its face early, but it does not feel live. A reply crosses six steps in series: our own turn wait (700 ms of silence by default), Deepgram speech-to-text, the text model, Deepgram text-to-speech, Simli and LiveKit. Simli, the step people suspect, publishes under 300 ms; most of the delay is in front of it and some of it is our own setting. No tuning of the chain removes a step.

A reference implementation ([awesome-llm-apps PR #1203](https://github.com/Shubhamsaboo/awesome-llm-apps/pull/1203)) feels instant because one speech-to-speech model does listening, thinking and speaking. The Gemini Live version needs Vertex AI access the project does not have ([CP-0018](cp-0018-gemini-live-avatar-channel.md), rejected). The same shape is available on an ordinary key: **Pipecat 1.12.0 ships `OpenAIRealtimeLLMService`** (checked in the installed package), which takes caller audio, does its own turn detection and transcription, calls tools, and returns 24 kHz speech as the same `TTSAudioRawFrame`s the Simli stage already consumes. The repo already holds an `OPENAI_API_KEY` for vision.

# What changes

1. **A video call has a brain.** `pipeline` is today's chain. `realtime` is new. `VIDEO_BRAIN` is `auto` (default: `realtime` when it is available, else `pipeline`), `realtime` or `pipeline`. The transport, the room, the frame tap, the Simli face and the browser are unchanged. `POST /api/calls` reports it as `media.brain` (RB-01).
2. **Four stages leave the video pipeline** when the brain is `realtime`: the local voice-activity detector, Deepgram speech-to-text, our TurnAggregator and Deepgram text-to-speech. The `BrainProcessor` is replaced by a `RealtimeBrain` of ours. A single OpenAI Realtime service sits where they were, in front of the Simli stage ([/architecture/realtime-brain.md](/architecture/realtime-brain.md)).
3. **What stays ours (RB-05…RB-12).** Tools run through the conversation module's executor, so the identity gate, events and call state are unchanged. Transcripts become the same `user` and `assistant` events. The safety screen, the welcome, escalation, the ending rules, and the silence and maximum-length clocks are re-implemented on top of the model's events.
4. **Turn detection maps onto the model's own** (RB-07): the `vad` mode becomes OpenAI's server voice-activity detection with the agent's `min_silence_ms`, the `semantic` mode becomes its semantic detection. The settings and the live switch keep working.
5. **The safety message stays word for word (RB-06).** It is rendered by our text-to-speech and pushed as audio; the model does not speak it.
6. **The camera is unchanged.** Frames still stop at the frame tap, `look_at_camera` is a tool, the description still comes from the `vision` role, and no frame reaches the realtime model (VI-03, compliance rule 10).
7. **The `pipeline` brain stays**, unchanged, as the fallback and for any deployment without an OpenAI key. The avatar criteria (AV-*) and the visual-intake criteria (VI-*) hold on both brains.

# Decisions taken while drafting

* **Video calls only.** Voice calls (WebSocket) keep the chain. Moving them is a later proposal with the same machinery.
* **Server-side turn detection, not our TurnAggregator.** Our aggregator works from Deepgram transcripts, which this brain does not produce. The alternative (OpenAI's manual mode driven by local voice-activity detection) would keep more of our code but keeps a local detector and the delay it adds.
* **One voice for every agent.** The model's voice is `REALTIME_VOICE`; a persona's Deepgram voice and speed are ignored on this brain. A persona switch changes the instructions only (RB-10).
* **Welcome, reminder, closing and hand-off lines are instructed, not rendered.** The recorded and displayed text is exact; the spoken wording is the model's reading of it and is not guaranteed verbatim. Rendering them through Deepgram would be exact but a different voice from the rest of the call. Only the safety message, where wording matters most, takes the exact path. Raised under Open questions.
* **No automatic switch between brains.** A call picks its brain at creation. A failure after creation ends the call with reason `error` (RB-13); swapping brains mid-call would give the caller an agent that had forgotten the conversation.
* **The model id is configuration.** Pipecat's default for the installed version is `gpt-realtime-2.1`; the product names it as a role in `models.yaml`, never a literal in code, and the spike confirms it against the account.

# Found while drafting

* The OpenAI service pushes the assistant's words downstream as `LLMTextFrame` / `TTSTextFrame` for transcripts (it does not mark them to be skipped by text-to-speech). A text-to-speech stage placed after it would therefore **speak every reply a second time**. The exact-wording path for the safety message must not be a pipeline stage; it is rendered separately and injected as audio (RB-06).
* Its transcript of the caller's speech arrives **after** the model has begun to answer. The safety screen can therefore trigger late, after a few words of an answer have been spoken. It interrupts, escalates and speaks the safety message, but it cannot prevent the first words (RB-06). This is a regression against the text pipeline, where the screen runs before any model call, and is raised under Open questions.

# Affected specs

New: [/architecture/realtime-brain.md](/architecture/realtime-brain.md) (RB-01…RB-14), [/decisions/adr-0013-openai-realtime-brain.md](/decisions/adr-0013-openai-realtime-brain.md), [/prompts/realtime-session-addendum.md](/prompts/realtime-session-addendum.md).

Updated (set to `draft`): [voice pipeline](/architecture/voice-pipeline.md), [agent runtime](/architecture/agent-runtime.md), [turn detection](/architecture/turn-detection.md), [LLM gateway](/architecture/llm-gateway.md) (the `speech` role), [avatar](/architecture/avatar.md) (the stage's position), [REST API](/api/rest-api.md) (`media.brain`), [healthcare compliance](/product/healthcare-compliance.md) (rule 14), [tech stack](/architecture/tech-stack.md), [test call UI](/ui/test-call.md) (UI-52), [conventions](/process/conventions.md) (prefix `RB`), [task plan](/build/task-plan.md) (T36…T41).

# Acceptance criteria

New: **RB-01…RB-14**, **UI-52**. No ID is changed or retired. AV-02 is reworded for the stage's position on the new brain; its intent is unchanged.

# Tasks

1. **T36 (spike, gates the rest)** - with the real `OPENAI_API_KEY`: confirm the model id and that the account can use it, the voice names, tool-call behaviour, how the transcript timing really falls, whether the Simli stage lip-syncs the model's audio acceptably, and the **measured latency** from end of caller speech to the first avatar frame, against the current chain. Write it up in `specs/verification/` and amend this CP with what was found.
2. **T37** - the `speech` role and price table, `VIDEO_BRAIN`, `REALTIME_VOICE`, availability, `media.brain`, the `pipeline` builder branch - covers RB-01, RB-02, RB-14.
3. **T38** - tools through the executor, transcripts, usage and cost - covers RB-05, RB-08, RB-12.
4. **T39** - welcome gate, ending, silence and length clocks, turn-detection mapping, persona switch - covers RB-03, RB-04, RB-07, RB-09, RB-10, RB-11.
5. **T40** - safety screen and the exact-wording path - covers RB-06.
6. **T41** - failure handling, web note, runbook and compliance notes - covers RB-13, UI-52.

# Risks and rollout

* **Behavioural parity.** The model is the brain, so replies are not what the text runtime would say, and evaluation and simulation keep using the text runtime, so a regression here is caught only by tests with a fake service and by hand. The spike's measurements are the main safeguard.
* **Compliance.** The caller's speech streams to OpenAI for the whole call instead of to Deepgram. OpenAI is already a provider (vision), but a Business Associate Agreement is a production gap (rule 14).
* **Latency is a target, not a promise.** The step count falls from six to four (model, Simli, LiveKit, and the model's own turn handling), and Simli's roughly 300 ms stays in the path, so expect a clear improvement and not the reference's feel. The spike measures it before more is built.
* **Cost.** Realtime audio tokens cost more per minute than the current chain on cheap models; the spike prices a minute of call.
* **Rollback:** set `VIDEO_BRAIN=pipeline`. Nothing about the chain changes.

# Out of scope

Voice (WebSocket) calls, a face or voice per persona, streaming the camera to the model, generated imagery, running evaluation and simulation on this brain, Gemini Live and Vertex ([CP-0018](cp-0018-gemini-live-avatar-channel.md)), retiring the chain.

# Open questions for the reviewer

1. Is a safety screen that can trigger a few words late (the transcript arrives after the model starts) acceptable for a healthcare demo, given rule 6? Alternative: hold the model's reply until the transcript of the caller's turn is in, which costs latency on every turn.
2. Are welcome, reminder, closing and hand-off lines that are instructed, not rendered, acceptable? The disclosure in the welcome is rule 2. Alternative: render the welcome through Deepgram, in a different voice.
3. Is a single voice for all agents, and a persona switch that changes style only, acceptable on this brain?
4. Is the OpenAI account the one in `.env`, and does it have access to the Realtime model?
