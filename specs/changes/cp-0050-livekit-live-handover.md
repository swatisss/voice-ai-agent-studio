---
type: Change Proposal
title: CP-0050 Live voice handover on a hosted LiveKit Cloud room
description: A customer talks to the AI in the browser; on escalation a specialist on another machine takes the voice call in Agent Desk (the AI leaves); both human voices are transcribed into call events for the learning loop.
status: draft
cp_state: accepted
tags: [voice, livekit, handover, escalation, agent-desk, learning, deployment]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The owner's Phase 2: today an escalated call ends and a specialist has no audio, so the handover is not live and the specialist's spoken answer never reaches the learning loop. The chat variant (a specialist typing) is CP-0049. This CP adds the voice variant on a hosted media room so two people on two machines can talk, with the AI in the same room until the specialist takes over. Research: `.scratch/human-voice-and-channels/research/02-livekit-cloud.md`; decision: [ADR-0015](/decisions/adr-0015-hosted-media-room-livekit.md).

# What changes

* New transport `livekit` for voice calls: room `lk-<call_id>`, customer token from the API, AI as a Pipecat `LiveKitTransport` participant inside the API process.
* On escalation in a room the call stays open (`voice_state: waiting`, the AI silent); Agent Desk shows **Take the call**; the specialist joins by token; the AI introduces them and leaves (warm handover).
* A scribe participant transcribes each human track (existing STT); specialist speech becomes `human` call events (the kind introduced by CP-0049) with `source: voice`.
* New end reasons `human_ended` and `handover_timeout`; CE-01 applies to non-room calls only.
* New settings `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` (names only), `LIVEKIT_TOKEN_TTL_S`, `HANDOVER_WAIT_S`; `/healthz` `livekit`; connectivity check script; runbook.
* UI: customer playground (Voice room switch, handover states) and the Agent Desk voice panel.

# Affected specs

* [/architecture/hosted-media-room.md](/architecture/hosted-media-room.md) - new (LKH-01..LKH-16)
* [/decisions/adr-0015-hosted-media-room-livekit.md](/decisions/adr-0015-hosted-media-room-livekit.md) - new
* [/architecture/escalation.md](/architecture/escalation.md) - procedure step 6 for room calls, LKH-17
* [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md) - end reasons, CE-01 scope, LKH-18
* [/architecture/agent-desk.md](/architecture/agent-desk.md) - allow-list rows for the voice requests
* [/data/data-model.md](/data/data-model.md) - `calls.media_room`, `escalations.voice_state`, LKH-19
* [/api/rest-api.md](/api/rest-api.md) - `transport: livekit`, the two voice endpoints, LKH-20
* [/architecture/deployment.md](/architecture/deployment.md) - settings, Cloud Run notes, health, LKH-21
* [/architecture/tech-stack.md](/architecture/tech-stack.md) - dependencies
* [/ui/test-call.md](/ui/test-call.md) - Voice room switch and handover states (LKH-22..LKH-24)
* [/ui/agent-console.md](/ui/agent-console.md), [/ui/agent-desk.md](/ui/agent-desk.md) - voice panel (LKH-25..LKH-28)
* [/build/runbook-livekit.md](/build/runbook-livekit.md) - new owner runbook
* [/process/conventions.md](/process/conventions.md) - prefix `LKH`

# Acceptance criteria

New, all under the `LKH` prefix so they cannot clash with the IDs other proposals (CP-0049) take in the shared series: LKH-01..LKH-16 ([/architecture/hosted-media-room.md](/architecture/hosted-media-room.md)), LKH-17 (escalation), LKH-18 (call ending), LKH-19 (data model), LKH-20 (REST API), LKH-21 (deployment), LKH-22..LKH-24 (customer playground), LKH-25..LKH-28 (Agent Desk voice panel). Unchanged and still true: ES-07 (resolution note required), DESK-02 (everything not allow-listed is 403) apart from the two listed requests, CE-06 for other transports.

# Tasks

1. **Gate.** `scripts/livekit_check.py` and, once the owner has a project, run it locally and from Cloud Run; record UDP/TCP/relay and latency in the research note. Stop here if nothing connects (covers LKH-16).
2. Settings, token minting, admission (`livekit_unavailable`), `/healthz`, fake room for tests (LKH-01, LKH-02, LKH-14, LKH-21).
3. AI participant: Pipecat `LiveKitTransport` bound to the existing turn policy, only the customer's audio reaches the model, welcome first (LKH-03, LKH-04, LKH-13).
4. Escalation in a room: `voice_state`, call stays open, control messages, wait clock (LKH-05, LKH-06, LKH-17, LKH-18, LKH-19).
5. Specialist join: endpoint, role allow-list, token, warm handover, AI leaves (LKH-07, LKH-08, LKH-15, LKH-20).
6. Scribe: per-track STT, `human`/`user` events, partials, learning hand-off (LKH-09, LKH-10).
7. End paths: resolve, hangup, drop and restart clock (LKH-11, LKH-12).
8. Web: `livekit-client`, playground Voice room, Agent Desk voice panel (LKH-22..LKH-28).
9. Tests citing the IDs; `specs/log.md`; specs `stable`, CP `implemented`.

# Risks and rollout

* **Media from Cloud Run is UNVERIFIED** (UDP is not mentioned in Cloud Run docs). Task 1 is a hard gate with a documented fallback.
* **Pipecat with a multi-participant transport.** Mitigated by passing only the customer's frames to the model and standing the AI down before the specialist speaks; realtime pipeline for rooms only if the check proves it.
* **Free plan caps are hard**: demos must be sized (4 participants per staffed call; 5 concurrent agent sessions).
* **Specialist echo and headsets**: browser echo cancellation is on by default; the UI asks for a headset.
* **Depends on CP-0049** for the `human` event kind and its use by analysis; if CP-0049 changes the shape, task 6 follows it.
* **Privacy**: voice is heard live by a specialist; transcripts stored as call events; no audio kept; HIPAA/BAA is an owner decision before real members.

# Out of scope

* Phone numbers and SIP into the room (a later phase); recording audio to a bucket; video; multiple specialists or a supervisor listening in; a queue or skill routing for specialists; transferring a call from one specialist to another; a mobile specialist app.
