---
type: Component Spec
title: Voice pipeline
description: Browser microphone audio over a WebSocket through a Pipecat pipeline - VAD, Deepgram STT, turn aggregation, the agent runtime, Deepgram TTS - with barge-in.
status: stable
tags: [architecture, voice, pipecat]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Topology

```
browser mic ─PCM16 16k─▶ WS /api/voice/{call_id} ─▶ Pipecat FastAPIWebsocketTransport (Silero VAD)
                                                        │
                    Deepgram STT (nova-3, streaming) ◀──┘
                                │ TranscriptionFrame (finals)
                    TurnAggregator  ── user turn text ──▶ BrainProcessor (AgentSession.respond)
                                                               │ TextFrames (streamed)
                    Deepgram TTS (persona voice) ◀─────────────┘
                                │ OutputAudioRawFrame 24k
browser speaker ◀─PCM16 24k── transport.output()
```

Wire format and control messages: [/api/voice-protocol.md](/api/voice-protocol.md). Only `voiceai/voice/` imports Pipecat ([/decisions/adr-0002-voice-pipeline.md](/decisions/adr-0002-voice-pipeline.md)).

# Pipeline processors

1. **Transport input** — `FastAPIWebsocketTransport` with a custom `RawPCMSerializer` (binary in → `InputAudioRawFrame` 16 kHz mono; JSON text → control). VAD: Silero, `stop_secs` 0.2 (`VOICE_VAD_STOP_SECS`); the longer silence a turn needs is applied by the TurnAggregator. Interruptions follow `allow_interruptions` ([/architecture/turn-detection.md](/architecture/turn-detection.md)).
2. **STT** — Deepgram streaming, model `nova-3`, `en-US`, smart formatting on, interim results on (interims are ignored by the brain).
3. **TurnAggregator** (ours) — collects final transcripts into one caller turn and decides when the turn is over, in **normal** (silence) or **semantic** mode, with settings read live from the call's `LiveControls`. Full algorithm, evaluator rules and settings: [/architecture/turn-detection.md](/architecture/turn-detection.md).
4. **BrainProcessor** (ours) — wraps one `AgentSession`:
   * **welcome**: once the client is connected *and* the pipeline has started, send `ready`, then speak the welcome exactly once — the persona greeting and disclosure for inbound and internal agents, the persona opening for outbound agents ([/architecture/call-modes.md](/architecture/call-modes.md)) — the same text `AgentSession.start()` records as the first assistant event. The welcome is **protected**: from the moment it starts until the agent has finished speaking it (or a safety timeout scaled to its length, at least 15 s, elapses) caller speech does not interrupt it and caller turns heard in that time are dropped, not answered. Without this, any sound the microphone picks up — including the agent's own voice from open speakers — interrupted the welcome after about a second and the call carried on as if the caller had spoken;
   * on user turn: if `allow_interruptions` is false and the agent is still speaking or responding, hold the turn and answer it after the agent finishes; otherwise cancel any in-flight response task, then start `respond(text)` and push each chunk downstream as text between LLM-response start/end frames so TTS speaks it sentence by sentence;
   * on interruption: cancel the in-flight task (partial reply is still recorded, suffixed `[interrupted]`);
   * **silence and length** ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-04, CE-05): a silence clock starts when the agent stops speaking and is cleared when the caller starts speaking; after `policy.silence_reminder_s` it speaks the reminder once, after `policy.silence_end_s` it speaks the closing line and ends the session with reason `idle`; a call clock ends the session with reason `max_duration` at `policy.max_call_seconds`. Neither silence timer runs during the welcome, while the agent speaks or while a reply is being produced;
   * when the session ends for any reason (`end_call`, `farewell`, `handoff`, `idle`, `max_duration`): after the final text has been spoken (at most 10 s) send the `end` control message with that reason and close (CE-06).
5. **TTS** — Deepgram, voice and speed from the persona (`aura-2-thalia-en`, 1.0 by default), output 24 kHz PCM16. When the persona is switched live, a TTS settings update (`TTSUpdateSettingsFrame`) changes voice and speed for the next sentence ([/architecture/personas.md](/architecture/personas.md)).
6. **Transport output** — serializer sends binary PCM to the browser; on interruption it sends `{"type":"interrupt"}` so the browser flushes queued audio.

# Lifecycle

* The call row must exist (`POST /api/calls` with `channel: voice`) before the WebSocket opens; unknown or ended `call_id` → close with code 4404.
* Browser `hangup` message or socket close → `AgentSession.end("hangup")` and pipeline teardown.
* A `LiveControls` object is registered for the call when the socket is accepted and removed at teardown.
* Missing Deepgram key → the WebSocket closes with code 4500 and reason `voice_unavailable`; the UI suggests the Type tab.

# Latency

* Target p50 < 1.2 s from end of caller speech to first agent audio on Groq.
* `assistant` events store `latency_ms` = time from turn dispatch to first text chunk.
* Filler line before tool rounds is on by default for voice (`policy.voice_filler`).

# Acceptance

- **VO-01** — Given a voice call, when the socket connects, then the caller hears the greeting without speaking first (checked by hand with real audio; the automated checks are VO-07 and VO-08).
- **VO-07** — Given a voice call whose pipeline has started, when the client is connected, then the brain emits the `ready` control message and then the welcome text exactly once, as one spoken response — greeting + disclosure for an inbound or internal agent, the rendered opening for an outbound agent — and a repeated connect signal does not speak it again.
- **VO-08** — Given the welcome is playing (interruptions allowed), when the caller starts speaking or the microphone picks up the agent's own voice, then no interruption is broadcast, the welcome is not cancelled, and a caller turn recognised during it is not answered; once the agent has finished the welcome (or the safety timeout passes), a caller speaking again interrupts and a caller turn is answered as in TD-07.
- **VO-02** — Given the TurnAggregator in normal mode, when two final transcripts arrive and the caller stays silent for the threshold, then the brain receives one turn containing both texts in order (detailed in TD-01).
- **VO-03** — Given the agent is speaking, when the caller starts speaking, then TTS output stops, the browser receives `interrupt`, and the in-flight response task is cancelled.
- **VO-04** — Given the WebSocket opens with an unknown call id, then it closes with code 4404.
- **VO-05** — Given `DEEPGRAM_API_KEY` is unset, when a voice socket opens, then it closes with code 4500 and the API stays healthy.
- **VO-06** — Given the pipeline module, when imported and constructed with dummy keys in tests, then no network call is made (smoke test guarding Pipecat API drift).
