---
type: Decision Record
title: ADR-0013 OpenAI Realtime as the video call's brain
description: "Run video calls on one OpenAI Realtime speech-to-speech model in the existing Pipecat, LiveKit and Simli pipeline, with our tools and call rules on top, keeping the speech-to-text and text-to-speech chain as the fallback."
status: stable
tags: [decision, video, avatar, realtime, openai, latency]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# Context

The video call's latency is the sum of its steps: our turn wait (700 ms of silence by default), speech-to-text, the text model, text-to-speech, the Simli face and LiveKit. After CP-0016 and CP-0017 it no longer drifts and the face is ready early, but it still does not feel live. The reference implementation that does ([ADR-0012](adr-0012-gemini-live-avatar.md)) has one model doing listening, thinking and speaking; it needs Vertex AI access the project does not have.

What was checked:

| Claim | How | Status |
|---|---|---|
| Pipecat 1.12.0 ships `OpenAIRealtimeLLMService` and `GeminiLiveLLMService` (AI Studio key) | Listed in the installed package | Verified |
| The OpenAI service takes an API key, does server-side voice-activity detection, transcribes the caller, calls functions, and returns speech as `TTSAudioRawFrame` with `TTSStarted/StoppedFrame` | Read from the installed source | Verified from code |
| It pushes the assistant's words as `LLMTextFrame`/`TTSTextFrame`, so a text-to-speech stage after it would double-speak | Read from the installed source | Verified from code |
| Caller transcription arrives after the model starts to answer | The event order in the source (`input_audio_transcription.completed`) | Verified from code; magnitude unmeasured |
| The default model id in this Pipecat version is `gpt-realtime-2.1` | Source default | Verified; whether the account can use it is not |
| The Simli stage lip-syncs this audio acceptably, and the end-to-end latency | Nothing | **Unmeasured.** `scripts/realtime_spike.py` and a real call measure it (CP-0019, T36, not yet run) |
| Simli publishes under 300 ms for speech-to-video | Vendor and a third-party comparison | Vendor claim, measures rendering only |

# Options

1. **OpenAI Realtime in the existing pipeline, Simli kept for the face (chosen).** Four stages removed, no new vendor, no new transport; works on the key already in `.env`.
2. **Gemini Live on an AI Studio key, Simli kept.** Same shape, a second vendor key to obtain. A reasonable later alternative behind the same seam.
3. **Gemini Live with Google's avatar on Vertex AI.** The reference's design. Needs access the project lacks (rejected, [CP-0018](../changes/cp-0018-gemini-live-avatar-channel.md)).
4. **Tune the chain only.** Lowering `min_silence_ms` is free and available now; it does not remove a step.
5. **Swap the face vendor.** Vendors publish rendering latency only, and Simli is already among the fast ones. Little gain.

# Decision

Option 1, for **video calls only**, as a second **brain** behind a configuration switch, not a replacement. The chain stays as the fallback and as the only brain for a deployment without an OpenAI key. Voice (WebSocket) calls are not moved.

Everything that makes the product more than a voice demo stays ours and runs on top of the model's events: tools through the conversation module's executor and its identity gate, transcripts as call events, the safety screen, escalation, the ending rules, the clocks, and the camera evidence flow ([/architecture/realtime-brain.md](/architecture/realtime-brain.md)).

# Consequences

* **Two brains to keep working.** Their criteria differ (RB-* for the new one, VO-* and TD-* for the chain). Retiring one is a later proposal.
* **Turn-taking is the model's.** Our TurnAggregator does not run; its two modes map onto OpenAI's two voice-activity detectors (RB-07). The `semantic` mode's extra-wait setting has no equivalent and is ignored.
* **One voice for every agent**, and a persona switch changes the instructions only (RB-10).
* **The safety screen is later than on the chain.** The caller's transcript arrives after the model begins to answer, so the screen can interrupt but not pre-empt (RB-06). The message wording stays exact because our text-to-speech renders it. This is a regression against rule 6 and is raised for review.
* **Instructed lines are not verbatim.** The welcome (with the disclosure), reminder, closing and hand-off are recorded exactly and spoken by the model from instruction (RB-04).
* **More of the call goes to OpenAI.** The caller's speech streams to it for the whole call instead of to Deepgram. The camera does not (VI-03). A BAA is a production gap (rule 14).
* **Cost per minute is higher** than the chain on cheap models and is unmeasured here; the spike prices it.
* **Evaluation does not exercise it.** Simulation and the judge run the text runtime.
* **The fallback inside this decision:** if the spike shows the face does not lip-sync the model's audio acceptably, the realtime brain still ships with the placeholder tile (AV-05 passes the audio through unchanged), keeping the latency gain without the face.
