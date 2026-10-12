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

1. **LiveKit Cloud as a second transport.** Verified against the pinned toolchain rather than assumed, because this is the option that looks best on paper:
   * The transport ships in the pinned Pipecat 1.12.0 (`pipecat/transports/livekit/`) with `video_in_enabled`, `video_out_enabled` and `write_video_frame`; the `livekit` extra (`livekit>=1.0.13,<2`, `livekit-api`, `pyjwt`, `tenacity`) installs cleanly on Linux/CPython 3.12 and mints room tokens. It carries a 28 MB native `liblivekit_ffi.so`.
   * **Cloud Run reachability is not the obstacle ADR-0002 implies.** LiveKit Cloud provides managed TURN over TLS on 443 (`*.turn.livekit.cloud`) and tries ICE/UDP → TURN/UDP → ICE/TCP → TURN/TLS, so we never run a TURN server and the worst case looks like ordinary HTTPS. Cloud Run's documented egress is layer-4 TCP **and** UDP.
   * It is the only option that makes an avatar video track possible, and Pipecat 1.12.0 already has a HeyGen transport that joins a LiveKit room.
   * The free *Build* tier (roughly 5,000 WebRTC minutes, 50 GB, ~100 concurrent connections) would cover a demo.

   What rules it out **for this feature** is one specific gap: Pipecat 1.12.0 is the current release and its LiveKit transport has **no on-demand frame fetch**. `video_in_enabled` starts a task that pushes *every* inbound frame into the pipeline as a `UserImageRawFrame`. Per-source, request-only delivery (`video_in_sources`, `on_request_only`) exists only in unreleased work upstream. So on today's release LiveKit forces continuous video — browser → LiveKit Cloud's SFU → our process, decoded and colour-converted frame by frame on the same 2 vCPU that runs Silero VAD, with almost all of it discarded.

   It also costs a hosted media service, room lifecycle, access tokens, two new secrets, and a second transport implementation inside the voice module — the module with the most volatile third-party blast radius ([/architecture/modular-structure.md](/architecture/modular-structure.md), MOD-04).
2. **Pipecat with SmallWebRTC.** Still needs TURN on Cloud Run. ADR-0002 rejected this and nothing about it improved.
3. **Camera stills on the existing call socket, pushed continuously.** The browser sends a downscaled JPEG every second while the camera is on; the server keeps the latest and uses it when the agent looks. No new infrastructure. It uploads frames for the whole call whether or not the agent ever looks.
4. **Camera stills on the existing call socket, captured on demand.** The browser holds the camera locally and sends nothing. When the agent calls `look_at_camera`, the server asks for one frame and the browser answers with one JPEG. No new infrastructure, and no image leaves the browser until the agent asks.

# Decision

Option 4. A video call is a voice call on the same WebSocket, with three added control messages ([/api/voice-protocol.md](/api/voice-protocol.md)): the client says the camera is on, the server asks for a frame, the client sends one.

Option 1 is possible and was checked properly; it is the right answer to a question we are not asking. It buys a live video track in both directions, and we need a few stills in one direction. On the current Pipecat release it cannot give us those stills on demand at all, so choosing it would mean streaming a hospital ward continuously to a third-party SFU in order to use two frames of it — and then writing a compliance rule that says so.

Option 4 beats both 1 and 3 on the thing that matters most in a healthcare product: with on-demand capture, **nothing from the camera leaves the caller's machine unless the agent asked for it and said so out loud**. That is a far easier property to defend than a server that streams a ward to itself, or to a vendor, and promises to throw most of it away. It is what rules 9 and 12 of [healthcare compliance](/product/healthcare-compliance.md) and VI-03 rest on, and no other option here can state it. Option 4 is also cheaper, needs no vendor, and the frame is fresher — captured *for* the look rather than up to a second before it.

The cost of option 4 is one round trip inside the tool call (the caller is already waiting for the look) and a timeout path when the browser does not answer. Both are cheap, and the timeout is the same declined status the tool already has for a camera that is off.

Frames travel as base64 inside a JSON control message rather than as binary, because the socket's binary channel already means PCM audio and a handful of stills per call do not justify a framing scheme to disambiguate it.

# Consequences

* **No new infrastructure, no new vendor, no new key.** Video works on localhost and on Cloud Run for the same reason voice does, which is the property ADR-0002 was protecting.
* **ADR-0002 stands unamended.** Its reasoning is not contradicted; it is extended to the only video shape this product needs.
* **The voice module keeps one transport.** `FastAPIWebsocketTransport` and the Pipecat pipeline are untouched, so VO-06 keeps guarding the only construction path there is.
* **No standing frame buffer exists to bound or to leak.** The server holds one still between receiving it and storing it, and that is all.
* **An avatar video track is out of reach**, and deliberately so. Sending the agent's face back to the caller is the requirement that forces a media server, and it belongs to its own change proposal with its own ADR. Nothing here blocks that: `look_at_camera` and the evidence pipeline sit behind the module contract and do not know what carried the frame. When that CP comes, **LiveKit Cloud is the transport to reach for and HeyGen the avatar provider** — the combination is already supported by the pinned Pipecat, and this ADR should be read as deferring it, not as an argument against it.
* **Revisit this decision when Pipecat ships request-only video input.** Per-source, on-demand frame delivery over LiveKit removes the one objection that actually decided this ADR. At that point LiveKit would offer everything option 4 offers plus a path to the avatar, and the remaining cost is a vendor and a second transport — a trade worth re-running rather than inheriting.
* **Telephony video is not addressed.** Neither was telephony audio ([/product/scope.md](/product/scope.md)).
* A caller on a browser that refuses `getUserMedia` for video, or who declines the permission, degrades to an ordinary voice call — the path [visual intake](/architecture/visual-intake.md) requires to work anyway (VI-14).
