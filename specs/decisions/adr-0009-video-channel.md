---
type: Decision Record
title: ADR-0009 LiveKit Cloud for the video channel
description: "Carry video calls on a LiveKit Cloud room with Pipecat's LiveKit transport, keeping the plain WebSocket for voice-only calls."
status: stable
tags: [decision, video, vision, transport, livekit]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Context

Two use cases need the caller to show the agent something rather than describe it ([/product/use-cases.md](/product/use-cases.md), 8 and 9). The question is what carries the camera.

[ADR-0002](/decisions/adr-0002-voice-pipeline.md) answered the audio version: WebRTC needs UDP, which Cloud Run does not give us without a TURN server, so voice runs as raw PCM over a plain WebSocket. Video reopens it, because video is what WebRTC is for.

That ADR's objection turns out not to apply to a managed SFU, and this was checked rather than assumed:

* The transport ships in the pinned **Pipecat 1.12.0** (`pipecat/transports/livekit/`) with `video_in_enabled`, `video_out_enabled` and `write_video_frame`. The `livekit` extra (`livekit>=1.0.13,<2`, `livekit-api`, `pyjwt`, `tenacity`) installs on Linux/CPython 3.12 and mints room tokens. It carries a 28 MB native `liblivekit_ffi.so`.
* **LiveKit Cloud provides managed TURN over TLS on 443** (`*.turn.livekit.cloud`) and negotiates ICE/UDP → TURN/UDP → ICE/TCP → TURN/TLS. We never run a TURN server, and the worst case looks like ordinary HTTPS. Cloud Run's documented egress is layer-4 TCP **and** UDP.
* The free *Build* tier (about 5,000 WebRTC minutes, 50 GB, ~100 concurrent connections) covers demo and development use.

# Options

1. **LiveKit Cloud for video calls, WebSocket kept for voice.** Two transports behind one pipeline.
2. **LiveKit Cloud for every call**, retiring the WebSocket transport and the hand-written PCM client.
3. **Pipecat with SmallWebRTC.** Still needs TURN on Cloud Run. ADR-0002 rejected it and nothing changed.
4. **Camera stills on the existing call socket, captured on demand.** The browser holds the camera and sends one JPEG when the agent asks. No new infrastructure, and nothing leaves the browser unless the agent asked.

# Decision

Option 1. `channel: "video"` runs on a LiveKit Cloud room; `channel: "voice"` keeps the WebSocket exactly as it is. The Pipecat pipeline — Silero VAD, Deepgram STT, our `TurnAggregator` and `BrainProcessor`, Deepgram TTS — is shared, and only the transport at each end differs ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), [/api/media-protocol.md](/api/media-protocol.md)).

Option 2 was rejected because it would put the working voice path, and VO-01…VO-08 with it, behind a vendor for no gain. Voice-only calls need nothing LiveKit offers.

**Option 4 is the honest cost of this decision and deserves recording.** It needs no vendor, no secret and no second transport, and it can state something option 1 cannot: *nothing from the camera leaves the caller's machine unless the agent asked for it and said so out loud.* That is given up here, because Pipecat 1.12.0's LiveKit transport has no on-demand frame fetch — `video_in_enabled` starts a task that pushes **every** inbound frame into the pipeline, and per-source request-only delivery exists only in unreleased upstream work. So while the camera is on, video streams continuously from the browser to LiveKit Cloud's SFU and down into our process, and we discard nearly all of it.

What is bought for that:

* **A video track in both directions**, which is the only way the talking avatar this product wants becomes reachable. Pipecat 1.12.0 already carries a HeyGen transport that joins a LiveKit room, so the avatar is a later change proposal rather than a rewrite.
* **Real WebRTC media**: adaptive bitrate, packet loss recovery, and camera handling on mobile browsers that a hand-rolled JPEG path would have to reinvent badly.
* **A managed TURN/TLS path**, so a caller behind a restrictive corporate or hospital network connects where raw WebRTC would fail.

Because the continuous stream cannot be avoided, the rules it affects are rewritten rather than quietly left standing: rules 9 and 12 of [healthcare compliance](/product/healthcare-compliance.md) now say plainly that camera media transits a third-party SFU while the camera is on, and VI-03 asserts what is still true — that **no frame reaches a model** unless the agent called `look_at_camera`, and that the buffer holds one frame however many arrive.

# Consequences

* **A vendor is now in the call path for video.** `LIVEKIT_URL`, `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` join the deployment's secrets ([/architecture/deployment.md](/architecture/deployment.md)). Unset means video is unavailable and the call is created as `voice` (VI-01) — the same degradation the `vision` role already needed, so there is one path, not two.
* **The voice module gains a second transport**, in the module with the most volatile third-party blast radius ([/architecture/modular-structure.md](/architecture/modular-structure.md), MOD-04). Pipecat confinement still holds: LiveKit is reached only through Pipecat's transport inside `modules/voice/`, and `evidence` gets its frame through the `FrameSource` port, so nothing outside the voice module learns what carried it.
* **Image size grows by ~28 MB** for the native LiveKit FFI library.
* **The media path cannot be verified offline.** Tests construct the LiveKit pipeline with dummy credentials and assert no network call, exactly as VO-06 already does for the WebSocket pipeline. A real room needs credentials and a browser, so VI-01 and VI-14's live halves are hand-checked and listed in `scripts/acceptance-baseline.txt`.
* **CPU cost on the single instance.** Every inbound frame is decoded and colour-converted on the same 2 vCPU that runs Silero VAD. The frame tap keeps one frame and drops the rest immediately, and the per-call capture cap still bounds what is stored and described ([/architecture/media-storage.md](/architecture/media-storage.md)).
* **ADR-0002 is amended, not overturned.** Its decision stands for voice; its reasoning about WebRTC on Cloud Run is narrowed to the case where we would have had to run TURN ourselves.
* **ADR-0005 is unaffected.** One instance, session affinity, process-local live-call state. A LiveKit room does not make the service horizontally scalable; the room is shared state held by the vendor, while the pipeline and the frame buffer are still process-local.
* **Telephony video is not addressed.** Neither was telephony audio ([/product/scope.md](/product/scope.md)).
* A caller who never enables the camera, or whose browser refuses it, degrades to an ordinary voice call on the same room (VI-14).

# Amendment (CP-0014)

The avatar this decision deferred now exists: [ADR-0011](/decisions/adr-0011-avatar-simli.md) renders the agent's face with Simli and publishes it through this same room, which is what LiveKit was chosen to make possible. Two statements above are therefore narrowed rather than wrong: the agent no longer publishes *no* video on every video call (it publishes its own face on an avatar call), and the pipeline's `video_out_enabled` is no longer always off. The camera is still the caller's and the agent still cannot publish it for them (VI-02).
