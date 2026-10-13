---
type: Decision Record
title: ADR-0011 Simli for the agent's talking face
description: "Render the agent as a live face in a video call with Simli's Pipecat service, publishing the result through the existing LiveKit room; no uploaded faces."
status: stable
tags: [decision, video, avatar, simli, livekit]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-13T00:00:00Z" }
---

# Context

A video call today shows the caller's own camera and nothing for the agent: the caller talks to a voice. The request is a proper video call, with the agent visible on the other side ([ADR-0009](/decisions/adr-0009-video-channel.md) chose LiveKit partly so this would stay reachable).

What was checked against the pinned toolchain (Pipecat 1.12.0) before choosing:

| Provider | How it fits our setup | Verdict |
|---|---|---|
| **Simli** | `SimliVideoService` is a pipeline processor. It takes the agent's TTS audio, returns lip-synced video frames (`OutputImageRawFrame`) and the matching audio, and our own `LiveKitTransport` publishes both with `video_out_enabled`. One room, one transport. Needs `pipecat-ai[simli]` (`simli-ai`, which brings `aiortc` and `av>=13`). | **Chosen** |
| HeyGen LiveAvatar | The Pipecat service opens its own avatar session and can be pointed at a custom LiveKit room. Two systems to keep in sync, and avatars are picked from the vendor's list. | Not chosen; revisit if Simli disappoints |
| Tavus, LemonSlice | Their Pipecat integrations require the Daily transport (`pipecat-ai[daily]`), which this product does not use. | Ruled out |
| Animated tile, no vendor | A browser-drawn tile with the persona's name and a speaking indicator. No cost, no key, not a face. | Kept, as the state a call is in when no avatar is available |

# Decision

Use Simli. The avatar is a processor placed after TTS in the video pipeline; the agent publishes one video track into the call's LiveKit room; the browser attaches it to a large agent tile with the caller's own camera as a small self-view ([/architecture/avatar.md](/architecture/avatar.md)).

Configuration is `SIMLI_API_KEY` and `SIMLI_FACE_ID`, both optional. Unset, a video call works exactly as it does today, with a placeholder tile for the agent. A single face serves every agent in this change; a face per persona is a later change.

**Uploading a photo to create an avatar is not part of this decision.** The SDK's documentation does not describe face creation (checked: the published README has no mention of upload or custom faces), so whether and how it works is unverified. It is also the part with a real ethical edge, because a face built from a photograph is a likeness of a person. If it is ever wanted it needs its own proposal covering consent and impersonation, not a line in this one.

# Consequences

* **A third vendor in the video path**, after LiveKit and the vision model provider. It receives the agent's synthesised speech, which can contain member information the agent reads back. That is the same class of exposure as the speech provider, and it joins the production gaps in [healthcare compliance](/product/healthcare-compliance.md): a BAA would be needed before real patients. Leaving `SIMLI_API_KEY` unset removes the exposure.
* **The audio the caller hears changes route** on an avatar call. Simli returns the speech in sync with the video, so the caller hears Simli's audio rather than the TTS output directly. If Simli fails the agent must still be heard, which makes pass-through on failure a requirement and not a nicety (AV-05).
* **Our server opens a WebRTC connection to Simli.** That is exactly the traffic ADR-0002 avoided for audio on Cloud Run. It works on a developer machine; whether it works on Cloud Run's UDP egress is **not verified** and is the first thing to check before deploying with the avatar on. Pipecat's service sets `enableSFU=True`, which routes through Simli's SFU and may help, but that is a hypothesis.
* **Extra dependencies**: `aiortc` and `av` are native packages. They install from wheels on the common platforms but add image size and are a plausible Windows install failure.
* **Extra CPU on the single instance**: video frames are decoded from Simli and re-encoded into the room, on the same 2 vCPU that runs VAD. Frame size and rate are therefore configuration, not constants.
* **Cost per call minute is unknown here.** It is a vendor price and was not checked. The session opens only when a participant has joined and closes with the call, so an idle room costs nothing (AV-07).
* **[IMG-01](/architecture/imagery.md) had to be narrowed.** It said no code path produces an image, which a video avatar plainly does. What it was protecting is that nothing manufactures *evidence*; the avatar renders the agent itself, never the caller's subject, and never enters the evidence record (AV-06). The wording now says that.
* **The media path is unverifiable offline**, as ADR-0009 already records for the room. Tests use a stub in place of the Simli service; the first run with a real key is the real test.
