---
type: Change Proposal
title: CP-0014 A talking avatar for video calls
description: "Give the agent a live face in a video call using Simli, published through the existing LiveKit room, and make the call look like a call: the agent large, the caller's own camera small."
status: draft
cp_state: proposed
tags: [video, avatar, simli, livekit, ui]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-13T00:00:00Z" }
---

# Why

CP-0013 made video calls work, and the first real run showed the gap: the caller sees their own camera and a black or empty space where the other party should be. The request was "a proper video call with the agent" — someone to talk to, not a voice and a mirror.

The original idea in the design session was bigger: upload a photo, make an avatar of it, talk to it. This proposal deliberately takes the part that is both valuable and checkable, a stock face the agent speaks through, and leaves the photo part out for reasons given below.

# What changes

1. **The agent appears as a live face.** On an avatar-enabled video call the agent publishes one video track into the LiveKit room, rendered by Simli from the agent's own speech, lip-synced to what it says ([/architecture/avatar.md](/architecture/avatar.md), [ADR-0011](/decisions/adr-0011-avatar-simli.md)).
2. **The call looks like a call.** The agent's face fills the main tile, labelled with the persona's name and **AI agent**; the caller's own camera becomes a small self-view instead of a full-width strip above the transcript (UI-46, UI-39).
3. **It is optional and degrades quietly.** Two new settings, `SIMLI_API_KEY` and `SIMLI_FACE_ID`. Unset, or the SDK absent, and a video call is exactly what it is today with a placeholder tile for the agent (AV-01, UI-47). An avatar that fails mid-call never silences the agent: the speech passes through unchanged and the call carries on (AV-05).
4. **The caller hears the avatar's audio** on an avatar call, because the vendor returns the speech re-timed to its video. Interruption still stops the voice and the face together (AV-04).
5. **The Simli session is cheap to leave configured.** It opens only once someone has joined, closes within 5 s of the call ending, and is never opened for a voice or text call (AV-07).
6. **Avatar frames are never evidence.** They are outbound, never stored, never pinned, never shown to a model (AV-06). The frame tap and the evidence module still see only the caller's inbound video.
7. **[IMG-01](/architecture/imagery.md) is narrowed, not broken.** It said no code path produces an image; a video avatar does. What the rule protects is that nothing can manufacture *evidence*, and that still holds — the avatar renders the agent, never the caller's subject. The wording of IMG-01, [healthcare compliance](/product/healthcare-compliance.md) rule 11 and the imagery spec now say exactly that.
8. **A new compliance rule, 13:** the face is a stock AI presenter, labelled as an AI agent, and never a real person's likeness; and Simli receives the agent's synthesised speech, which can contain member information, so it joins the production gaps (a BAA would be needed) and leaving the key unset removes it.

# Decisions taken while drafting, for review

* **Simli, not HeyGen.** Chosen with the requester. Simli's service is a pipeline processor that our own `LiveKitTransport` publishes from, so it stays one room and one transport; HeyGen runs its own session, and Tavus and LemonSlice require the Daily transport this product does not use. The comparison is in [ADR-0011](/decisions/adr-0011-avatar-simli.md).
* **No uploaded faces.** Two independent reasons. It is **unverified** that the SDK supports it — its published documentation says nothing about creating faces. And it is the part with an ethical edge: a face built from a photograph is a likeness of a person, which raises consent and impersonation questions that deserve their own proposal rather than a clause in this one.
* **One face for every agent.** A face per persona is the natural next step (a persona is already a voice) but it touches the data model, the persona editor and the seeder. It is a follow-up, not folded in.
* **A gap closed in passing:** the `VideoRoom` port created in CP-0013 was never added to the port table in [modular structure](/architecture/modular-structure.md). It is added here, together with the one method this change gives it.

# Affected specs

New:

* [/architecture/avatar.md](/architecture/avatar.md) - the pipeline position, configuration, degradation, lifetime, and what an avatar frame is not; AV-01…AV-08
* [/decisions/adr-0011-avatar-simli.md](/decisions/adr-0011-avatar-simli.md) - Simli chosen, the alternatives checked against the pinned Pipecat, and the consequences including the unverified Cloud Run egress

Updated:

* [/api/media-protocol.md](/api/media-protocol.md) - the agent may publish one video track (its face); `media.avatar`; browser attaches it
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) - the avatar processor and `video_out_enabled` on video calls
* [/architecture/visual-intake.md](/architecture/visual-intake.md) - VI-02 reworded: the agent still cannot publish the caller's camera, but it now has a video track of its own
* [/architecture/imagery.md](/architecture/imagery.md) - IMG-01 and the "no image generated" section narrowed to evidence
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rule 11 narrowed, new rule 13, a new production gap for the avatar vendor
* [/product/scope.md](/product/scope.md) - the talking avatar moves from out of scope to in, with uploaded faces explicitly out
* [/decisions/adr-0009-video-channel.md](/decisions/adr-0009-video-channel.md) - amendment: the avatar it deferred now exists
* [/api/rest-api.md](/api/rest-api.md) - `media.avatar` on the `POST /api/calls` response
* [/architecture/modular-structure.md](/architecture/modular-structure.md) - the missing `VideoRoom` port row, with `avatar_enabled()`
* [/architecture/deployment.md](/architecture/deployment.md), [/architecture/tech-stack.md](/architecture/tech-stack.md), [/build/runbook-gcp.md](/build/runbook-gcp.md), [/build/runbook-local.md](/build/runbook-local.md) - the two Simli secrets, the `simli` extra
* [/ui/visual-case.md](/ui/visual-case.md) - the agent tile, the self-view, the placeholder; UI-39 reworded, UI-46…UI-48
* [/ui/test-call.md](/ui/test-call.md) - a pointer to the new layout
* [/process/conventions.md](/process/conventions.md) - register the `AV` prefix
* [/build/task-plan.md](/build/task-plan.md) - T29…T32

# Acceptance criteria

New: **AV-01…AV-08** ([avatar](/architecture/avatar.md)) and **UI-46…UI-48** ([visual case](/ui/visual-case.md)).

Reworded, with the same intent: **VI-02** (the agent publishes no track carrying the *caller's* camera, rather than no track at all), **IMG-01** (no code path produces an image *of the caller's subject or as evidence*), and **UI-39** (a self-view, no longer a full-width preview). No ID is retired.

Everything in AV is testable offline with a stub standing in for the Simli service, including the failure pass-through (AV-05), which is the one that matters most. UI-46…UI-48 are hand-checked; they need a browser and, for UI-46, a real Simli key.

# Tasks

1. Spec edits above, the `AV` prefix and the [log](/log.md) entry (done in this CP).
2. **T29** — `simli` extra in `pyproject.toml`; `SIMLI_API_KEY`, `SIMLI_FACE_ID`, `AVATAR_VIDEO_SIZE`, `AVATAR_VIDEO_FPS` in settings and `.env.example`; `VideoRoom.avatar_enabled()`; `media.avatar` on the call response — covers AV-01.
3. **T30** — the avatar processor in `build_room()`, `video_out_enabled` only when enabled, interruption through to the service, and the **pass-through-on-failure wrapper** — covers AV-02, AV-03, AV-04, AV-05. Update `test_the_agent_publishes_no_video_track`, which asserts `video_out_enabled=False` and is correct today and wrong afterwards.
4. **T31** — session lifetime (open on first participant, close within 5 s of the end, never when nobody joins), voice and text calls never construct it, the key never leaves the process — covers AV-06, AV-07, AV-08.
5. **T32** — web: subscribe to the agent's video track in `lib/room.ts`, the agent tile with name and **AI agent** label, the caller's self-view, the placeholder tile and its notice — covers UI-46, UI-47, UI-48, UI-39.
6. Close: specs to `status: stable`, this CP to `implemented`, [log](/log.md) entry, `scripts/acceptance-baseline.txt` for UI-46…UI-48.

# Risks and rollout

* **The real thing cannot be tested here.** No automated test can reach Simli. The processor is exercised through a stub that yields frames, fails on demand and records interruptions; whether the real service renders a good face, in sync, at an acceptable size, is learned only on the first run with a real key. This is the weakest point of the change, as the room itself already was in CP-0013.
* **Our server opens a WebRTC connection to Simli.** Fine on a developer machine. Whether it works from Cloud Run's UDP egress is **unverified** and is exactly the constraint [ADR-0002](/decisions/adr-0002-voice-pipeline.md) was written around. Do not deploy with the avatar on until it has been tried.
* **Latency.** The avatar adds delay between the agent finishing its sentence and the caller hearing it, and the closing line has only 10 s to finish (CE-06). Expect to tune it.
* **CPU.** Decoding Simli's video and re-encoding it into the room is new steady-state load on the same 2 vCPU as VAD. Size and rate are configuration for that reason; the defaults are a guess until measured.
* **Cost.** A new per-minute vendor charge, not checked here. Bounded by opening the session only after someone joins and closing it with the call.
* **PHI to a third party.** The agent's speech goes to Simli and can include member details. Removed by leaving the key unset; recorded as a production gap.
* **Native dependencies.** `aiortc` and `av` are new native packages; Windows is the likeliest place for an install to fail.
* **Rollback.** Leave the two settings unset. Nothing else changes, because the processor is absent from the pipeline and `video_out_enabled` is off.

# Out of scope

* **Creating a face from an uploaded photograph.** Unverified in the SDK, and a likeness-of-a-person question that needs consent and impersonation rules of its own. A separate proposal if ever wanted.
* **A face per persona or per agent.** One configured face for now; the data-model and persona-editor changes it needs are a follow-up.
* **Lip-sync or expression control of our own.** The vendor owns the rendering.
* **Avatar on voice or text calls.** Video calls only.
* **Telephony video.** As for CP-0013.
* **HeyGen, Tavus and LemonSlice.** Considered and set aside in [ADR-0011](/decisions/adr-0011-avatar-simli.md).
