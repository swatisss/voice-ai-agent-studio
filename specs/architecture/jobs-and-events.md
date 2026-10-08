---
type: Component Spec
title: Jobs and events
description: The database-backed background job queue and the in-process event bus streamed to the browser as server-sent events.
status: stable
tags: [architecture, jobs, events, sse]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Job queue

Table `jobs` ([/data/data-model.md](/data/data-model.md)). One worker task runs inside the API process (started in the FastAPI lifespan, disabled with `JOBS_ENABLED=0`).

| Kind | Payload | Handler |
|---|---|---|
| `analyze_call` | `{call_id}` | [/architecture/fleet-learning.md](/architecture/fleet-learning.md) §1–2 |
| `draft_fix` | `{cluster_id}` | fleet learning §4 |
| `run_eval` | `{proposal_id, eval_run_id}` | [/architecture/evaluation.md](/architecture/evaluation.md) |

Handlers are registered by the composition root from a declared list of kinds, and a declared kind whose module failed to register is a start-up error ([/architecture/modular-structure.md](/architecture/modular-structure.md), MOD-08). Every entry point that works or drains the queue — the API process and the `chat` command alike — performs that registration, so a drained job always has its handler.

A module asks for post-call work through the `PostCallAnalysis` port rather than naming a job kind, so the kind string and its dedupe convention have one owner.

Rules:

1. Poll every 1 s for the oldest `queued` job with `run_after ≤ now`; claim it by setting `status: running` (single worker → no locking needed; Postgres uses `FOR UPDATE SKIP LOCKED` for safety).
2. Up to 2 jobs run concurrently.
3. On exception: `attempts += 1`, `last_error` set; if `attempts < 3` → `queued` with `run_after = now + 5s × attempts`, else `failed`.
4. On success: `done`.
5. On startup, jobs left `running` are reset to `queued`.
6. `enqueue(kind, payload, dedupe_key=None)` — if a non-failed job with the same `dedupe_key` exists, no new job is created (used for `analyze_call:{call_id}`; re-analysis uses key `analyze_call:{call_id}:2`).

# Event bus

In-process async pub/sub. Each event: `{id, topic, type, tenant_id, at, data}`.

| Topic | Events |
|---|---|
| `call:{id}` | `call.event` (each stored call event), `call.escalated`, `call.ended` |
| `console` | `escalation.created`, `escalation.updated` |
| `insights` | `analysis.created`, `cluster.updated`, `proposal.updated`, `eval.progress`, `proposal.approved` |
| `dashboard` | `call.ended`, `agent.published` |

`GET /api/events?topics=console,call:abc` streams matching events for the caller's tenant as SSE ([/api/events.md](/api/events.md)). Subscribers get a bounded queue (500); if full, the oldest events are dropped. A `ping` comment is sent every 15 s.

The bus is per process; v1 runs one instance ([/decisions/adr-0005-single-service.md](/decisions/adr-0005-single-service.md)). Publishing is synchronous, non-blocking and best-effort by contract — it drops rather than waits — because it happens on the voice latency path and inside open transactions. Work that must not be lost therefore MUST NOT be triggered through the bus; it goes on the job queue.

# Acceptance

- **JB-01** — Given a job that raises twice then succeeds, then it ends `done` with `attempts == 2`.
- **JB-02** — Given a job that always raises, then after 3 attempts it is `failed` with `last_error` set.
- **JB-03** — Given a job left `running` at shutdown, when the app starts, then it is `queued` again.
- **JB-04** — Given `enqueue` twice with the same dedupe key, then one job exists.
- **JB-05** — Given a subscriber to `console` for tenant A, when tenant B creates an escalation, then the subscriber receives nothing.
