---
type: Component Spec
title: Talking avatar
description: "How the agent appears as a live face in a video call: where the Simli service sits in the pipeline, what the caller sees and hears, what happens when it is unavailable or fails, and why its frames are never evidence."
status: draft
tags: [architecture, video, avatar, simli]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-13T00:00:00Z" }
---

# What this is for

A video call should look like a call with someone. The caller already sees themselves; this gives the agent a face on the other side, speaking in sync with what it says. The decision and the alternatives are in [ADR-0011](/decisions/adr-0011-avatar-simli.md).

It is presentation only. The brain, the tools, the escalation rules and the visual-intake flow ([/architecture/visual-intake.md](/architecture/visual-intake.md)) are unchanged, and a call with no avatar behaves exactly as a video call does today.

# Where it sits

The video pipeline gains one processor, between TTS and the transport output ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md)):

```
... BrainProcessor ──▶ TTS ──▶ Simli avatar ──▶ LiveKit transport output
                                 │   ▲                    │
                  TTS audio ─────┘   └── video frames ────┤ agent video track
                                       synced audio ──────┘ agent audio track
```

* Simli receives the agent's TTS audio and returns **video frames and the same speech re-timed to match them**. The caller therefore hears Simli's audio on an avatar call, not the TTS output directly.
* The transport is configured with `video_out_enabled`. The agent publishes **one video track**, its face, into the call's room. It publishes no other video.
* Without an avatar the processor is simply not in the pipeline and `video_out_enabled` is off, so the pipeline is the one that exists today (AV-02).
* A `voice` or `text` call never constructs the service and never contacts Simli (AV-07).

Pipecat, and with it Simli's service, stays inside the voice module (MOD-04). Nothing outside it learns that an avatar exists; the one fact the rest of the product needs — "will this call have a face?" — is a boolean on the room port ([/api/media-protocol.md](/api/media-protocol.md)).

# Configuration

| Setting | Meaning |
|---|---|
| `SIMLI_API_KEY` | The vendor key. Never returned by any API and never logged (AV-08). |
| `SIMLI_FACE_ID` | Which stock face to render. One face serves every agent in this change. |
| `AVATAR_VIDEO_SIZE`, `AVATAR_VIDEO_FPS` | The published track's size and frame rate. Configuration because they cost CPU on the single instance and because the vendor's native size is unverified; the defaults are a starting point and the first real run confirms them. |

An avatar is **available** when both Simli values are set and the SDK is installed. Anything less makes it unavailable; that is not an error. `POST /api/calls` reports it as `media.avatar`, true or false, and a video call is created either way.

The face is chosen from the vendor's stock faces. **A face built from an uploaded photograph is out of scope** ([ADR-0011](/decisions/adr-0011-avatar-simli.md)).

# Audio, interruption and speaking

* **Interruption works as it does for voice.** When the caller barges in, the interruption reaches the avatar, which drops what it had buffered, so the face stops speaking with the voice (AV-04, VO-03).
* The protected welcome, the silence clocks and the closing line behave as they do on a voice call. The added latency of the avatar is a risk to the closing line, which is allowed up to 10 s to finish before the call closes ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-06); if it proves too tight in practice that is a configuration change, not a redesign.

# When it is unavailable or fails

An avatar must never make the agent harder to hear than no avatar would.

* **Unavailable** (not configured, or the SDK is absent): the call is an ordinary video call. The agent's voice is the TTS audio, the caller's UI shows a placeholder tile for the agent, and nothing is reported as an error.
* **Fails to start or fails mid-call**: the agent's speech is **passed through unchanged** so the caller still hears it, the call continues, the failure is logged, and the UI falls back to the placeholder tile with a notice. A failed avatar never ends a call and never silences the agent (AV-05).

# Lifetime and cost

The Simli session opens when the first participant joins the room and closes when the call ends, for any reason, within 5 s. It is never opened at call creation, and if nobody joins within the 60 s the room waits ([/api/media-protocol.md](/api/media-protocol.md)) it is never opened at all (AV-07). The call's maximum duration bounds it.

# What an avatar frame is not

* **Not evidence.** The frame tap and the evidence module see only the caller's inbound video. An avatar frame is outbound, is never stored, never pinned, and never sent to any model (AV-06, VI-03).
* **Not a likeness of anyone.** It is a stock face presenting the agent. It is labelled as an AI agent wherever it is shown ([/ui/visual-case.md](/ui/visual-case.md), UI-46), on top of the spoken disclosure every call opens with ([/product/healthcare-compliance.md](/product/healthcare-compliance.md), rules 2 and 13).
* **Not generated imagery in the sense [IMG-01](/architecture/imagery.md) forbids.** That rule exists so nothing can manufacture the evidence the product is there to check. The avatar renders the agent, never the caller's subject.

# Acceptance

- **AV-01** — Given `SIMLI_API_KEY` and `SIMLI_FACE_ID` set and the SDK installed, when `POST /api/calls` is called with `channel: "video"`, then `media.avatar` is `true`; and given either value unset or the SDK absent, then `media.avatar` is `false` and the call is still created as a video call with no `video_unavailable`.
- **AV-02** — Given an avatar-enabled video call, when its pipeline is built, then the avatar processor sits after TTS and before the transport output and `video_out_enabled` is on; and given an avatar-less video call, then the processor order and transport settings are exactly those of CP-0013.
- **AV-03** — Given an avatar-enabled call whose avatar service yields video frames and re-timed audio, when the agent speaks, then the transport output carries both, and the audio the caller receives is the avatar's, not the TTS output.
- **AV-04** — Given the agent is speaking through the avatar, when the caller interrupts, then the interruption reaches the avatar service and its buffered speech is dropped.
- **AV-05** — Given the avatar service raises on start or mid-call, when the agent next speaks, then its TTS audio reaches the transport output unchanged, the call stays active, and the failure is logged; and the call is never ended by the avatar failing.
- **AV-06** — Given an avatar-enabled call, when frames are produced, then none is written to the blob store, none becomes a `call_evidence` entry, and none is sent to any model; and the frame tap holds only the caller's inbound frames.
- **AV-07** — Given a `voice` or `text` call, then no avatar service is constructed; and given a video call, then the avatar session opens only after a participant has joined, closes within 5 s of the call ending for any reason, and is never opened when nobody joins within 60 s.
- **AV-08** — Given any API response, log line or call event produced during an avatar call, then `SIMLI_API_KEY` appears in none of them.
