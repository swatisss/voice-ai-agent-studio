---
type: API Contract
title: REST API
description: Every /api endpoint with method, purpose, request and response shapes, and error conventions.
status: stable
tags: [api, rest]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Conventions

* JSON in/out; `snake_case` fields; timestamps ISO 8601 UTC.
* Tenant header `X-Tenant-Id` on every request except `GET /api/tenants` ([/architecture/multi-tenancy.md](/architecture/multi-tenancy.md)).
* Errors: `{"error": "<code>", "detail": "<human text>"}` with 400/404/409/422/500.
* Lists return `{"items": [...]}`; no pagination in v1 (lists capped at 500, newest first).

# Endpoints

## Tenants & models
| Method | Path | Result |
|---|---|---|
| GET | `/api/tenants` | `{items: [{id, name, industry}]}` |
| GET | `/api/models` | `{roles: {realtime: "<ref>", ...}, selectable: ["<ref>", ...]}` |

## Agents
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/agents` | `{items: [{id, name, description, mode, published_version, updated_at}]}` |
| POST | `/api/agents` | `{name, description, draft_config?}` → agent (default config filled in) |
| GET | `/api/agents/{id}` | `{id, name, description, draft_config, published_version: {id, version, created_at} \| null}` |
| PUT | `/api/agents/{id}` | `{name?, description?, draft_config?}` → agent (validated per [/data/agent-config.md](/data/agent-config.md)) |
| POST | `/api/agents/{id}/publish` | `{change_note?}` → `{id, version, created_at}`; 422 on validation failure |
| GET | `/api/agents/{id}/versions` | `{items: [{id, version, change_note, source_proposal_id, created_at}]}` |
| GET | `/api/agents/{id}/scenarios` | `{items: [eval_scenario]}` |

## Personas
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/personas` | `{items: [persona + used_by: [agent names]]}` |
| POST | `/api/personas` | persona fields ([/architecture/personas.md](/architecture/personas.md)) → persona |
| PUT | `/api/personas/{id}` | persona fields → persona |
| DELETE | `/api/personas/{id}` | 204; 409 `persona_in_use` while an agent draft references it |

`settings` (in call responses and `GET /api/calls/{id}`): `{persona: {id, name, voice, speed}, turn_detection: {...}}`, the effective values after overrides.

## Tools, skills, knowledge
| Method | Path | Body → Result |
|---|---|---|
| GET/POST | `/api/tools` | tool definition → tool |
| PUT/DELETE | `/api/tools/{id}` | tool definition → tool / 204 |
| GET/POST | `/api/skills` | skill definition → skill |
| PUT/DELETE | `/api/skills/{id}` | skill definition → skill / 204 |
| GET | `/api/knowledge` | `{items: [{id, title, source_type, status, chunk_count, created_at}]}` |
| GET | `/api/knowledge/{id}` | doc with `content` and `chunks` |
| POST | `/api/knowledge/text` | `{title, content}` → doc |
| POST | `/api/knowledge/url` | `{url}` → doc |
| POST | `/api/knowledge/upload` | multipart `file` (`.md/.txt/.pdf` → one doc; `.zip` → OKF import) → `{items: [doc]}` |
| DELETE | `/api/knowledge/{id}` | archive → 204 |
| POST | `/api/knowledge/search` | `{query, doc_ids?}` → search result (debug panel in builder) |

## Calls
| Method | Path | Body → Result |
|---|---|---|
| POST | `/api/calls` | `{agent_id, channel: "voice"\|"text", persona_id?, turn_detection?, context?}` → `{call_id, greeting, settings}`; 409 if agent unpublished. For an outbound agent `context: {member_ref}` is required (422 `unknown_target`) and `greeting` is the persona opening ([/architecture/call-modes.md](/architecture/call-modes.md)). `persona_id` and `turn_detection` (any subset of the turn-detection fields) override the agent's for this call. For `text`, the greeting is already recorded; for `voice`, it is spoken on connect. |
| POST | `/api/calls/{id}/messages` | `{text}` → `{reply, call_status, ended, escalated}` (text channel only) |
| POST | `/api/calls/{id}/end` | → `{status, outcome}` |
| PATCH | `/api/calls/{id}/live` | `{persona_id?, turn_detection?}` → `{settings}`; changes persona and/or turn detection of a running call (404 unknown, 409 ended, 422 invalid). See [/architecture/personas.md](/architecture/personas.md), [/architecture/turn-detection.md](/architecture/turn-detection.md). |
| GET | `/api/calls` | query `agent_id?`, `outcome?`, `channel?`, `direction?`, `include_seed=true` → `{items: [call summary]}` (eval calls excluded) |
| GET | `/api/calls/{id}` | call + `events` + `escalation` + `analysis` |
| WS | `/api/voice/{id}?tenant=` | [/api/voice-protocol.md](/api/voice-protocol.md) |

## Use cases and outbound
| Method | Path | Result |
|---|---|---|
| GET | `/api/use-cases` | `{items: [{id, category, title, summary, channels, mode, agent_id, agent_name, published, sample_utterances, demo_callers}]}` in catalog order ([/product/use-cases.md](/product/use-cases.md)) |
| GET | `/api/outbound/targets` | query `agent_id` → `{items: [{member_ref, first_name, summary, context}]}` from the agent's `outbound.targets_url`; 409 `not_outbound` for other agents ([/architecture/call-modes.md](/architecture/call-modes.md)) |

## Escalations (console)
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/escalations` | query `status?` → `{items: [escalation + call summary]}` |
| GET | `/api/escalations/{id}` | escalation + call events |
| POST | `/api/escalations/{id}/accept` | `{assignee}` → escalation; 409 unless `waiting` |
| POST | `/api/escalations/{id}/resolve` | `{disposition, resolution_note}` → escalation; 409 unless `accepted` |

## Insights
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/insights/clusters` | query `agent_id?` → `{items: [cluster + weekly_escalations, est_weekly_cost_usd, ready_for_fix, label]}` |
| GET | `/api/insights/clusters/{id}` | cluster + member calls (analysis + resolution notes) + proposals |
| POST | `/api/insights/clusters/{id}/draft-fix` | → `{job_id}` (proposal arrives via `proposal.updated` event); 409 if not ready |
| POST | `/api/insights/clusters/{id}/ignore` | → cluster |
| GET | `/api/proposals/{id}` | proposal + draft doc + latest eval run (summary + results) |
| PUT | `/api/proposals/{id}` | `{title?, payload?}` → proposal (status back to `draft`) |
| POST | `/api/proposals/{id}/evaluate` | → `{eval_run_id}` |
| POST | `/api/proposals/{id}/approve` | `{decided_by, note?, force?}` → `{proposal, version}`; 409 per [/architecture/fleet-learning.md](/architecture/fleet-learning.md) |
| POST | `/api/proposals/{id}/reject` | `{decided_by, note}` → proposal |

## Dashboard
| Method | Path | Result |
|---|---|---|
| GET | `/api/dashboard/summary` | query `agent_id?` → `{totals: {calls, resolved, escalated, abandoned, containment_rate, cost_saved_usd, avg_llm_cost_usd, latency_p50_ms}, weekly: [{week_start, calls, containment_rate}], by_root_cause: [{root_cause, count}], top_clusters: [...], recent_versions: [...]}` |

## Ops
| Method | Path | Result |
|---|---|---|
| GET | `/healthz` | see [/architecture/deployment.md](/architecture/deployment.md) |

# Acceptance

- **API-01** — Given an unpublished agent, when `POST /api/calls` is made, then the response is 409 `agent_not_published`.
- **API-02** — Given a text call, when `POST /messages` is made on a voice call id, then the response is 409 `wrong_channel`.
- **API-03** — Given any validation failure, then the response is 422 with `{error, detail}`.
- **API-04** — Given `GET /api/calls`, then simulation calls created by evaluations never appear.
