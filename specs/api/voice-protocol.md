---
type: API Contract
title: Voice WebSocket protocol
description: Wire format between the browser test-call client and the voice pipeline - binary PCM audio frames, JSON control messages, and the camera stills a video call captures on demand.
status: draft
tags: [api, voice, video, websocket]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Endpoint

`wss://<host>/api/voice/{call_id}?tenant=<tenant_id>` (or `ws://localhost:8000/...` locally). The call must have been created with `channel: "voice"` or `channel: "video"`. A video call is a voice call that can also carry camera stills; everything below applies to both, and the camera messages apply only to `video` ([ADR-0009](/decisions/adr-0009-video-channel.md)).

# Frames

| Direction | Frame type | Content |
|---|---|---|
| client → server | binary | Caller audio: PCM signed 16-bit little-endian, mono, **16,000 Hz**, 20 ms per frame (640 bytes) recommended |
| client → server | text (JSON) | `{"type":"hangup"}` |
| server → client | binary | Agent audio: PCM signed 16-bit little-endian, mono, **24,000 Hz**, arbitrary frame sizes |
| server → client | text (JSON) | `{"type":"ready"}` once the pipeline is running; the agent's spoken welcome follows immediately and the caller does not need to speak first ([VO-07](/architecture/voice-pipeline.md)) |
| server → client | text (JSON) | `{"type":"interrupt"}` — caller barged in; client MUST discard queued playback immediately |
| server → client | text (JSON) | `{"type":"end","reason":"end_call"\|"farewell"\|"handoff"\|"idle"\|"max_duration"\|"hangup"\|"error"}` ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md)) — sent after the closing speech has finished; client stops capture and releases the microphone; server closes after sending |

Transcripts, tool calls and status are **not** sent on this socket; the page subscribes to SSE topic `call:{id}` ([/api/events.md](/api/events.md)).

# Camera frames (video calls)

The camera stays in the browser. Nothing is captured or sent until the agent calls `look_at_camera`, which is the whole point of the design ([/architecture/visual-intake.md](/architecture/visual-intake.md)).

| Direction | Frame type | Content |
|---|---|---|
| client → server | text (JSON) | `{"type":"camera","state":"on"\|"off"}` — the caller turned the camera on or off. The server MUST treat `off` as the initial state and MUST NOT request a frame while the state is `off`. |
| server → client | text (JSON) | `{"type":"capture","request_id":"<hex>"}` — the agent is looking. Sent only on a video call whose camera state is `on`. |
| client → server | text (JSON) | `{"type":"frame","request_id":"<hex>","mime":"image/jpeg","data":"<base64>"}` — exactly one still for that `request_id` |
| client → server | text (JSON) | `{"type":"frame_error","request_id":"<hex>","reason":"no_camera"\|"capture_failed"\|"denied"}` |

* The server waits **2 s** for a `frame` or `frame_error`. On timeout the tool returns a declined status and a late `frame` for that `request_id` is discarded without being stored or described (VI-15).
* A `frame` whose `request_id` is unknown, already answered, or belongs to a `capture` the server did not send is discarded.
* The client downscales to **1280 px on the longest edge** and encodes JPEG at quality ≈ 0.7 before base64. The server applies the bounds again and does not trust these ([/architecture/media-storage.md](/architecture/media-storage.md)); a payload above 4 MB is refused undecoded.
* Frames travel as base64 in a text message, not on the binary channel, because binary already means PCM audio and a handful of stills per call does not justify a framing scheme to tell them apart.
* There is **no** message by which the server can enable the camera. The absence is the contract (VI-02).

# Close codes

| Code | Meaning |
|---|---|
| 1000 | normal (hangup or end) |
| 4400 | wrong channel (a text call id) |
| 4404 | unknown or ended call |
| 4500 | voice unavailable (e.g. `DEEPGRAM_API_KEY` missing) |

# Browser client requirements

* `getUserMedia({audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1}})`.
* Capture via an `AudioWorklet` that downsamples from the context rate to 16 kHz and posts 20 ms Int16 frames.
* Playback via a 24 kHz `AudioContext` scheduling `AudioBuffer`s back-to-back; on `interrupt`, stop all scheduled sources and reset the play head.
* A level meter for the mic and a "speaking" indicator for agent audio.
* Video calls: `getUserMedia({video: {width: {ideal: 1280}}})` only when the caller presses the camera control, never on connect. Keep the track local, draw the current video frame to a canvas on `capture`, and send one JPEG. Release the track when the camera is turned off or the call ends.
