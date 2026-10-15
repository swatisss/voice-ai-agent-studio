---
type: Change Proposal
title: CP-0017 Avatar ready before the welcome
description: "The avatar session starts loading as soon as the agent is in the call, while the caller's browser is still joining, and the welcome waits a few seconds for the face so the first sentence is already on camera."
status: stable
cp_state: implemented
tags: [video, avatar, simli, latency]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-15T00:00:00Z" }
---

# Why

After [CP-0016](cp-0016-avatar-video-without-lag.md) the delay no longer grows, but a local run still showed the face arriving only after the caller had spoken a sentence or two. The cause is ordering, by design in [CP-0014](cp-0014-simli-avatar-for-video-calls.md): the vendor session was opened only when the first participant joined, took a few seconds to connect, and the welcome was spoken straight away rather than wait for it (AV-09), so the first words were heard with no face and the face arrived late. The requester wants the avatar loaded while the application comes up, so it is there when the call starts.

# What changes

1. **The session starts loading when the agent is in the call (AV-07, reworded).** It opens as soon as the video pipeline has started, which is before the caller's browser has joined the room, so connecting to the vendor overlaps with the browser joining instead of following it. It still closes with the call, and a call nobody joins within 60 s is closed, so an unused session lives at most about a minute.
2. **The welcome waits for the face, briefly (AV-09 reworded, AV-15).** When the caller joins, the welcome is held until the avatar is ready, has failed, or 5 s have passed, whichever comes first, then spoken. Normally the session is already up by then and nothing waits. On a failure or a timeout the welcome is spoken directly, as before.

# Decisions taken while drafting

* **Cost trade-off accepted.** Opening at call start means a call abandoned before anyone joins costs up to about 60 s of vendor session where before it cost none. AV-07's old promise ("never opened when nobody joins") is replaced by a bound.
* **5 s, not longer.** A slow vendor delays the first word by at most 5 s on a call that would otherwise have had no face for its first sentences. Raise or lower the constant (`WELCOME_WAIT_S`) after real runs.
* **The vendor is unchanged.** Whether to replace Simli is a separate decision and not part of this change.

# Affected specs

Updated: [/architecture/avatar.md](/architecture/avatar.md) (hangs, lifetime and cost, AV-07, AV-09, AV-15), [/build/task-plan.md](/build/task-plan.md) (T35).

# Acceptance criteria

Reworded: **AV-07, AV-09** (IDs kept). New: **AV-15**.

# Tasks

1. **T35** - open the avatar when the pipeline starts, `wait_ready`, the welcome waits up to `WELCOME_WAIT_S`, tests - covers AV-07, AV-09, AV-15.

# Risks and rollout

* **Unverified against the real vendor.** Connect time is a vendor property; the tests use stubs. The first real run shows whether 5 s is enough.
* **Idle cost and the vendor's idle timeout.** A session left open while the caller joins is idle for a few seconds; Simli's own idle limit is far longer than that.
* **Rollback:** set `WELCOME_WAIT_S` to 0 to restore the old welcome; the earlier open stays harmless.

# Out of scope

Choosing a different avatar or speech-to-speech provider, lowering the vendor's own latency, a warm pool of sessions across calls.
