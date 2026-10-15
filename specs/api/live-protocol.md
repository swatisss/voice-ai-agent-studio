---
type: API Contract
title: Live session protocol
description: "The WebSocket between the browser and the API for a video call on the Live engine: what the browser sends, what the server sends, how the avatar stream and the camera answer travel, and the close codes."
status: draft
tags: [api, video, websocket, avatar, gemini, live]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# Where this applies

Only a `channel: "video"` call whose `media.engine` is `gemini_live` ([/architecture/live-session.md](/architecture/live-session.md), GL-01). A video call on the `livekit` engine uses the room in [/api/media-protocol.md](/api/media-protocol.md); a voice call uses [/api/voice-protocol.md](/api/voice-protocol.md). Transcripts, tool calls, evidence and status are **not** sent on this socket: the page subscribes to SSE topic `call:{id}` as it does for every call ([/api/events.md](/api/events.md)).

# Starting

`POST /api/calls` with `channel: "video"` returns, for this engine:

```json
{"call_id": "...", "greeting": "...", "media": {"engine": "gemini_live", "ws_path": "/api/live/<call_id>", "avatar": true}}
```

`avatar` is whether a face is expected; it can be corrected by a `notice` once the session is open. The browser then opens `ws_path` on the API's own origin. No third-party URL, token or key is ever sent to the browser. The LiveKit engine's `media` carries `engine: "livekit"` beside its existing fields.

# Browser to server

| Message | Meaning |
|---|---|
| binary | Microphone audio, PCM16 little-endian, 16 kHz mono, in chunks of 20–100 ms |
| `{"type":"frame","id":"<request id>","data":"<base64 JPEG>"}` | The answer to one `frame_request`: a single still, at most 1280 px on its long side. The server re-bounds it anyway ([/architecture/media-storage.md](/architecture/media-storage.md)) |
| `{"type":"frame","id":"<request id>","declined":true}` | The camera is off or the capture failed |
| `{"type":"avatar","enabled":false}` | The browser cannot play the stream; the server reopens the session audio-only (GL-05) |
| `{"type":"hangup"}` | The caller ended the call |

The microphone is the browser's to open; the camera is never opened by anything but the caller's own control ([/ui/visual-case.md](/ui/visual-case.md)).

# Server to browser

| Message | Meaning |
|---|---|
| `{"type":"ready"}` | The session is open; the welcome follows |
| `{"type":"avatar_video","data":"<base64>"}` | One chunk of the fragmented MP4 that carries the face and its voice together, forwarded as received. The first chunks are the initialisation segment |
| `{"type":"audio","data":"<base64>","rate":24000}` | Voice only, PCM16 mono. Sent only when the session is audio-only |
| `{"type":"interrupt"}` | The caller interrupted: drop everything buffered and reset the player |
| `{"type":"frame_request","id":"<request id>"}` | The agent wants to look; answer with one `frame` |
| `{"type":"notice","avatar":false,"reason":"..."}` | The call continues without a face |
| `{"type":"end","reason":"<end reason>","detail":"..."}` | The call is over. `reason` is a call end reason ([/data/data-model.md](/data/data-model.md)); `detail` is shown for `error` |

No other message is sent. A message of an unknown type, or malformed JSON, from the browser is ignored and logged; it never closes the socket.

# Close codes

| Code | Reason |
|---|---|
| 4404 | unknown, ended or another tenant's `call_id` |
| 4400 | the call is not a Live-engine video call |
| 4500 | `live_unavailable`: the session could not be opened. An `end` with `reason: "error"` is sent first |

# Not offered on this engine

`PATCH /api/calls/{id}/live` with `persona_id` or `turn_detection` answers 409 `unsupported_on_engine` for a Live call: turn-taking and the voice belong to the session. The Test call page hides those controls for it ([/ui/test-call.md](/ui/test-call.md)).

# Acceptance

- **LV-01** — Given a socket opened with an unknown, ended or another tenant's call id, then it closes with 4404; given a call that is not a Live-engine video call, 4400; given the session cannot be opened, an `end` with reason `error` is sent and the socket closes with 4500.
- **LV-02** — Given the browser sends microphone chunks, a `frame` answer, an `avatar` message and `hangup`, then each is acted on as specified, and a `hangup` ends the call with reason `hangup`.
- **LV-03** — Given a Live call, then the server sends only the message types in the table above, each with its fields, and `avatar_video` data is exactly what the session produced.
- **LV-04** — Given a `frame` answer larger than the bound, or not a JPEG, or for an id that was never requested, or arriving after the 3 s window, then it is dropped and the look is declined; the socket stays open.
- **LV-05** — Given `POST /api/calls` on the Live engine, then `media` is `{engine, ws_path, avatar}` with no URL, token or key; and given the LiveKit engine, then `media` is unchanged apart from `engine: "livekit"`.
- **LV-06** — Given `PATCH /api/calls/{id}/live` with a persona or turn-detection change on a Live call, then the response is 409 `unsupported_on_engine` and nothing changes.
