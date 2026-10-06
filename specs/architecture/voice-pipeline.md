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

1. **Transport input** — `FastAPIWebsocketTransport` with a custom `RawPCMSerializer` (binary in → `InputAudioRawFrame` 16 kHz mono; JSON text → control). VAD: Silero, `stop_secs` default 0.5 (`VOICE_VAD_STOP_SECS`). Interruptions enabled.
2. **STT** — Deepgram streaming, model `nova-3`, `en-US`, smart formatting on, interim results on (interims are ignored by the brain).
3. **TurnAggregator** (ours) — collects final transcripts into one caller turn:
   * on `UserStartedSpeaking`: cancel any pending dispatch timer;
   * on final `TranscriptionFrame`: append text to the buffer; if the user is not speaking, (re)start the dispatch timer;
   * on `UserStoppedSpeaking`: (re)start the dispatch timer;
   * when the timer (default 350 ms, `VOICE_TURN_DELAY_MS`) fires with a non-empty buffer: emit one user turn and clear the buffer.
4. **BrainProcessor** (ours) — wraps one `AgentSession`:
   * on client connect: push the greeting text;
   * on user turn: cancel any in-flight response task, then start `respond(text)` and push each chunk downstream as text between LLM-response start/end frames so TTS speaks it sentence by sentence;
   * on interruption: cancel the in-flight task (partial reply is still recorded, suffixed `[interrupted]`);
   * when the session ends (e.g. `end_call`): after the final text is spoken, send the `end` control message and close.
5. **TTS** — Deepgram, voice from persona (`aura-2-thalia-en` default), output 24 kHz PCM16.
6. **Transport output** — serializer sends binary PCM to the browser; on interruption it sends `{"type":"interrupt"}` so the browser flushes queued audio.

# Lifecycle

* The call row must exist (`POST /api/calls` with `channel: voice`) before the WebSocket opens; unknown or ended `call_id` → close with code 4404.
* Browser `hangup` message or socket close → `AgentSession.end("hangup")` and pipeline teardown.
* Missing Deepgram key → the WebSocket closes with code 4500 and reason `voice_unavailable`; the UI suggests the Type tab.

# Latency

* Target p50 < 1.2 s from end of caller speech to first agent audio on Groq.
* `assistant` events store `latency_ms` = time from turn dispatch to first text chunk.
* Filler line before tool rounds is on by default for voice (`policy.voice_filler`).

# Acceptance

- **VO-01** — Given a voice call, when the socket connects, then the caller hears the greeting without speaking first.
- **VO-02** — Given two final transcripts within the turn delay and no new speech, when the timer fires, then the brain receives one turn containing both texts in order.
- **VO-03** — Given the agent is speaking, when the caller starts speaking, then TTS output stops, the browser receives `interrupt`, and the in-flight response task is cancelled.
- **VO-04** — Given the WebSocket opens with an unknown call id, then it closes with code 4404.
- **VO-05** — Given `DEEPGRAM_API_KEY` is unset, when a voice socket opens, then it closes with code 4500 and the API stays healthy.
- **VO-06** — Given the pipeline module, when imported and constructed with dummy keys in tests, then no network call is made (smoke test guarding Pipecat API drift).
