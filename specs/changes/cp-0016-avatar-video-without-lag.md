---
type: Change Proposal
title: CP-0016 Avatar video without lag
description: "The agent's face stays in step with its voice for the whole call: the transport shows the newest frame instead of queueing every frame, the vendor's video is read from the moment the session opens, and the published frame rate matches the vendor's."
status: stable
cp_state: implemented
tags: [video, avatar, simli, livekit, latency, reliability]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# Why

The first local runs of the avatar showed two faults against [CP-0014](cp-0014-simli-avatar-for-video-calls.md): the face lagged the voice by more and more as the call went on, and often did not appear at all. LiveKit was ruled out: it only carries what the agent process publishes. Both faults are in the agent process, between Simli's output and the published track. Found by reading the pinned toolchain (Pipecat 1.12.0, `simli-ai` 2.0.3); not yet confirmed against a live Simli session.

1. **Delay that grows for the whole call.** Simli renders 512×512 at 30 fps. The agent ran its output with `video_out_is_live=True`, where Pipecat puts every frame in an unbounded queue and drains it at `AVATAR_VIDEO_FPS`, which defaulted to 25. Thirty in against 25 out adds five frames of delay per second, about 12 s after a minute, never recovering; the voice plays in real time, so the face falls further behind it. Even with the rates equal, any slow moment adds delay that is never dropped.
2. **The face does not appear.** Pipecat's `SimliVideoService` starts reading the vendor's video only after it has processed its first TTS audio frame (both readers wait on an event that frame sets). The pass-through guard ([AV-05](/architecture/avatar.md)) deliberately forwards speech untouched until the stage is ready, and the stage is ready once it has seen a first video frame ([AV-10](/architecture/avatar.md)). Each waits for the other: the welcome passes through, the 5 s proof-of-life wait runs out, and video starts only after the caller's next turn. The stage tests passed because their stub does not have the real service's gating.

# What changes

1. **The transport shows the newest frame and never queues (AV-13).** The avatar's output is published in "latest frame wins" mode: a new frame replaces the one waiting, a publish loop sends whatever is newest at the configured rate. Delay cannot accumulate however long the call runs; a slow moment skips frames, and a stalled vendor freezes the picture instead of drifting later.
2. **The vendor's video is read from the moment the session opens (AV-14).** The stage starts the readers itself when the session opens, without waiting for speech, so the idle face appears at once and the proof of life in AV-10 is real.
3. **`AVATAR_VIDEO_FPS` defaults to 30**, the vendor's rate, so the face is not choppy and `AVATAR_VIDEO_SIZE` 512 is its native size, so nothing is resized per frame.

# Decisions taken while drafting

* **Latest-frame-wins over a bounded queue.** A bounded queue still delays by its length and needs a drop policy of its own; replacing the waiting frame is the drop policy, with Pipecat's existing code path and no code of ours in the frame path.
* **The welcome still does not wait for the face (AV-09 unchanged).** Waiting up to a few seconds so the first sentence is also on camera was proposed and not taken; with AV-14 the face is usually up within about a second of joining, so it is likely moot. Revisit after a real run.

# Affected specs

Updated: [/architecture/avatar.md](/architecture/avatar.md) (configuration, a new "Keeping the face in step" section, AV-13, AV-14), [/build/task-plan.md](/build/task-plan.md) (T34).

# Acceptance criteria

New: **AV-13, AV-14**. No ID is changed or retired. AV-02's test is updated for the new transport settings; its criterion is unchanged.

# Tasks

1. **T34** - avatar output in latest-frame mode, readers started at open, `AVATAR_VIDEO_FPS` default 30, tests - covers AV-13, AV-14.

# Risks and rollout

* **Unverified against the real vendor.** Tests drive Pipecat's real output sender and the real Simli stage with a fake client. Whether Simli's idle video starts flowing straight after connect, and whether its audio reader pushes anything before speech, is read from the SDK and confirmed only by a real call. If the idle audio is not silent, the caller could hear it before the first word; the stage already drops silence and the first real call will show.
* **Frame skipping.** On a loaded machine the face may drop frames rather than fall behind. That is the intended trade.
* **Rollback:** set `video_out_is_live` back to true in `build_room` (not recommended: it brings the growing delay back) and `AVATAR_VIDEO_FPS` to 25.

# Out of scope

Waiting for the face before the welcome, lowering the vendor's own latency, hardware encoding, a face per persona.
