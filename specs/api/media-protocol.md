---
type: API Contract
title: Media room protocol
description: "The LiveKit room contract for a video call: how the room and tokens are scoped, which tracks each side publishes, and how the call starts and ends."
status: draft
tags: [api, video, livekit, webrtc]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Where this applies

Only `channel: "video"` calls **on the `livekit` engine**. A video call on the `gemini_live` engine has no room and no token; it uses the WebSocket in [/api/live-protocol.md](/api/live-protocol.md) ([/architecture/live-session.md](/architecture/live-session.md)).

Only `channel: "video"` calls. A `channel: "voice"` call uses the WebSocket in [/api/voice-protocol.md](/api/voice-protocol.md) and is unaffected by anything here ([ADR-0009](/decisions/adr-0009-video-channel.md)).

# Room and tokens

`POST /api/calls` with `channel: "video"` creates the call and returns a `media` object ([/api/rest-api.md](/api/rest-api.md)):

```json
{"url": "wss://<project>.livekit.cloud", "room": "call-<call_id>", "token": "<jwt>", "identity": "caller"}
```

| Rule | Why |
|---|---|
| The room name is `call-<call_id>` and nothing else. | One room per call, derivable, and never reused across calls. |
| The caller's token grants `roomJoin`, `canPublish` and `canSubscribe` on **that room only**, with identity `caller`. | A token for one call cannot reach another call's room, in this tenant or any other (VI-13). |
| The token's TTL is the call's maximum duration plus five minutes. | It cannot be kept and replayed after the call it was minted for. |
| `canPublishData` is **not** granted, and no data messages are read. | The control surface is the REST API and SSE; a second one would be a second thing to secure. |
| The agent joins the same room server-side with identity `agent` and its own token. | The caller's token never carries agent rights. |

The API key and secret never leave the server. The browser receives only the minted token.

# Tracks

| Participant | Publishes | Subscribes to |
|---|---|---|
| `caller` (browser) | microphone audio; camera video **only after the caller turns it on** | the agent's audio |
| `agent` (server) | audio (Deepgram TTS output, or the avatar's re-timed audio on an avatar call); **one video track, its face, only on an avatar call** | the caller's audio and, when present, the caller's camera video |

The agent publishes a video track **only on an avatar call**, and that track is its own face rendered by the avatar service ([/architecture/avatar.md](/architecture/avatar.md), AV-03). On any other video call the agent publishes no video at all. `POST /api/calls` says which case a call is in with `media.avatar`, so the browser knows whether to expect an agent track or draw a placeholder ([/api/rest-api.md](/api/rest-api.md), AV-01).

**The camera is the caller's.** The agent MUST NOT be able to enable it: nothing in this protocol, the REST API or the tool surface publishes a camera track on the caller's behalf, and the absence is the contract (VI-02). The agent's own face track is a different thing and is never the caller's camera. The caller unpublishes the track to turn it off, and the agent's next look is declined.

# Lifecycle

1. `POST /api/calls` creates the call row, mints the token, and starts the agent pipeline as a background task. The agent joins the room and waits.
2. The browser connects with the token and publishes its microphone.
3. On the first participant joining, the agent speaks its welcome — the same protected welcome a voice call gets ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), VO-07, VO-08).
4. The caller may turn the camera on and off as often as they like. Each change is a track published or unpublished.
5. The call ends when the agent ends the session (`end_call`, `farewell`, `handoff`, `idle`, `max_duration`), when the caller disconnects (`hangup`), or when **no participant joins within 60 s** of the agent joining — which ends the call `hangup` rather than leaving a room and a pipeline running for nobody.
6. The agent disconnects and the room is left to expire.

Transcripts, tool calls, evidence and status are **not** sent over the room. The page subscribes to SSE topic `call:{id}` exactly as it does for a voice call ([/api/events.md](/api/events.md)).

# Frames

Inbound video is decoded by the transport and pushed into the pipeline frame by frame. A tap inside the voice module keeps the **most recent frame only**, replacing it as frames arrive and never queueing, and drops it from the pipeline so nothing downstream sees video. `look_at_camera` takes whatever is in that holder at the moment it runs ([/architecture/visual-intake.md](/architecture/visual-intake.md)).

A queue here would hand the model a stale frame and grow without bound, which is why the holder is one frame deep. No frame is encoded, stored or sent to a model unless a look asks for it (VI-03).

# Browser client requirements

* `livekit-client`. Connect with the returned `url`, `room` and `token`; enable the microphone on connect.
* Camera: `setCameraEnabled(true)` **only** when the caller presses the camera control, never on connect. `setCameraEnabled(false)` unpublishes it.
* Capture at 1280×720 or below. The server re-bounds anyway and does not trust the client ([/architecture/media-storage.md](/architecture/media-storage.md)).
* Attach the agent's audio track to an element for playback. When `media.avatar` is true, attach the agent's **video** track to the main tile as well, and show the caller's own camera as a small self-view without uploading anything extra ([/ui/visual-case.md](/ui/visual-case.md), UI-46).
* Disconnect on hang-up and release the devices.

# Unavailable

When `LIVEKIT_URL`, `LIVEKIT_API_KEY` or `LIVEKIT_API_SECRET` is unset, or no vision-capable model ref resolves, `POST /api/calls` creates the call as `channel: "voice"` and returns `video_unavailable` with a reason instead of `media` (VI-01). There is one degradation path for both causes.
