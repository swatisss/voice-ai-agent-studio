---
type: Decision Record
title: ADR-0009 Video channel without a media server
description: "Carry the caller's camera on the existing call WebSocket as single stills captured on demand, instead of adding WebRTC or a LiveKit room."
status: draft
tags: [decision, video, vision, transport]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Context

Two use cases need the caller to show the agent something rather than describe it ([/product/use-cases.md](/product/use-cases.md), 8 and 9). The question is what carries the camera.

[ADR-0002](/decisions/adr-0002-voice-pipeline.md) already answered the audio version of this question: WebRTC needs UDP, which Cloud Run does not give us without a TURN server, so voice runs as raw PCM over a plain WebSocket. Video reopens it, because video is the thing WebRTC is actually for.

What changed the answer is a constraint from the feature itself. [Visual intake](/architecture/visual-intake.md) requires the agent to see a frame **only when it calls `look_at_camera`** — for cost, for grounding and for consent. A report of a damaged bed needs two or three looks, not a stream. So the transport question is not "how do we carry video" but "how do we get a handful of stills from the caller's camera to a vision model".

# Options

1. **LiveKit Cloud as a second transport.** Pipecat has a LiveKit transport with `video_in_enabled`, and LiveKit Cloud is the SFU, so Cloud Run's lack of UDP stops mattering. It is the option that also makes an avatar video track possible later. It costs: a hosted media service, room lifecycle, access tokens, agent dispatch, a second transport implementation inside the voice module, and a vendor in the call path for both demo and development.
2. **Pipecat with SmallWebRTC.** Still needs TURN on Cloud Run. ADR-0002 rejected this and nothing about it improved.
3. **Camera stills on the existing call socket, pushed continuously.** The browser sends a downscaled JPEG every second while the camera is on; the server keeps the latest and uses it when the agent looks. No new infrastructure. It uploads frames for the whole call whether or not the agent ever looks.
4. **Camera stills on the existing call socket, captured on demand.** The browser holds the camera locally and sends nothing. When the agent calls `look_at_camera`, the server asks for one frame and the browser answers with one JPEG. No new infrastructure, and no image leaves the browser until the agent asks.

# Decision

Option 4. A video call is a voice call on the same WebSocket, with three added control messages ([/api/voice-protocol.md](/api/voice-protocol.md)): the client says the camera is on, the server asks for a frame, the client sends one.

Option 1 is the right answer to a question we are not asking. It buys a live video track in both directions; we need a few stills in one direction, and we would pay for the track in vendor setup, a second transport in the module with the most volatile dependency, and a demo that stops working when a hosted room does.

Option 4 beats option 3 on the thing that matters most in a healthcare product: with on-demand capture, **nothing from the camera reaches the server unless the agent asked for it and said so out loud**. That is a far easier property to defend than a server that streams a ward to itself and promises to throw most of it away. It is also cheaper, and the frame is fresher — it is captured for the look rather than up to a second before it.

The cost of option 4 is one round trip inside the tool call (the caller is already waiting for the look) and a timeout path when the browser does not answer. Both are cheap, and the timeout is the same declined status the tool already has for a camera that is off.

Frames travel as base64 inside a JSON control message rather than as binary, because the socket's binary channel already means PCM audio and a handful of stills per call do not justify a framing scheme to disambiguate it.

# Consequences

* **No new infrastructure, no new vendor, no new key.** Video works on localhost and on Cloud Run for the same reason voice does, which is the property ADR-0002 was protecting.
* **ADR-0002 stands unamended.** Its reasoning is not contradicted; it is extended to the only video shape this product needs.
* **The voice module keeps one transport.** `FastAPIWebsocketTransport` and the Pipecat pipeline are untouched, so VO-06 keeps guarding the only construction path there is.
* **No standing frame buffer exists to bound or to leak.** The server holds one still between receiving it and storing it, and that is all.
* **An avatar video track is out of reach**, and deliberately so. Sending the agent's face back to the caller is the requirement that forces a media server, and it belongs to its own change proposal with its own ADR. Nothing here blocks that: `look_at_camera` and the evidence pipeline sit behind the module contract and do not know what carried the frame.
* **Telephony video is not addressed.** Neither was telephony audio ([/product/scope.md](/product/scope.md)).
* A caller on a browser that refuses `getUserMedia` for video, or who declines the permission, degrades to an ordinary voice call — the path [visual intake](/architecture/visual-intake.md) requires to work anyway (VI-14).
