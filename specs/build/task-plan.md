---
type: Task Plan
title: Task plan for CP-0001
description: Ordered implementation tasks for the initial platform build, each with governing specs, acceptance IDs, and status.
status: stable
tags: [build, tasks, cp-0001]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

Work top to bottom; each task ends green (`spec_check`, tests, web build where relevant). Status: `todo` · `doing` · `done`.

| # | Task | Specs | Acceptance | Status |
|---|---|---|---|---|
| T01 | Repo scaffolding and SDD tooling: `AGENTS.md`, `CLAUDE.md`, Claude commands, `scripts/spec_check.py`, `.githooks/` | [/process/sdd-workflow.md](/process/sdd-workflow.md) | SDD-01…04 | todo |
| T02 | API skeleton: settings, DB engine, ORM models, tenancy dependency, error format, `/healthz` | [/data/data-model.md](/data/data-model.md), [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) | DM-01…03, MT-02 | todo |
| T03 | Event bus, SSE endpoint, job queue and worker | [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md), [/api/events.md](/api/events.md) | JB-01…05 | todo |
| T04 | LLM gateway, `models.yaml`, fake provider | [/architecture/llm-gateway.md](/architecture/llm-gateway.md) | LG-01…06 | todo |
| T05 | Knowledge ingest (text/file/url/OKF), chunking, embeddings, search | [/architecture/knowledge.md](/architecture/knowledge.md) | KN-01…06 | todo |
| T06 | Mock healthcare and pharmacy API | [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md), [/demo-data/members-and-claims.md](/demo-data/members-and-claims.md) | MOCK-01…04 | todo |
| T07 | Tool executor (gate, URL rendering, in-process ASGI), tools/skills CRUD | [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) | TS-01…08 | todo |
| T08 | Prompt loader reading `specs/prompts/*.md` | [/prompts/](/prompts/) | — | todo |
| T09 | Agent runtime `AgentSession`; text call endpoints | [/architecture/agent-runtime.md](/architecture/agent-runtime.md), [/api/rest-api.md](/api/rest-api.md) | RT-01…09, API-01…04 | todo |
| T10 | Escalation engine, packet builder, console endpoints | [/architecture/escalation.md](/architecture/escalation.md) | ES-01…08 | todo |
| T11 | Agents CRUD, config validation, publish and versions | [/data/agent-config.md](/data/agent-config.md) | DM-04, DM-05, MT-01, MT-03, TS-07 | todo |
| T12 | Seeder: tenants, agents, tools, skills, KB via OKF, scenarios, call history, clusters | [/demo-data/](/demo-data/) | DEP-01 | todo |
| T13 | Fleet learning: `analyze_call`, clustering, naming, `draft_fix` | [/architecture/fleet-learning.md](/architecture/fleet-learning.md) | FL-01…05, FL-08 | todo |
| T14 | Evaluation: simulator, judge, `run_eval` | [/architecture/evaluation.md](/architecture/evaluation.md) | EV-01…06 | todo |
| T15 | Proposal edit/approve/reject → new version | [/architecture/fleet-learning.md](/architecture/fleet-learning.md) | FL-06, FL-07 | todo |
| T16 | Dashboard summary endpoint | [/ui/dashboard.md](/ui/dashboard.md) | MT-04, UI-03 | todo |
| T17 | Voice pipeline and WebSocket endpoint | [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), [/api/voice-protocol.md](/api/voice-protocol.md) | VO-01…06 | todo |
| T18 | Web: shell, design system components, API client, SSE hook | [/ui/app-shell.md](/ui/app-shell.md), [/ui/design-system.md](/ui/design-system.md) | UI-01, UI-02 | todo |
| T19 | Web: dashboard, agents list and builder, calls explorer and detail | [/ui/dashboard.md](/ui/dashboard.md), [/ui/agent-builder.md](/ui/agent-builder.md), [/ui/calls.md](/ui/calls.md) | UI-03…07, UI-11 | todo |
| T20 | Web: test call (text + voice client) | [/ui/test-call.md](/ui/test-call.md) | UI-08…10 | todo |
| T21 | Web: agent console and insights | [/ui/agent-console.md](/ui/agent-console.md), [/ui/insights.md](/ui/insights.md) | UI-12…17 | todo |
| T22 | Static web serving, Dockerfile, Cloud Run script | [/architecture/deployment.md](/architecture/deployment.md), [/build/runbook-gcp.md](/build/runbook-gcp.md) | DEP-02, DEP-03 | todo |
