---
type: Architecture
title: System overview
description: Components, deployment shape and the three core flows (resolve, escalate, learn) of the voice AI agent platform.
status: stable
tags: [architecture, overview]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Shape

One Python service (FastAPI) serves the REST API, the voice WebSocket, server-sent events, the mock business API, the background job worker **and** the statically exported web app. One deployable, one origin, no CORS in production. See [/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md).

```
Browser (Next.js static export)
  Builder · Test call (voice/text) · Agent console · Insights · Dashboard
      │  REST /api/*      │ WS /api/voice/{call_id}     │ SSE /api/events
      ▼                   ▼                             ▼
┌──────────────────────── FastAPI service ─────────────────────────────┐
│ routes ── agent runtime (shared brain) ── tools ── knowledge search   │
│              ▲                    │            │                       │
│ voice pipeline (Pipecat: VAD→STT→turns→brain→TTS)   mock healthcare API│
│ LLM gateway (roles → Groq / OpenRouter)   event bus   job worker       │
│                 learning: analyze → cluster → draft fix → evaluate     │
└──────────────────────────────┬───────────────────────────────────────┘
                               ▼
              SQLite (local) / Postgres (Cloud SQL)
External: Groq, OpenRouter (LLM) · Deepgram (STT/TTS)
```

# Components

| Component | Responsibility | Spec |
|---|---|---|
| Agent runtime | Turn loop, prompt assembly, tool execution, state, safety screen, escalation triggers. Shared by voice, text and simulation. | [/architecture/agent-runtime.md](/architecture/agent-runtime.md) |
| Call modes | Inbound, outbound (the agent places the call) and internal (staff assistant) modes, call context, outbound targets. | [/architecture/call-modes.md](/architecture/call-modes.md) |
| Voice pipeline | Browser PCM over WebSocket → Silero VAD → Deepgram STT → turn aggregation → runtime → Deepgram TTS → browser; barge-in. | [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md) |
| LLM gateway | Role → provider/model mapping, streaming, tool calls, JSON outputs, fallback, cost. | [/architecture/llm-gateway.md](/architecture/llm-gateway.md) |
| Knowledge | Ingest, chunk, embed (local fastembed), search with a no-answer threshold. | [/architecture/knowledge.md](/architecture/knowledge.md) |
| Tools & skills | HTTP tool execution (in-process for relative URLs), verification gate, skill rendering. | [/architecture/tools-and-skills.md](/architecture/tools-and-skills.md) |
| Escalation | Triggers, packet generation, console lifecycle. | [/architecture/escalation.md](/architecture/escalation.md) |
| Fleet learning | Analysis, clustering, impact, fix drafting, approval → new version. | [/architecture/fleet-learning.md](/architecture/fleet-learning.md) |
| Evaluation | Simulator + judge replays; baseline vs candidate; regressions. | [/architecture/evaluation.md](/architecture/evaluation.md) |
| Jobs & events | DB-backed job queue; in-process pub/sub streamed as SSE. | [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md) |
| Mock insurance API | Members, policies, coverage, claims, documents and Green Card, renewals, onboarding, outreach lists, internal reference data. | [/api/mock-healthcare-api.md](/api/mock-healthcare-api.md) |
| Web app | All UI pages. | [/ui/](/ui/) |

# Flow 1 — Resolve

1. Test call page `POST /api/calls` (agent, channel) → `call_id` bound to the agent's published version.
2. Voice: browser opens `WS /api/voice/{call_id}`; text: browser posts messages to `/api/calls/{id}/messages`.
3. The runtime greets, then for each caller turn: safety screen → LLM (`realtime` role) with tools → tool calls (verification gate, HTTP tools, knowledge search) → streamed reply (→ TTS for voice).
4. Every turn, tool call and latency sample is stored as a `call_event` and published to `call:{id}` on the event bus.
5. On hang-up or `end_call`, the call ends and an `analyze_call` job is queued.

# Flow 2 — Escalate

1. The LLM calls `escalate_to_human`, or a deterministic trigger fires (safety, repeated no-answer, repeated tool errors, max turns).
2. The agent speaks the handoff message; the call status becomes `escalated`; an `escalations` row is created with `packet_status: pending` and published to the `console` topic.
3. The packet is generated immediately (LLM `analysis` role) with a deterministic fallback; the console updates live.
4. A human accepts and resolves with a disposition and note. The note becomes learning evidence.

# Flow 3 — Learn

1. `analyze_call` produces a structured analysis (outcome, intent, root cause, gap summary, caller goal).
2. The gap summary is embedded and assigned to the nearest cluster (or a new one); cluster stats and impact update.
3. A fixable cluster at or above threshold can be turned into a **fix proposal** (knowledge article or skill + tool), drafted from the human resolution notes.
4. An **eval run** replays cluster cases and regression scenarios with simulated callers against baseline and candidate configs; a judge grades each transcript.
5. A human approves → a new agent version is published with the fix; the cluster is marked `fixed`.
