---
type: Component Spec
title: Talking avatar
description: "How the agent appears as a live face in a video call: where the Simli service sits in the pipeline, what the caller sees and hears, what happens when it is unavailable or fails, and why its frames are never evidence."
status: stable
tags: [architecture, video, avatar, simli]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-13T00:00:00Z" }
---

# What this is for

A video call should look like a call with someone. The caller already sees themselves; this gives the agent a face on the other side, speaking in sync with what it says. The decision and the alternatives are in [ADR-0011](/decisions/adr-0011-avatar-simli.md).

It is presentation only. The brain, the tools, the escalation rules and the visual-intake flow ([/architecture/visual-intake.md](/architecture/visual-intake.md)) are unchanged, and a call with no avatar behaves exactly as a video call does today.

# Where it sits

The video pipeline gains one processor, between TTS (on the `realtime` brain, the OpenAI Realtime service, whose speech is the same `TTSAudioRawFrame`) and the transport output ([/architecture/voice-pipeline.md](/architecture/voice-pipeline.md)):

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
| `AVATAR_MAX_SESSIONS` | How many vendor sessions this process may hold at once (default 1). Keep it at or below the Simli plan's limit. A call over it is an ordinary video call with a placeholder tile (AV-11). |
| `AVATAR_VIDEO_SIZE`, `AVATAR_VIDEO_FPS` | The published track's size and frame rate, default 512 and 30: Simli's native size and rate as read from its SDK, so no frame is resized and the face is not choppy. Configuration because they cost CPU on the single instance; the first real run confirms them. Lowering the rate skips frames; it never adds delay (AV-13). |

An avatar is **available** when both Simli values are set and the SDK is installed. Anything less makes it unavailable; that is not an error. `POST /api/calls` reports it as `media.avatar`, true or false, and a video call is created either way.

The face is chosen from the vendor's stock faces. **A face built from an uploaded photograph is out of scope** ([ADR-0011](/decisions/adr-0011-avatar-simli.md)).

# Audio, interruption and speaking

* **Interruption works as it does for voice.** When the caller barges in, the interruption reaches the avatar, which drops what it had buffered, so the face stops speaking with the voice (AV-04, VO-03).
* The protected welcome, the silence clocks and the closing line behave as they do on a voice call. The added latency of the avatar is a risk to the closing line, which is allowed up to 10 s to finish before the call closes ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md), CE-06); if it proves too tight in practice that is a configuration change, not a redesign.

# Keeping the face in step

The face must stay in step with the voice for the whole call, however long it runs.

* **The transport shows the newest frame and never queues.** The avatar's output is published in "latest frame wins" mode: a frame replaces the one waiting and a publish loop sends whatever is newest at `AVATAR_VIDEO_FPS`. The other mode queues every frame and drains the queue at that rate, so a vendor rendering faster than the publish rate adds delay without limit. A slow moment skips frames and a stalled vendor freezes the picture; neither makes the face later (AV-13).
* **The vendor's video is read from the moment the session opens.** The stock service only starts reading after the first speech reaches it, which would leave the face absent until the caller's second turn and the proof of life in AV-10 waiting for a frame that cannot come. The stage starts the readers itself when it opens the session, so the idle face is up at once (AV-14).

# When it is unavailable or fails

An avatar must never make the agent harder to hear than no avatar would.

* **Unavailable** (not configured, or the SDK is absent): the call is an ordinary video call. The agent's voice is the TTS audio, the caller's UI shows a placeholder tile for the agent, and nothing is reported as an error.
* **Fails to start or fails mid-call**: the agent's speech is **passed through unchanged** so the caller still hears it, the call continues, the failure is logged, and the UI falls back to the placeholder tile with a notice. A failed avatar never ends a call and never silences the agent (AV-05).
* **Hangs**: a vendor that connects and then says nothing is a failure too, and without a limit it would be the worst one, because nothing raises. Opening the session is limited to 15 s and runs in the background, and **the welcome waits for it only briefly** (up to 5 s, AV-15): until the session is up the stage is transparent and the agent is heard directly, so a slow or hung vendor can delay the first word by at most that. Speech sent to the vendor must come back, lip-synced, within 5 s; if it does not, the stage fails over, and the speech it had swallowed is **delivered late rather than never** (AV-09).

* **Refused**: a vendor that refuses the session (a rate limit, too many concurrent sessions) does not raise; it drops the connection. The stage listens for the vendor's error event and waits up to 5 s after opening for the first video frame, so a refusal fails the stage **before** it has consumed a word of speech (AV-10). No frame and no refusal is trusted, not failed.
* **Over our own cap**: see `AVATAR_MAX_SESSIONS`; the call never contacts the vendor (AV-11).

# Lifetime and cost

The Simli session starts opening as soon as the agent's video pipeline has started, which is before the caller's browser has joined the room, so connecting to the vendor overlaps with the caller joining and the face is normally up by the time the welcome is due. It closes when the call ends, for any reason, within 5 s; if nobody joins within the 60 s the room waits ([/api/media-protocol.md](/api/media-protocol.md)) the call is closed, so a session nobody used lives about a minute at most (AV-07). When the caller joins, the welcome is held until the face is ready, has failed, or 5 s have passed (AV-15). The call's maximum duration bounds it. Shutting the API down closes every session still open (AV-12).

# What an avatar frame is not

* **Not evidence.** The frame tap and the evidence module see only the caller's inbound video. An avatar frame is outbound, is never stored, never pinned, and never sent to any model (AV-06, VI-03).
* **Not a likeness of anyone.** It is a stock face presenting the agent. It is labelled as an AI agent wherever it is shown ([/ui/visual-case.md](/ui/visual-case.md), UI-46), on top of the spoken disclosure every call opens with ([/product/healthcare-compliance.md](/product/healthcare-compliance.md), rules 2 and 13).
* **Not generated imagery in the sense [IMG-01](/architecture/imagery.md) forbids.** That rule exists so nothing can manufacture the evidence the product is there to check. The avatar renders the agent, never the caller's subject.

# Acceptance

- **AV-01** — Given `SIMLI_API_KEY` and `SIMLI_FACE_ID` set and the SDK installed, when `POST /api/calls` is called with `channel: "video"`, then `media.avatar` is `true`; and given either value unset or the SDK absent, then `media.avatar` is `false` and the call is still created as a video call with no `video_unavailable`.
- **AV-02** — Given an avatar-enabled video call, when its pipeline is built, then the avatar processor sits after TTS, or after the realtime service on the realtime brain, and before the transport output and `video_out_enabled` is on; and given an avatar-less video call, then the processor order and transport settings are exactly those of CP-0013.
- **AV-03** — Given an avatar-enabled call whose avatar service yields video frames and re-timed audio, when the agent speaks, then the transport output carries both, and the audio the caller receives is the avatar's, not the TTS output.
- **AV-04** — Given the agent is speaking through the avatar, when the caller interrupts, then the interruption reaches the avatar service and its buffered speech is dropped.
- **AV-05** — Given the avatar service raises on start or mid-call, when the agent next speaks, then its TTS audio reaches the transport output unchanged, the call stays active, and the failure is logged; and the call is never ended by the avatar failing.
- **AV-06** — Given an avatar-enabled call, when frames are produced, then none is written to the blob store, none becomes a `call_evidence` entry, and none is sent to any model; and the frame tap holds only the caller's inbound frames.
- **AV-07** — Given a `voice` or `text` call, then no avatar service is constructed; and given a video call, then the avatar session starts opening when the agent's pipeline starts (before any participant has joined), closes within 5 s of the call ending for any reason, and a call nobody joins within 60 s is closed, which closes the session.
- **AV-08** — Given any API response, log line or call event produced during an avatar call, then `SIMLI_API_KEY` appears in none of them.
- **AV-09** — Given a vendor session that never comes up, or that comes up and never hands speech back, when the time limit passes (15 s to open, 5 s for speech to return), then the stage fails over to pass-through, the call continues, and speech the vendor had swallowed is delivered to the caller late; and given the session is still opening when the welcome is due, then the welcome waits for it no longer than AV-15 allows and is then spoken directly.
- **AV-10** — Given a vendor that reports an error or limit after the connection opens, when the stage is still waiting for the first frame, then it fails before consuming any speech and the agent is heard directly; and given a session that shows no frame and reports no error, then it is trusted and becomes ready; and given the first frame arrives, then it is ready at once.
- **AV-11** — Given `AVATAR_MAX_SESSIONS` sessions already open in this process, when another video call's avatar is asked to open, then it never contacts the vendor, the agent is heard directly, and the slot is available again once an open session closes or fails.
- **AV-12** — Given avatar sessions open when the API shuts down, then every one is closed.
- **AV-13** — Given an avatar-enabled video call, when the vendor produces frames faster than they are published (a burst, or a vendor rate above `AVATAR_VIDEO_FPS`), then the next frame published is the newest one, the transport holds no backlog of frames, and the published frame rate defaults to the vendor's 30; so the delay between face and voice does not grow with the length of the call.
- **AV-14** — Given the real avatar stage whose session has just opened and no speech has reached it, then its video and audio readers are already running, a frame the vendor renders is pushed on, and that frame makes the stage ready at once (AV-10) without any speech having been sent.
- **AV-15** — Given an avatar-enabled call whose caller has joined, when the welcome is due, then it is not spoken until the avatar is ready, or has failed, or 5 s have passed, whichever is first; and given the avatar is already ready, then the welcome is spoken at once; and given the avatar fails or does not come up in time, then the welcome is spoken directly.
