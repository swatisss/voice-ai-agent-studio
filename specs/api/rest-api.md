---
type: API Contract
title: REST API
description: Every /api endpoint with method, purpose, request and response shapes, and error conventions.
status: draft
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

## Tenant settings
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/tenant-settings` | `{allowed_pipelines: ["cascade", ...], openai: {key_set, key_last4, key_updated_at, platform_fallback}}` ([/architecture/tenant-settings.md](/architecture/tenant-settings.md)) |
| PUT | `/api/tenant-settings` | `{allowed_pipelines?, openai_platform_fallback?}` → settings; 422 if `allowed_pipelines` is empty, lacks `cascade` or has an unknown value; 409 `pipeline_in_use` (`detail` names the agents) when dropping a pipeline an agent still uses |
| PUT | `/api/tenant-settings/openai-key` | `{api_key}` → `{key_set: true, key_last4, key_updated_at}`; 422 `invalid_key`; 503 `secrets_unavailable`. The key is never returned |
| DELETE | `/api/tenant-settings/openai-key` | → 204 |

## Agents
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/agents` | `{items: [{id, name, description, mode, published_version, updated_at}]}` |
| POST | `/api/agents` | `{name, description, draft_config?}` → agent (default config filled in) |
| GET | `/api/agents/{id}` | `{id, name, description, draft_config, published_version: {id, version, created_at} \| null}` |
| PUT | `/api/agents/{id}` | `{name?, description?, draft_config?}` → agent (validated per [/data/agent-config.md](/data/agent-config.md); 422 `pipeline_not_allowed`) |
| POST | `/api/agents/{id}/publish` | `{change_note?}` → `{id, version, created_at}`; 422 on validation failure, including `pipeline_not_allowed` |
| GET | `/api/agents/{id}/versions` | `{items: [{id, version, change_note, source_proposal_id, created_at}]}` |
| GET | `/api/agents/{id}/scenarios` | `{items: [scenario + last: {eval_run_id, passed, of} \| null]}`, the scenarios of the agent's test suite ([/architecture/test-suites.md](/architecture/test-suites.md)) and each one's result in the latest finished suite run |
| POST | `/api/agents/{id}/scenarios` | `{name, caller_goal, caller_profile?, persona?, expected?, required_tools?, forbidden_tools?, expected_results?, memory?, enabled?}` → scenario; 422 invalid or `unknown_tool`, 409 `name_taken` |
| PUT | `/api/scenarios/{id}` | same body, any subset → scenario |
| DELETE | `/api/scenarios/{id}` | → 204; finished runs keep their copy |
| POST | `/api/agents/{id}/test-runs` | `{target?: "published"\|"draft"\|"version", version_id?, repeats?: 1–5, scenario_ids?, trigger?: "manual"\|"builder"}` → `{eval_run_id}`; 409 `run_in_progress`, 409 `not_published`, 422 `no_scenarios`, 422 when the draft would not publish |
| GET | `/api/agents/{id}/test-runs` | → `{items: [{id, target, version, trigger, status, repeats, summary, created_at, finished_at}]}`, newest first, at most 50 |
| GET | `/api/agents/{id}/checks` | query `source=draft\|published` (default `draft`) → `{items: [{key, group, method, hard_gate, text, source: "built_in"\|"config"\|"custom"}]}`, the checks [call scoring](/architecture/call-scoring.md) would apply; 409 `not_published` for `published` on an unpublished agent |

## Personas
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/personas` | `{items: [persona + used_by: [agent names]]}` |
| POST | `/api/personas` | persona fields ([/architecture/personas.md](/architecture/personas.md)) → persona |
| PUT | `/api/personas/{id}` | persona fields → persona |
| DELETE | `/api/personas/{id}` | 204; 409 `persona_in_use` while an agent draft references it |

`settings` (in call responses and `GET /api/calls/{id}`): `{pipeline: "cascade"|"realtime", persona: {id, name, voice, speed}, turn_detection: {...}, openai_key_source?: "tenant"|"platform"}`, the effective values after overrides; `openai_key_source` is present on voice calls of the realtime pipeline from call creation (the admission plan's credential source).

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
| POST | `/api/calls` | `{agent_id, channel: "voice"\|"text", persona_id?, turn_detection?, context?, caller_number?}` → `{call_id, greeting, settings}` (`settings`: `{pipeline, persona, turn_detection}`); 409 if agent unpublished; for `voice`, 409 `pipeline_not_allowed` or `voice_unavailable` when [call admission](/architecture/call-admission.md) refuses (no call row is created). For an outbound agent `context: {member_ref}` is required (422 `unknown_target`) and `greeting` is the persona opening ([/architecture/call-modes.md](/architecture/call-modes.md)). `persona_id` and `turn_detection` (any subset of the turn-detection fields) override the agent's for this call. For `text`, the greeting is already recorded; for `voice`, it is spoken on connect. `caller_number` (E.164, test calls only) is looked up as a phone call's number would be, and only the identification result is kept ([/architecture/caller-verification.md](/architecture/caller-verification.md)). |
| POST | `/api/calls/{id}/messages` | `{text}` → `{reply, call_status, ended, escalated}` (text channel only) |
| POST | `/api/calls/{id}/end` | → `{status, outcome}` |
| POST | `/api/calls/{id}/feedback` | `{rating: "up"\|"down", comment?: string ≤ 300}` → `{rating, comment}`; only for an ended call: 404 unknown, 409 `call_active`, 409 `not_ratable` (simulation calls), 422 invalid. Sending again replaces the earlier answer; a `down` queues one more `analyze_call`. See [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md). |
| PATCH | `/api/calls/{id}/live` | `{persona_id?, turn_detection?}` → `{settings}`; changes persona and/or turn detection of a running call (404 unknown, 409 ended, 422 invalid). 409 `realtime_pipeline` for a call on the realtime pipeline ([/architecture/realtime-voice.md](/architecture/realtime-voice.md), RV-15). See [/architecture/personas.md](/architecture/personas.md), [/architecture/turn-detection.md](/architecture/turn-detection.md). |
| GET | `/api/calls` | query `agent_id?`, `outcome?`, `channel?`, `direction?`, `feedback?` (`up`\|`down`\|`none`), `include_seed=true` → `{items: [call summary]}` (eval calls excluded); each summary carries `feedback` (`"up"`, `"down"` or `null`) and `transport` (`"phone"` for a call that came in through Twilio, else `"browser"`) |
| GET | `/api/calls/{id}` | call + `events` + `escalation` + `analysis` + `feedback` (`{rating, comment, at}` or `null`) + `telephony` (`{provider, call_sid, from_last4, to}` for a phone call, else `null`) + `identification` (`{first_name, method, attestation}` or `null`) + `memory` (`{used: [memory], updated: [memory event]}`) + `scorecard` (the call's scorecard with `reviews: {check_key: review}`, or `null`) |
| POST | `/api/calls/{id}/rescore` | → `{job_id}`; queues `score_call` again; 409 `call_active`, 409 `not_scorable` for a simulation call |
| WS | `/api/voice/{id}?tenant=` | [/api/voice-protocol.md](/api/voice-protocol.md) |

## Member memory

| Method | Path | Body / query → result |
|---|---|---|
| GET | `/api/members/{member_ref}/memory` | query `agent_id` → `{agents: [{id, name}], facts, episodes, retired, events}` for that agent ([/architecture/agent-memory.md](/architecture/agent-memory.md)); 404 when the tenant holds nothing for the member |
| POST | `/api/members/{member_ref}/memory/{memory_id}/restore` | → the restored item; 409 if it is not retired |
| POST | `/api/members/{member_ref}/memory/erase` | → `{erased: <count>}`; removes every memory and event content of the member in the tenant |
| GET | `/api/members/{member_ref}/memory/export` | → JSON file of all memories and events of the member in the tenant |

## Phone numbers and telephony
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/phone-numbers` | → `{items: [{id, e164, agent_id, agent_name, label, created_at}]}` for the tenant |
| POST | `/api/phone-numbers` | `{e164, agent_id, label?}` → the number; 409 `number_in_use`, 422 for a bad number or an agent that is not the tenant's |
| DELETE | `/api/phone-numbers/{id}` | → 204; 404 for another tenant's number |
| POST | `/api/telephony/twilio/voice` | Twilio voice webhook (form fields, signed); **no tenant header**: returns TwiML ([/architecture/telephony.md](/architecture/telephony.md)); 403 on a bad signature |
| WS | `/api/telephony/twilio/stream/{call_id}?token=` | Twilio Media Stream; **no tenant parameter**; token minted by the webhook |

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
| GET | `/api/insights/clusters` | query `agent_id?` → `{items: [cluster + weekly_escalations, est_weekly_cost_usd, dislike_count, signal_count, ready_for_fix, label]}`; `dislike_count` = member calls with a thumbs down in the last 28 days, `signal_count` = distinct member escalations plus thumbs-down calls in that window ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)) |
| GET | `/api/insights/clusters/{id}` | cluster + member calls (analysis + resolution notes + `feedback`) + proposals |
| POST | `/api/insights/clusters/{id}/draft-fix` | → `{job_id}` (proposal arrives via `proposal.updated` event); 409 if not ready |
| POST | `/api/insights/clusters/{id}/ignore` | → cluster |
| GET | `/api/proposals/{id}` | proposal + draft doc + latest eval run (summary + results) |
| PUT | `/api/proposals/{id}` | `{title?, payload?}` → proposal (status back to `draft`) |
| POST | `/api/proposals/{id}/evaluate` | → `{eval_run_id}` |
| GET | `/api/insights/inbox` | query `agent_id?` → `{items: [proposal + cluster name + latest eval summary with its gate]}`: proposals in `ready` that nobody decided, newest first ([/architecture/self-learning.md](/architecture/self-learning.md), Review) |
| GET | `/api/learning/runs` | → `{items: [{id, trigger, status, since, summary, started_at, finished_at}]}`, newest first, at most 30 |
| POST | `/api/learning/run` | → `{learning_run_id}`; 409 `run_in_progress` |
| POST | `/api/proposals/{id}/approve` | `{decided_by, note?, force?}` → `{proposal, version}`; 409 `evaluation_gate` when the gate failed and no `force` with a note ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)) |
| POST | `/api/proposals/{id}/reject` | `{decided_by, note}` → proposal |

## Evaluation
| Method | Path | Body / query → Result |
|---|---|---|
| GET | `/api/test-runs/{id}` | → run + `results: [{scenario_id, scenario, repeat, passed, failures, call_id, scorecard: {score, hard_fail, failed_checks}}]` |
| GET | `/api/evaluation/summary` | query `agent_id` (required), `days` (7\|28\|90, default 28), `include_seed=true` → `{versions: [{version_id, version, published_at, calls, scored, containment_rate, correct_escalation_rate, unnecessary_escalation_rate, abandonment_rate, hard_fail_calls, thumbs_up_rate, first_response_ms, latency_p50_ms, latency_p95_ms, drift: ["goal_met"\|"grounded"\|"containment"], check_pass_rates: {key: rate}}], checks: [{key, group, method, hard_gate, text, pass_rate, decided, reviews, agreement, catch_rate, baseline, calibrated}], daily: [{date, calls, containment_rate, goal_met_rate, grounded_rate, hard_fails}]}`; rates are 0–1 or `null` without data; another `days` → 422 `invalid_days` ([/architecture/call-scoring.md](/architecture/call-scoring.md)) |
| GET | `/api/evaluation/scorecards` | query `agent_id` (required), `version_id?`, `check?` (key), `verdict?`, `hard_fail?`, `reviewed?`, `days`, `include_seed=true` → `{items: [{call_id, started_at, version, outcome, feedback, score, hard_fail, judged, failed_checks: [key], review_count}]}`, newest first, at most 200 |
| PUT | `/api/scorecards/{id}/reviews/{check_key}` | `{verdict: "pass"\|"fail"\|"n/a", note?, reviewer}` → review; replaces the earlier review of that check; 404 unknown key; 409 `code_check` for a check decided in code |

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
- **API-05** — Given `POST /api/calls` with `caller_number` set to a registered number, then `GET /api/calls/{id}` shows `identification.first_name` and never the number; a value that is not E.164 returns 422.
- **API-06** — Given a verified call that loaded memory and a finished `extract_memory` job, then `GET /api/calls/{id}` lists the loaded items under `memory.used` and the job's changes under `memory.updated`.
- **API-07** — Given a member erased with `POST …/memory/erase`, then `GET …/memory` returns no facts, episodes or retired items and only the content-free erasure event, and so does the export; for a member the tenant never held anything about, `GET …/memory` returns 404.
- **API-08** — Given a scored call, when `PUT /api/scorecards/{id}/reviews/knowledge.grounded` is sent twice with different verdicts, then one review exists with the second verdict and the stored judge verdict is unchanged; the same request for `tools.succeeded` returns 409 `code_check`.
- **API-09** — Given an agent with scored real calls and simulation calls, then `GET /api/evaluation/summary` counts only the real calls, and `GET /api/agents/{id}/checks` for a draft with a new `never` item lists its `never.<hash>` check with `source: "config"` before it is published.
- **API-04** — Given `GET /api/calls`, then simulation calls created by evaluations never appear.
