---
type: Change Proposal
title: CP-0018 Gemini Live avatar channel
description: "Video calls can run on a Gemini Live session on Vertex AI whose avatar video and voice arrive together on one stream, relayed over our WebSocket, replacing the speech-to-text, model, text-to-speech, Simli and LiveKit chain; the LiveKit and Simli path stays as the fallback."
status: stable
cp_state: rejected
tags: [video, avatar, gemini, live, latency, architecture]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

> **Rejected, 2026-10-15.** The requester has no Vertex AI or Gemini Live access, so the avatar half of this proposal cannot be built or verified. It is kept as the record of the Gemini route and of what was learned from the reference implementation. Its spec edits were reverted, and its acceptance IDs (GL-01…GL-15, LV-01…LV-06, UI-49…UI-51) were never accepted and are not reused. Superseded by [CP-0019](cp-0019-openai-realtime-brain-for-video.md), which gets the same one-model latency win on OpenAI Realtime, a LiveKit room and Simli.

# Why

CP-0016 and CP-0017 fixed what could be fixed in the current video path: delay no longer grows and the face is loaded before the welcome. The result still does not feel real-time, and a reference implementation does. The path is what limits it. Every reply crosses five hops in series: Deepgram speech-to-text, our turn aggregation, the language model, Deepgram text-to-speech, then Simli, which re-times the speech and renders the face, and then LiveKit carries it to the browser. Each hop adds its own buffering, and no tuning of our code removes a hop.

The reference is the avatar added to the open-source insurance claim agent in [awesome-llm-apps PR #1203](https://github.com/Shubhamsaboo/awesome-llm-apps/pull/1203). Read from its code, not its description, it works like this:

* One **Gemini Live session on Vertex AI** (`gemini-3.8-live` by that repo's default) does listening, thinking and speaking. The session is asked for `response_modalities: VIDEO` with an `avatar_config` (a stock avatar by name, or a custom portrait), and it returns **a fragmented MP4 whose one stream carries the avatar's face and its voice**, so they share a clock and no lip-sync step exists.
* The server relays those MP4 chunks as base64 over an ordinary WebSocket; the browser appends them to a `MediaSource` on a `<video>` element. No WebRTC, no SFU, no third-party avatar vendor.
* Tools are declared `NON_BLOCKING`, so the avatar keeps talking while they run, and their results are scheduled back to the session (`WHEN_IDLE`, or `INTERRUPT` when urgent).
* Interruption is the session's own: caller speech interrupts it, and the browser drops its buffered media.

This proposal brings that shape into the product as a second **engine** for video calls, chosen by configuration, without throwing away the parts that are ours: the tools, the identity gate, the safety screen, the call-ending rules, the evidence flow and the transcript.

# What changes

1. **A video call has an engine.** `livekit` is today's path (CP-0013, CP-0014 and everything since). `gemini_live` is new. `VIDEO_ENGINE` is `auto` (default: Gemini Live when it is configured, else LiveKit), `gemini_live` or `livekit`. `POST /api/calls` reports the engine in `media` (GL-01).
2. **The Live engine replaces the middle of the pipeline, not the product.** For these calls there is no Pipecat pipeline, no Deepgram, no separate language-model turn loop, no Simli and no LiveKit room. A relay in the `voice` module connects the browser's WebSocket to a Live session through a new port, `LiveAgent`, with Google's SDK confined to one adapter (`/architecture/live-session.md`, GL-13).
3. **What stays ours (GL-06…GL-12).** Tools run through the conversation module's executor, so the verification gate, events and call state are unchanged. Transcripts become the same `user` and `assistant` events, so analysis, feedback, the console and the explorer need no change. The safety screen, escalation, the welcome, silence and maximum-length clocks, and the closing line are re-implemented on top of the session's events.
4. **The camera is pulled, not streamed.** The browser keeps the camera and sends one still only when `look_at_camera` asks for it. That is a stronger form of VI-03 than the LiveKit path, where video streams to a media server whenever the camera is on. Nothing is sent to the Live session (`/architecture/live-session.md`, GL-11).
5. **A new browser path.** A WebSocket client sends microphone PCM and answers frame requests; a MediaSource player plays the avatar stream; a voice-only fallback exists when the avatar cannot be had or played (`/api/live-protocol.md`, UI-49…UI-51).
6. **The LiveKit engine and Simli stay**, unchanged, as the fallback when Gemini Live is not configured and as the only engine for any deployment that cannot use Vertex AI. Their criteria (AV-*, VI-*) apply to that engine.

# Decisions taken while drafting

* **Engine per deployment, not per call, and no automatic mid-call switching.** A call that cannot reach the Live API at creation is created on the LiveKit engine; one whose session fails *after* creation ends with reason `error` and a message (GL-12). Two stacks switching under one caller would be hard to test and hard to explain.
* **The model is the brain on this engine.** It follows the agent's system prompt and tools, but its turn-taking is Google's, so **turn-detection modes (normal/semantic) and live persona switching do not apply** to Live calls; the UI hides them and `PATCH /live` answers 409 `unsupported_on_engine` (LV-06). One configured voice and avatar serve every agent in this change, as with Simli.
* **Look stays our vision role.** `look_at_camera` still describes a frame through the `vision` role and the evidence module, so the confidence rules, pinning, cases and the "agent said it looked" notice are unchanged. Streaming the camera into the Live session, as the reference does, would put video in front of a model with no look to anchor it and is not adopted (VI-03, compliance rule 10).
* **The safety message is spoken by the model.** A text-only pipeline can speak the fixed safety wording byte for byte; a speech-to-speech model can only be instructed to. The screen escalates deterministically and the fixed text is recorded and shown, but the audio wording is **not guaranteed verbatim** (GL-08). This is the largest behavioural gap and is raised under Open questions.
* **Facts below come from a third-party repo and press coverage, not Google's reference.** The model id, the `avatar_config` shape, the stock avatar names, whether a stock avatar needs allowlisting, and whether this works on an ordinary project are **unverified**. The first task is a spike that settles them before anything else is built.

# Affected specs

New: `/architecture/live-session.md` (GL-01…GL-15), `/api/live-protocol.md` (LV-01…LV-06), [/decisions/adr-0012-gemini-live-avatar.md](/decisions/adr-0012-gemini-live-avatar.md), `/prompts/live-session-addendum.md`.

Updated (set to `draft`): [voice pipeline](/architecture/voice-pipeline.md), [media protocol](/api/media-protocol.md), [agent runtime](/architecture/agent-runtime.md), [avatar](/architecture/avatar.md), [REST API](/api/rest-api.md), [healthcare compliance](/product/healthcare-compliance.md) (rule 14, a production gap), [modular structure](/architecture/modular-structure.md) (the `LiveAgent` port and its adapter), [tech stack](/architecture/tech-stack.md), [deployment](/architecture/deployment.md), [test call UI](/ui/test-call.md), [visual case UI](/ui/visual-case.md) (UI-49…UI-51), [conventions](/process/conventions.md) (prefixes `GL`, `LV`), [task plan](/build/task-plan.md) (T36…T42).

# Acceptance criteria

New: **GL-01…GL-15**, **LV-01…LV-06**, **UI-49…UI-51**. No ID is changed or retired; AV-* and VI-* are scoped to the `livekit` engine in prose.

# Tasks

1. **T36 (spike, gates the rest)** - with a real Vertex AI project: confirm the model id, the avatar options and stock avatar names, whether the stock avatar needs allowlisting, the region, the shape of the returned MP4 (codecs, fragment cadence), tool-call behaviour, and the **measured latency** from end of caller speech to first avatar frame. Write it up in `specs/verification/` and amend this CP with what was found. If the avatar is not available to this project, stop and decide between ADR-0012's alternatives.
2. **T37** - `LiveAgent` port, the Vertex adapter, settings, `.env.example`, `arch_check` confinement - covers GL-02, GL-13, GL-14.
3. **T38** - the relay in `voice`, engine selection and `media` for `POST /api/calls`, the WebSocket endpoint - covers GL-01, GL-03, GL-04, GL-05, GL-12, LV-01…LV-06.
4. **T39** - tools, transcripts, safety, welcome, ending and clocks on the Live session - covers GL-06…GL-10, GL-15.
5. **T40** - the camera pull and `FrameSource` over the socket - covers GL-11.
6. **T41** - web: socket client, microphone capture, MediaSource player, voice fallback, camera answers - covers UI-49…UI-51.
7. **T42** - runbooks, deployment (service account, region), compliance and demo notes.

# Risks and rollout

* **Access and unverified API (largest).** If the avatar needs allowlisting or an enterprise agreement this project does not have, the avatar half of this change cannot ship. The audio-only Live session (GL-05) still removes most hops and may be worth shipping alone. T36 decides this before any code.
* **Behavioural parity.** The model is the brain, so replies are not byte-for-byte what the text runtime would say. Evaluation and simulation keep using the text runtime and do not exercise this engine (out of scope below), so a regression here is caught only by hand and by the spike's checks.
* **Compliance.** The caller's speech streams to Google continuously for the whole call, in addition to what Deepgram receives today on the other engine. A production deployment needs a Business Associate Agreement with Google that this proposal does not obtain (rule 14).
* **Region.** Reported US and EU endpoints only.
* **Browser support.** MediaSource with H.264 and AAC is required for the face; Safari on iOS is the usual gap. The voice-only fallback covers it.
* **Cost is unknown.** Live audio and avatar minutes are priced by the vendor; the proposal does not state a figure.
* **Cloud Run.** The path is WebSocket-only, so it avoids the UDP and TURN concerns of ADR-0009 and ADR-0011. It needs a service account with Vertex AI access.
* **Rollback:** set `VIDEO_ENGINE=livekit`. Nothing about the LiveKit engine changes.

# Out of scope

Custom avatar faces from a portrait (allowlisted by Google, and a likeness question that needs its own proposal), a face or voice per persona, Gemini-generated sketches (the reference draws an incident sketch; this product's IMG-01 forbids generated evidence), streaming the camera to the model, running evaluation and simulation on the Live engine, retiring the LiveKit engine, multilingual switching, any engine switch mid-call.

# Open questions for the reviewer

1. Does the project have Vertex AI access to Gemini Live and the Avatar API, and does the stock avatar work without allowlisting? (T36 answers it; the answer may end the avatar half.)
2. Is a safety message that is **instructed, not guaranteed verbatim** acceptable for a healthcare demo, given rule 6? Alternative: on a safety match the relay mutes the model and plays a pre-rendered fixed audio clip. That is deterministic but needs a recorded clip and a face-less moment.
3. Is dropping turn-detection modes and live persona switching on this engine acceptable?
4. Keep the LiveKit engine indefinitely, or plan to retire it after the Live engine proves out?
5. Is a Google Cloud BAA in scope for the demo, or does the "synthetic data only" rule (compliance rule 1) cover it for now?
