---
type: Change Proposal
title: CP-0013 Visual evidence intake
description: "Add a video channel and a look-on-demand vision tool, so a caller can show the agent a damaged asset or insured item and the call ends with reviewable evidence, a case and a ticket."
status: draft
cp_state: proposed
tags: [video, vision, evidence, cases, storage]
generated: { by: "claude-code/claude-opus-5", at: "2026-10-12T00:00:00Z" }
---

# Why

Two kinds of call in this domain are badly served by audio alone, and both end the same way today: the agent takes a description, escalates or files something thin, and a human calls back to ask for a photograph.

1. **A ward asset is damaged.** A nurse reports a bed rail that will not latch. What a maintenance team needs — which rail, how bent, whether it is safe to use tonight — is exactly what does not survive a spoken description, so the ticket arrives under-specified and someone walks to the ward to look.
2. **An insured item is damaged.** A member describes a dented car door. The claim cannot progress until photographs arrive by email, which is a second contact, a second queue, and the most common place a claim stalls.

Both are the same mechanism: let the caller show the agent, and let the agent write down what it could actually see.

The reason this is worth specifying carefully rather than bolting on is the failure mode. An agent with a camera and no discipline agrees with the caller — "yes, I can see the big crack" — because agreeing is the path of least resistance for a language model, and the result is a case that collapses the first time a human looks at the frame. In a healthcare and insurance product that is the failure that matters, and it is worse than having no camera at all. So the load-bearing part of this proposal is not the video. It is a confidence field the model is **required** to withhold, a pinned record of the looks that confirmed nothing, and a narrative drafted from observations rather than from what the caller said.

Nothing in the specs covers any of this today: there is no video channel, no vision role, no image anywhere in the product, and no byte storage of any kind.

# What changes

1. **A third live channel.** `POST /api/calls` accepts `channel: "video"`. A video call *is* a voice call — same brain, same tools, same ending rules — that additionally has a camera the agent may ask to look at. A caller who never enables the camera gets exactly the voice call they would have had (VI-14).
2. **No media server, no WebRTC.** The camera stays in the browser and nothing is captured until the agent asks. A look is one control message down the existing call WebSocket and one JPEG back ([ADR-0009](/decisions/adr-0009-video-channel.md)). No new vendor, no new key, works on localhost and Cloud Run for the same reason voice does.
3. **Looking is an act.** A new built-in tool, `look_at_camera`, beside `search_knowledge`, `escalate_to_human` and `end_call`. It is offered only on a video call, and the agent **cannot turn the camera on** — there is no API, protocol message or tool that does, and the absence is the contract (VI-02).
4. **An observation that may withhold confidence.** One look produces one validated observation: what is visible, the things it can point at, a `confidence` of `confirmed` / `unclear` / `not_confirmed`, a `safety_flag`, and — when confidence is withheld — the better look it needs. The agent asks for that look instead of guessing, and `not_confirmed` is reported as what it does see, never as an accusation.
5. **Evidence is pinned, including the looks that confirmed nothing.** Append-only per call, each entry holding the frame, the observation and the caller's words from the turn that prompted it. A reviewer can tell a careful agent from a lucky one, which is the whole point.
6. **A case with a routing decision.** At most one per call: `facility_fault` or `claim`, a narrative drafted from the evidence, what is still missing, and a routing destination with a reason. The ticket id comes back from an ordinary business-system tool; when that call fails the case stays open and the agent says the report is recorded but not filed rather than inventing a reference (VI-12).
7. **Safety outranks the form.** An observation flagging an injury or unsafe premises hands off immediately with category `safety`, whatever state the case is in, and the packet carries the evidence pinned so far (VI-11).
8. **The product stores bytes for the first time, narrowly.** One `BlobStore` port with a local and a bucket adapter, frames bounded on the way in, a 30-day retention window, and no public or signed URL. The frame expires; the description, confidence and caller's words do not, so a case stays auditable after its images are gone ([ADR-0010](/decisions/adr-0010-media-retention.md)).
9. **A ninth module, `evidence`.** It owns the frame, the vision call, the observation, the evidence and the case. It reaches the live call through a `FrameSource` port rather than importing `voice`, because the turn loop already calls `evidence` and `voice` already calls `conversation` — a direct import would close the module graph into a cycle.
10. **A `vision` LLM role**, and messages that may carry image parts. It is the one role that can be unresolvable: with no vision-capable model configured, `POST /api/calls` creates the call as `voice` and says video is unavailable instead of failing (VI-01).
11. **No image is ever generated.** Reference and sample images are synthetic, checked in, few, and labelled. A product that can synthesise a convincing picture of damage, inside the flow that produces insurance cases, is one careless prompt away from manufacturing the evidence it exists to check ([/architecture/imagery.md](/architecture/imagery.md), IMG-01).
12. **Two new use cases and a fifth agent.** Use case 8 (ward asset fault) goes to a new internal **Facilities Intake** agent; use case 9 (visual claim intake) goes to the existing Customer Care agent.

The deployment is unchanged: one process, one origin, one Cloud Run service.

# Decisions taken while drafting, for review

Three of these were open questions, and the reviewer should push back on any of them.

* **Transport: stills on the existing socket, not LiveKit.** LiveKit Cloud was checked against the pinned toolchain rather than waved away: the transport ships in Pipecat 1.12.0, the SDK installs and mints tokens, LiveKit Cloud provides the managed TURN-over-TLS-443 fallback that ADR-0002 assumed we would have to run ourselves, and the free tier would cover a demo. It is rejected for *this* feature on one verified fact: Pipecat 1.12.0's LiveKit transport has no on-demand frame fetch, so choosing it means streaming a ward continuously to a third-party SFU in order to use two frames of it — the opposite of the consent property rules 9 and 12 of [healthcare compliance](/product/healthcare-compliance.md) rest on. The options, the measurements and the condition for revisiting are in [ADR-0009](/decisions/adr-0009-video-channel.md).
* **On demand, not a frame buffer.** The first draft of the architecture had the browser pushing a frame per second into a latest-frame buffer. On-demand capture is better on every axis that matters here — nothing leaves the browser unless the agent asked and said so, the frame is captured *for* the look rather than up to a second stale, and there is no buffer to bound or to leak. The cost is one round trip inside a tool call the caller is already waiting for, plus a 2 s timeout path (VI-15).
* **A fifth agent, not a skill on the knowledge assistant.** A ward fault report involves no member, no verification and no PHI, and it *writes* rather than answers. Bolting it onto the Internal Knowledge Assistant would blur the one agent whose guarantee (UC-03, knowledge-set isolation) is load-bearing and tested. The new agent has no document set at all, so UC-03 is untouched (UC-07). Visual claim intake is the opposite case — it is the existing claims job with a camera — so it attaches to Customer Care.

# Affected specs

New:

* [/architecture/visual-intake.md](/architecture/visual-intake.md) - the mechanism: on-demand looks, the observation and its confidence, evidence, the case and its routing, safety override, VI-01…VI-15
* [/architecture/media-storage.md](/architecture/media-storage.md) - the `BlobStore` port, frame bounds, retention, authorised access, MS-01…MS-05
* [/architecture/imagery.md](/architecture/imagery.md) - reference and sample images, no runtime generation, IMG-01…IMG-06
* [/decisions/adr-0009-video-channel.md](/decisions/adr-0009-video-channel.md) - stills on the existing socket; LiveKit and WebRTC rejected and why
* [/decisions/adr-0010-media-retention.md](/decisions/adr-0010-media-retention.md) - storing frames at all, and the split lifetimes that make it defensible
* [/prompts/vision-observation.md](/prompts/vision-observation.md) - describes one frame, withholds confidence, names the better look
* [/prompts/visual-case-draft.md](/prompts/visual-case-draft.md) - narrative, missing items, routing with a reason
* [/ui/visual-case.md](/ui/visual-case.md) - camera control, evidence strip, case card, sample picker, UI-38…UI-45

Updated:

* [/product/use-cases.md](/product/use-cases.md) - use cases 8 and 9; UC-02 reworded from seven to nine; UC-06
* [/product/scope.md](/product/scope.md) - video and visual intake in scope; the avatar, live streaming to a model and image generation explicitly out
* [/product/healthcare-compliance.md](/product/healthcare-compliance.md) - rules 9–12 (the camera is the caller's, no over-claiming, no generation, frames expire and findings do not) and three honest new production gaps
* [/architecture/agent-runtime.md](/architecture/agent-runtime.md) - the `video` channel, the `look_at_camera` built-in, RT-10
* [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) - a video call runs the same pipeline; camera state and frame handling sit outside the audio path
* [/api/voice-protocol.md](/api/voice-protocol.md) - `camera`, `capture`, `frame` and `frame_error` messages, the 2 s timeout, browser requirements
* [/api/rest-api.md](/api/rest-api.md) - `channel: "video"` and `video_unavailable`, `evidence` and `case` on call detail, `GET /api/media/{id}`, API-05
* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - the `vision` role, image parts, the `vision: true` capability flag, `role_available`, LG-16, LG-17
* [/architecture/modular-structure.md](/architecture/modular-structure.md) - the ninth module, the `BlobStore` and `FrameSource` ports, the cycle `FrameSource` prevents
* [/decisions/adr-0008-modular-monolith.md](/decisions/adr-0008-modular-monolith.md) - amendment: a ninth module, arriving with its two ports
* [/architecture/system-overview.md](/architecture/system-overview.md) - nine modules
* [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) - the `prune_media` job that re-enqueues itself, JB-06
* [/architecture/escalation.md](/architecture/escalation.md) - the visual safety trigger, `visual_evidence` on the packet, ES-09
* [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) - `look_at_camera` joins the reserved built-in names
* [/data/data-model.md](/data/data-model.md) - `media_objects`, `call_evidence`, `visual_cases`; `channel` gains `video`; DM-01 to 23 tables; DM-06
* [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) - ward assets, facility faults, claim intake, MOCK-13…15
* [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) - the Facilities Intake agent and the Rowan persona, three new tools (19), the seeded imagery and ward assets, nine use-case rows; UC-01 reworded, UC-07
* [/ui/test-call.md](/ui/test-call.md) - the channel switch becomes Talk | Video | Type
* [/ui/calls.md](/ui/calls.md) and [/ui/agent-console.md](/ui/agent-console.md) - evidence read back; the specialist sees the frames before the conclusions
* [/process/conventions.md](/process/conventions.md) - register the `VI`, `MS` and `IMG` prefixes
* [/build/task-plan.md](/build/task-plan.md) - T23…T28

# Acceptance criteria

New: **VI-01…VI-15** ([visual intake](/architecture/visual-intake.md)), **MS-01…MS-05** ([media storage](/architecture/media-storage.md)), **IMG-01…IMG-06** ([imagery](/architecture/imagery.md)), **UI-38…UI-45** ([visual case](/ui/visual-case.md)), **LG-16, LG-17**, **RT-10**, **ES-09**, **JB-06**, **DM-06**, **API-05**, **UC-06**, **UC-07**, **MOCK-13…MOCK-15**.

Reworded, with the same intent: **UC-02** (seven use cases → nine), **UC-01** (four agents and 16 tools → five and 19), **DM-01** (20 tables → 23). No ID is retired and none changes meaning.

UI-38…UI-45 need a browser and, for three of them, a webcam; they go in `scripts/acceptance-baseline.txt` as hand-checked, like UI-31…UI-33 before them. Everything else is automatable with a scripted vision response, including the `not_confirmed` path, which is the one that most needs a test.

# Tasks

1. Spec edits above, the three prefix registrations and the [log](/log.md) entry (done in this CP).
2. **T23** — `vision` role, image parts through the gateway to the wire adapter, the `vision: true` flag, `role_available` — covers LG-16, LG-17.
3. **T24** — `ports/blobstore.py`, the `local` and `gcs` adapters, frame bounds, the `prune_media` job, `GET /api/media/{id}` — covers MS-01…MS-05, JB-06.
4. **T25** — the `evidence` module: three tables, `ports/framesource.py`, `look_at_camera`, observations, pinned evidence, the case and its routing — covers VI-02…VI-13, VI-15, DM-06, RT-10. Update the table-count assertion in `tests/test_agents_tenancy.py` (20 → 23); CP-0012 annotated it as load-bearing because a table module nobody imports vanishes from the schema silently.
5. **T26** — `channel: "video"` end to end: the four control messages, the camera-state gate, degradation to voice — covers VI-01, VI-14, API-05.
6. **T27** — the Facilities Intake agent, three tools, three mock endpoints, seeded assets and the synthetic imagery — covers UC-01, UC-02, UC-06, UC-07, MOCK-13…15, IMG-01…06.
7. **T28** — web: camera control and preview, evidence strip, case card, sample picker, evidence on Calls and in the console — covers UI-38…45, ES-09.
8. Close: specs to `status: stable`, this CP to `implemented`, [log](/log.md) entry, the repo map in `AGENTS.md` for the ninth module and the two ports.

Tasks 2 and 3 are independent of the rest and land first, because every later task depends on a vision call and a place to put a frame.

# Risks and rollout

* **Schema change, and the seeder is the migration.** Three new tables and a new `channel` value. v1 creates tables with `create_all` and has no migrations ([/data/data-model.md](/data/data-model.md)), so an existing database gains the tables on start-up and existing rows are untouched — but the new demo agent, tools and use-case rows need `seed --reset`. That is the established path and the runbooks already say so; it is called out because this is the first CP since the table count changed.
* **The risk that matters is the model agreeing with the caller.** Everything else here is plumbing. Mitigations are in the design rather than in review: the prompt states that withholding is correct and that the caller's words are not evidence; `confidence` is validated enum output, not prose to be interpreted; `not_confirmed` is pinned rather than retried away; and the case narrative is drafted from observations. The test that proves it is VI-06, and it is written before the tool.
* **Cost.** A look is one `vision` call on a 1280 px frame, capped at 12 per call. The default `vision` model is OpenAI's, not Groq's, because the default text models take no images — so a deployment with only `GROQ_API_KEY` gets voice calls and an honest "video unavailable" rather than a broken camera button (VI-01).
* **Latency.** The capture round trip plus one vision call sits inside a tool round, where the runtime already speaks a filler line for voice. It does not touch turn detection or interruption, because a look is an ordinary tool call.
* **Demo impact.** The seven existing use cases are untouched; their `channels` stay `voice, chat` and UC-06 asserts it. The demo runs with no webcam through the sample images, which is the path most likely to be used on stage.
* **Fallback.** If visual intake has to be pulled, `channel: "video"` stops being offered and nothing else regresses: the built-in is absent on other channels by construction (RT-10), and the `BlobStore` port, the `vision` role and the `prune_media` job are each independently useful and independently removable.

# Out of scope

* **A talking avatar.** Uploading a face, animating it and sending the agent's video back to the caller was part of the original idea and is deliberately not here. Sending a live video track *down* to the browser is the one requirement that forces a media server, which is exactly what ADR-0009 declines to add for a feature that needs a few stills going up. It needs its own CP and its own ADR, for which the groundwork is now done: LiveKit Cloud is the transport to reach for and HeyGen the provider, both already supported by the pinned Pipecat 1.12.0. None of this work blocks it — `look_at_camera` and the evidence pipeline sit behind a module contract and never learn what carried the frame.
* **A live video stream to a model.** By design, not by deferral. See [visual intake](/architecture/visual-intake.md).
* **Runtime image generation**, including generating an example of the damage described. Reference and sample images are checked in (IMG-01), for the reason in [imagery](/architecture/imagery.md).
* **Telephony video.** Telephony audio is already out of scope.
* **PHI in frames.** A caller pointing a camera at a ward can capture a person, a chart or a screen nobody asked for. v1 neither detects nor redacts it, and [healthcare compliance](/product/healthcare-compliance.md) now records that as a production gap rather than implying it is handled. A redaction pass is a separate CP and needs more than a prompt.
* **Deletion on request and an access audit trail.** v1 gets a retention window; it does not get a path for a caller to ask for their image to be removed sooner, or a record of who viewed one. Both are named gaps.
* **Horizontal scaling.** The `local` blob-store adapter is correct for one instance and wrong for two, the same constraint [ADR-0005](/decisions/adr-0005-single-service.md) already places on the session registry. This CP adds one item to that CP's list and delivers none of it.
* **Evidence in fleet learning.** Call analysis, clustering and fix drafting do not read observations or cases yet. Visual calls will cluster on their transcripts like any other, which is adequate and not interesting; making the learning loop see evidence is a later CP with its own questions about what a "gap" means when the agent could not see well enough.
