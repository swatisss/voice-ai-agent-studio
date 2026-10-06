---
type: API Contract
title: Server-sent events
description: The SSE endpoint, topic subscription rules and event payloads the web app consumes for live updates.
status: stable
tags: [api, events, sse]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Endpoint

`GET /api/events?tenant=<tenant_id>&topics=<comma-separated>` → `text/event-stream`.

Each message:

```
event: <type>
data: {"id":"...","topic":"...","type":"...","at":"...","data":{...}}
```

A `: ping` comment every 15 s keeps proxies open. Topics and the bus semantics are in [/architecture/jobs-and-events.md](/architecture/jobs-and-events.md).

# Event payloads (`data` field)

| Type | Payload |
|---|---|
| `call.event` | `{call_id, seq, kind, text, data}` — one stored call event |
| `call.escalated` | `{call_id, escalation_id, reason_category}` |
| `call.ended` | `{call_id, status, outcome, end_reason}` |
| `escalation.created` | escalation summary `{id, call_id, status, reason_category, reason_detail, packet_status, created_at}` |
| `escalation.updated` | same shape plus `packet` when ready |
| `analysis.created` | `{call_id, outcome, root_cause, cluster_id}` |
| `cluster.updated` | cluster summary |
| `proposal.updated` | `{id, cluster_id, status, kind, title}` |
| `eval.progress` | `{proposal_id, eval_run_id, done, total, last: {case_key, arm, passed}}` |
| `proposal.approved` | `{id, version_id, version}` |
| `agent.published` | `{agent_id, version_id, version}` |
