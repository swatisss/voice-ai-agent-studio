---
type: API Contract
title: Voice WebSocket protocol
description: Wire format between the browser test-call client and the voice pipeline - binary PCM audio frames and JSON control messages.
status: stable
tags: [api, voice, websocket]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Endpoint

`wss://<host>/api/voice/{call_id}?tenant=<tenant_id>` (or `ws://localhost:8000/...` locally). The call must have been created with `channel: "voice"`.

# Frames

| Direction | Frame type | Content |
|---|---|---|
| client → server | binary | Caller audio: PCM signed 16-bit little-endian, mono, **16,000 Hz**, 20 ms per frame (640 bytes) recommended |
| client → server | text (JSON) | `{"type":"hangup"}` |
| server → client | binary | Agent audio: PCM signed 16-bit little-endian, mono, **24,000 Hz**, arbitrary frame sizes |
| server → client | text (JSON) | `{"type":"ready"}` once the pipeline is running; the agent's spoken welcome follows immediately and the caller does not need to speak first ([VO-07](/architecture/voice-pipeline.md)) |
| server → client | text (JSON) | `{"type":"interrupt"}` — caller barged in; client MUST discard queued playback immediately |
| server → client | text (JSON) | `{"type":"end","reason":"end_call"\|"farewell"\|"handoff"\|"idle"\|"max_duration"\|"hangup"\|"error"}` ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md)) — sent after the closing speech has finished; client stops capture and releases the microphone; server closes after sending |

The protocol is the same for both voice pipelines ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)): the browser cannot tell which one answered. Phone calls use a different socket, `WS /api/telephony/twilio/stream/{call_id}`, with Twilio's own JSON events ([/architecture/telephony.md](/architecture/telephony.md)).

Transcripts, tool calls and status are **not** sent on this socket; the page subscribes to SSE topic `call:{id}` ([/api/events.md](/api/events.md)).

# Close codes

| Code | Meaning |
|---|---|
| 1000 | normal (hangup or end) |
| 4400 | wrong channel (text call id) |
| 4404 | unknown or ended call |
| 4500 | voice unavailable (e.g. `DEEPGRAM_API_KEY` missing for a cascade agent, `OPENAI_API_KEY` missing for a realtime agent) |

# Browser client requirements

* `getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}})`.
* Capture via an `AudioWorklet` that downsamples from the context rate to 16 kHz and posts 20 ms Int16 frames.
* Playback via a 24 kHz `AudioContext` scheduling `AudioBuffer`s back-to-back; on `interrupt`, stop all scheduled sources and reset the play head.
* A level meter for the mic and a "speaking" indicator for agent audio.
