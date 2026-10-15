---
type: Task Plan
title: Task plan for CP-0001
description: Ordered implementation tasks for the initial platform build, each with governing specs, acceptance IDs, and status.
status: draft
tags: [build, tasks, cp-0001]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

Work top to bottom; each task ends green (`spec_check`, tests, web build where relevant). Status: `todo` · `doing` · `done`.

| # | Task | Specs | Acceptance | Status |
|---|---|---|---|---|
| T01 | Repo scaffolding and SDD tooling: `AGENTS.md`, `CLAUDE.md`, Claude commands, `scripts/spec_check.py`, `.githooks/` | [/process/sdd-workflow.md](/process/sdd-workflow.md) | SDD-01…04 | done |
| T02 | API skeleton: settings, DB engine, ORM models, tenancy dependency, error format, `/healthz` | [/data/data-model.md](/data/data-model.md), [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) | DM-01…03, MT-02 | done |
| T03 | Event bus, SSE endpoint, job queue and worker | [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md), [/api/events.md](/api/events.md) | JB-01…05 | done |
| T04 | LLM gateway, `models.yaml`, fake provider | [/architecture/llm-gateway.md](/architecture/llm-gateway.md) | LG-01…06 | done |
| T05 | Knowledge ingest (text/file/url/OKF), chunking, embeddings, search | [/architecture/knowledge.md](/architecture/knowledge.md) | KN-01…06 | done |
| T06 | Mock healthcare and insurance API | [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md), [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) | MOCK-01…04 | done |
| T07 | Tool executor (gate, URL rendering, in-process ASGI), tools/skills CRUD | [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) | TS-01…08 | done |
| T08 | Prompt loader reading `specs/prompts/*.md` | [/prompts/](/prompts/) | — | done |
| T09 | Agent runtime `AgentSession`; text call endpoints | [/architecture/agent-runtime.md](/architecture/agent-runtime.md), [/api/rest-api.md](/api/rest-api.md) | RT-01…09, API-01…04 | done |
| T10 | Escalation engine, packet builder, console endpoints | [/architecture/escalation.md](/architecture/escalation.md) | ES-01…08 | done |
| T11 | Agents CRUD, config validation, publish and versions | [/data/agent-config.md](/data/agent-config.md) | DM-04, DM-05, MT-01, MT-03, TS-07 | done |
| T12 | Seeder: tenants, agents, tools, skills, KB via OKF, scenarios, call history, clusters | [/demo-data/](/demo-data/) | DEP-01 | done |
| T13 | Fleet learning: `analyze_call`, clustering, naming, `draft_fix` | [/architecture/fleet-learning.md](/architecture/fleet-learning.md) | FL-01…05, FL-08 | done |
| T14 | Evaluation: simulator, judge, `run_eval` | [/architecture/evaluation.md](/architecture/evaluation.md) | EV-01…06 | done |
| T15 | Proposal edit/approve/reject → new version | [/architecture/fleet-learning.md](/architecture/fleet-learning.md) | FL-06, FL-07 | done |
| T16 | Dashboard summary endpoint | [/ui/dashboard.md](/ui/dashboard.md) | MT-04, UI-03 | done |
| T17 | Voice pipeline and WebSocket endpoint | [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), [/api/voice-protocol.md](/api/voice-protocol.md) | VO-01…06 | done |
| T18 | Web: shell, design system components, API client, SSE hook | [/ui/app-shell.md](/ui/app-shell.md), [/ui/design-system.md](/ui/design-system.md) | UI-01, UI-02 | done |
| T19 | Web: dashboard, agents list and builder, calls explorer and detail | [/ui/dashboard.md](/ui/dashboard.md), [/ui/agent-builder.md](/ui/agent-builder.md), [/ui/calls.md](/ui/calls.md) | UI-03…07, UI-11 | done |
| T20 | Web: test call (text + voice client) | [/ui/test-call.md](/ui/test-call.md) | UI-08…10 | done |
| T21 | Web: agent console and insights | [/ui/agent-console.md](/ui/agent-console.md), [/ui/insights.md](/ui/insights.md) | UI-12…17 | done |
| T22 | Static web serving, Dockerfile, Cloud Run script | [/architecture/deployment.md](/architecture/deployment.md), [/build/runbook-gcp.md](/build/runbook-gcp.md) | DEP-02, DEP-03 | done |
| T23 | `vision` LLM role: image parts through the gateway and wire adapter, `vision: true` capability, `role_available` | [/architecture/llm-gateway.md](/architecture/llm-gateway.md) | LG-16, LG-17 | done |
| T24 | `BlobStore` port with `local` and `gcs` adapters, frame bounds, the `prune_media` job, the authorised media endpoint | [/architecture/media-storage.md](/architecture/media-storage.md) | MS-01…05, JB-06 | done |
| T25 | `evidence` module: tables, the `FrameSource` port, `look_at_camera`, observations, evidence, cases and routing | [/architecture/visual-intake.md](/architecture/visual-intake.md), [/data/data-model.md](/data/data-model.md) | VI-02…13, VI-15, DM-01, DM-06, RT-10 | done |
| T26 | LiveKit video channel: room and token, the LiveKit transport beside the WebSocket one, the frame tap behind `FrameSource`, degradation to voice | [/api/media-protocol.md](/api/media-protocol.md), [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), [/api/rest-api.md](/api/rest-api.md) | VI-01, VI-14, VI-15, API-05 | done |
| T27 | Facilities Intake agent, the three new tools and mock endpoints, seeded assets and imagery | [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md), [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) | UC-01, UC-02, UC-06, UC-07, MOCK-13…15, IMG-01…06 | done |
| T28 | Web: `livekit-client` room join, camera control, evidence strip, case card, sample picker; evidence on Calls and in the console | [/ui/visual-case.md](/ui/visual-case.md), [/api/media-protocol.md](/api/media-protocol.md) | UI-38…45, ES-09 | done |
| T29 | Avatar settings and availability: the `simli` extra, `SIMLI_*` and `AVATAR_VIDEO_*` settings, `VideoRoom.avatar_enabled()`, `media.avatar` on the call response | [/architecture/avatar.md](/architecture/avatar.md), [/api/rest-api.md](/api/rest-api.md) | AV-01 | done |
| T30 | The avatar processor in `build_room()`, `video_out_enabled` only when on, interruption through to the service, pass-through of the agent's speech on failure | [/architecture/avatar.md](/architecture/avatar.md), [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) | AV-02…AV-05 | done |
| T31 | Avatar session lifetime, voice and text calls never construct it, evidence untouched, the key never leaves the process | [/architecture/avatar.md](/architecture/avatar.md) | AV-06…AV-08 | done |
| T32 | Web: the agent's video track, the agent tile with the AI agent label, the caller's self-view, the placeholder tile | [/ui/visual-case.md](/ui/visual-case.md), [/api/media-protocol.md](/api/media-protocol.md) | UI-39, UI-46…UI-48 | done |
| T33 | Avatar: refusal detected at open, `AVATAR_MAX_SESSIONS` admission cap, sessions closed at shutdown | [/architecture/avatar.md](/architecture/avatar.md) | AV-10…AV-12 | done |
| T34 | Avatar video without lag: output in latest-frame mode, vendor readers started at open, `AVATAR_VIDEO_FPS` default 30 | [/architecture/avatar.md](/architecture/avatar.md) | AV-13, AV-14 | done |
| T35 | Avatar ready before the welcome: session opens at pipeline start, the welcome waits up to 5 s for the face | [/architecture/avatar.md](/architecture/avatar.md) | AV-07, AV-09, AV-15 | done |
| T36 | Spike: confirm Vertex access, model id, avatar options and names, MP4 shape, tool behaviour and measured latency; write up under `specs/verification/` and amend CP-0018. Gates T37-T42 | [/architecture/live-session.md](/architecture/live-session.md), [/decisions/adr-0012-gemini-live-avatar.md](/decisions/adr-0012-gemini-live-avatar.md) | - | todo |
| T37 | `LiveAgent` port, Vertex adapter, settings and `.env.example`, `arch_check` confinement | [/architecture/live-session.md](/architecture/live-session.md), [/architecture/modular-structure.md](/architecture/modular-structure.md) | GL-02, GL-13, GL-14 | todo |
| T38 | The relay, engine selection and `media` on `POST /api/calls`, the WebSocket endpoint | [/architecture/live-session.md](/architecture/live-session.md), [/api/live-protocol.md](/api/live-protocol.md) | GL-01, GL-03, GL-04, GL-05, GL-12, LV-01…LV-06 | todo |
| T39 | Tools, transcripts, safety screen, welcome, ending and clocks on the Live session, usage and cost | [/architecture/live-session.md](/architecture/live-session.md) | GL-06…GL-10, GL-15 | todo |
| T40 | Camera pull: `frame_request`, `FrameSource` over the socket | [/architecture/live-session.md](/architecture/live-session.md) | GL-11 | todo |
| T41 | Web: socket client, microphone capture, MediaSource player, voice fallback, camera answers | [/ui/visual-case.md](/ui/visual-case.md), [/api/live-protocol.md](/api/live-protocol.md) | UI-49…UI-51 | todo |
| T42 | Runbooks, deployment (service account, region), compliance and demo notes | [/architecture/deployment.md](/architecture/deployment.md), [/product/healthcare-compliance.md](/product/healthcare-compliance.md) | - | todo |
