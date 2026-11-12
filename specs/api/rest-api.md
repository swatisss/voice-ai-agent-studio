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
* The key-authenticated `/v1` API for tenant backends is a separate contract: [/api/public-api.md](/api/public-api.md).
* Errors: `{"error": "<code>", "detail": "<human text>"}` with 400/401/403/404/409/422/500.
* **Sign-in** ([/architecture/studio-auth.md](/architecture/studio-auth.md)): when it is on, every `/api/` request except `/api/auth/*` and `/api/telephony/*` needs the `studio_session` cookie (401 `login_required`), admin-only requests from a reviewer get 403 `admin_required`, and the signed-in user's name replaces body names (`decided_by`, `assignee`, `reviewer`, `by`).
* Lists return `{"items": [...]}`; no pagination in v1 (lists capped at 500, newest first).

# Endpoints

## Sign-in
| Method | Path | Body → Result |
|---|---|---|
| POST | `/api/auth/login` | `{email, password}` → `{user: {email, name, role}}` and the session cookie; 401 `bad_credentials` |
| POST | `/api/auth/logout` | → 204, cookie cleared |
| GET | `/api/auth/me` | → `{enabled, user}` (`user` `null` without a session) |

## Compliance
| Method | Path | Result |
|---|---|---|
| GET | `/api/compliance/evidence` | → `{controls: [{id, rule, reference, enforcement, where, status, evidence: [{id, status, tests}]}], gaps: [text], report: {generated_at, commit} \| null}` ([/product/compliance-evidence.md](/product/compliance-evidence.md)); not tenant-scoped |

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
| GET | `/api/tenant-settings/front-desk` | → `{persona_id, pipeline, default_agents: {member, staff}, min_confidence, max_clarifications, connecting_message, min_routing_accuracy, routing_mode, clear_win, clear_margin}` with defaults filled in ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)) |
| PUT | `/api/tenant-settings/front-desk` | any subset → front desk; 422 for an unknown persona, a pipeline the tenant does not allow, or a default agent that is not routable in that scope |

## API keys and webhooks
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/api-keys` | → `{items: [{id, name, prefix, scope, rate_limit_per_min, max_concurrent_voice, created_at, last_used_at, revoked_at}]}` ([/api/public-api.md](/api/public-api.md)) |
| POST | `/api/api-keys` | `{name, scope, rate_limit_per_min?, max_concurrent_voice?}` → the key row plus `key` (the full key, **only in this response**); 409 `name_taken`, 409 `too_many_keys` (20 active), 422 invalid |
| PUT | `/api/api-keys/{id}` | `{name?, rate_limit_per_min?, max_concurrent_voice?}` → key row (scope cannot change) |
| DELETE | `/api/api-keys/{id}` | revoke → 204 |
| GET | `/api/webhooks` | → `{items: [{id, url, events, include_transcript, enabled, created_at, secret_rotated_at}]}` ([/architecture/webhooks.md](/architecture/webhooks.md)) |
| POST | `/api/webhooks` | `{url, events, include_transcript?, enabled?}` → endpoint plus `secret` (only here and on rotate); 409 `too_many_endpoints` (5); 422 invalid URL or event; 503 `secrets_unavailable` |
| PUT | `/api/webhooks/{id}` | `{url?, events?, include_transcript?, enabled?}` → endpoint |
| POST | `/api/webhooks/{id}/rotate` | → `{secret}` |
| DELETE | `/api/webhooks/{id}` | → 204 |
| GET | `/api/webhooks/{id}/deliveries` | query `status?` → `{items: [{id, event_id, type, conversation_id, status, attempts, last_status_code, last_error, created_at, delivered_at}]}`, newest first, at most 200 |
| POST | `/api/webhooks/deliveries/{id}/resend` | → delivery (queued) |

## Agents
| Method | Path | Body → Result |
|---|---|---|
| GET | `/api/agents` | `{items: [{id, name, description, mode, published_version, updated_at}]}` |
| POST | `/api/agents` | `{name, description, draft_config?}` → agent (default config filled in; on a tenant that allows `realtime` the default is the realtime pipeline with `languages: ["en","hi"]`, otherwise cascade with `["en"]`; values in `draft_config` win, [/architecture/languages.md](/architecture/languages.md) LANG-11) |
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
| POST | `/api/knowledge/search` | `{query, doc_ids?, source_ids?}` → search result (debug panel in builder); results from website pages carry `url` |
| GET | `/api/knowledge/sources` | `{items: [source]}` ([/architecture/knowledge.md](/architecture/knowledge.md), Website sources) |
| POST | `/api/knowledge/sources` | `{start_url, scope?: "page"\|"section", max_pages?: 1–100, refresh?: "off"\|"daily"\|"weekly", title?}` → 202 source with `status: indexing`; queues `sync_knowledge_source`; 422 `invalid_url` or `blocked_address` for the start URL |
| GET | `/api/knowledge/sources/{id}` | source + `pages: [{doc_id, url, title, status, chunk_count, content_hash, updated_at}]` |
| PUT | `/api/knowledge/sources/{id}` | `{title?, max_pages?, refresh?}` → source |
| POST | `/api/knowledge/sources/{id}/sync` | → 202 `{job_id}`; 409 `sync_in_progress` |
| DELETE | `/api/knowledge/sources/{id}` | → 204; archives its pages and removes it from draft configs |

## Calls
| Method | Path | Body → Result |
|---|---|---|
| POST | `/api/calls` | `{agent_id, channel: "voice"\|"text", persona_id?, turn_detection?, context?, caller_number?}` → `{call_id, greeting, settings}` (`settings`: `{pipeline, persona, turn_detection}`); 409 if agent unpublished; for `voice`, 409 `pipeline_not_allowed` or `voice_unavailable` when [call admission](/architecture/call-admission.md) refuses (no call row is created). For an outbound agent `context: {member_ref}` is required (422 `unknown_target`) and `greeting` is the persona opening ([/architecture/call-modes.md](/architecture/call-modes.md)). `persona_id` and `turn_detection` (any subset of the turn-detection fields) override the agent's for this call. For `text`, the greeting is already recorded; for `voice`, it is spoken on connect. `caller_number` (E.164, test calls only) is looked up as a phone call's number would be, and only the identification result is kept ([/architecture/caller-verification.md](/architecture/caller-verification.md)). |
| POST | `/api/calls/{id}/messages` | `{text}` → `{reply, call_status, ended, escalated}` (text channel only) |
| POST | `/api/calls/{id}/end` | → `{status, outcome}` |
| POST | `/api/calls/{id}/feedback` | `{rating: "up"\|"down", comment?: string ≤ 300}` → `{rating, comment}`; only for an ended call: 404 unknown, 409 `call_active`, 409 `not_ratable` (simulation calls), 422 invalid. Sending again replaces the earlier answer; a `down` queues one more `analyze_call`. See [/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md). |
| PATCH | `/api/calls/{id}/live` | `{persona_id?, turn_detection?}` → `{settings}`; changes persona and/or turn detection of a running call (404 unknown, 409 ended, 422 invalid). 409 `realtime_pipeline` for a call on the realtime pipeline ([/architecture/realtime-voice.md](/architecture/realtime-voice.md), RV-15). See [/architecture/personas.md](/architecture/personas.md), [/architecture/turn-detection.md](/architecture/turn-detection.md). |
| GET | `/api/calls` | query `agent_id?`, `outcome?`, `channel?`, `direction?`, `feedback?` (`up`\|`down`\|`none`), `include_seed=true` → `{items: [call summary]}` (eval calls excluded); each summary carries `feedback` (`"up"`, `"down"` or `null`) and `transport` (`"phone"` for a call that came in through Twilio, else `"browser"`) |
| GET | `/api/calls/{id}` | call + `events` + `escalation` + `analysis` + `feedback` (`{rating, comment, at}` or `null`) + `telephony` (`{provider, call_sid, from_last4, to}` for a phone call, else `null`) + `identification` (`{first_name, method, attestation}` or `null`) + `memory` (`{used: [memory], updated: [memory event]}`) + `scorecard` (the call's scorecard with `reviews: {check_key: review}`, or `null`) + `version_info` (`{version, published_by, published_at, change_note, source_proposal: {id, title, cluster_id, decided_by, decided_at} | null}`, CMP-03) |
| POST | `/api/calls/{id}/rescore` | → `{job_id}`; queues `score_call` again; 409 `call_active`, 409 `not_scorable` for a simulation call |
| WS | `/api/voice/{id}?tenant=` | [/api/voice-protocol.md](/api/voice-protocol.md) |

`GET /api/calls` also accepts `conversation_id`; call summaries and `GET /api/calls/{id}` carry `conversation_id`, `segment` and `routed_by` (`null` for calls outside a conversation).

## Conversations (Studio)
The playground's full-flow mode and the Studio's views of conversations. Same behaviour and shapes as the public API's conversation endpoints ([/api/public-api.md](/api/public-api.md)), with the tenant from `X-Tenant-Id`, `source: playground`, and the scope in the body.

| Method | Path | Body → Result |
|---|---|---|
| POST | `/api/conversations` | `{scope: "member"\|"staff", channel, message?, agent_id?, transport?, caller?, context?}` → as the public create; voice returns `connect` for `/v1/voice/{id}` |
| POST | `/api/conversations/{id}/messages` | `{text}` → turn result (JSON or SSE) |
| POST | `/api/conversations/{id}/end` | → `{status, outcome}` |
| GET | `/api/conversations` | query `source?`, `status?` → `{items: [conversation summary]}`, newest first, at most 200 |
| GET | `/api/conversations/{id}` | → conversation view with `routing` and `transcript` |

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
| GET | `/api/phone-numbers` | → `{items: [{id, e164, target, agent_id, agent_name, label, created_at}]}` for the tenant (`target`: `agent` or `front_desk`; `agent_id` is `null` for the front desk) |
| POST | `/api/phone-numbers` | `{e164, target?: "agent"\|"front_desk", agent_id?, label?}` → the number (`target` defaults to `agent`, which requires `agent_id`); 409 `number_in_use`, 422 for a bad number, an agent that is not the tenant's, or `agent_id` with `front_desk` |
| DELETE | `/api/phone-numbers/{id}` | → 204; 404 for another tenant's number |
| POST | `/api/telephony/twilio/voice` | Twilio voice webhook (form fields, signed); **no tenant header**: returns TwiML ([/architecture/telephony.md](/architecture/telephony.md)); 403 on a bad signature |
| WS | `/api/telephony/twilio/stream/{call_id}?token=` | Twilio Media Stream; **no tenant parameter**; token minted by the webhook |

## Use cases and outbound
| Method | Path | Result |
|---|---|---|
| GET | `/api/use-cases` | query `agent_id?` → `{items: [{id, category, title, summary, channels, mode, agent_id, agent_name, published, sample_utterances, demo_callers, sort, updated_at}]}` in catalog order ([/product/use-cases.md](/product/use-cases.md)) |
| POST | `/api/use-cases` | `{agent_id, title, summary?, category?, channels?, sample_utterances, demo_callers?, sort?}` → use case; validation per [/architecture/capability-catalog.md](/architecture/capability-catalog.md) (422; 404 for another tenant's agent; 409 `title_taken`); queues `index_capabilities` for a published agent |
| PUT | `/api/use-cases/{id}` | any subset → use case; re-index as above |
| DELETE | `/api/use-cases/{id}` | → 204; re-index as above |
| GET | `/api/agents/{id}/capability` | → `{status, built_at, error, summary, skills, tools, knowledge, generated_examples}` or 404 `not_routable` |
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
| GET | `/api/insights/clusters` | query `agent_id?` → `{items: [cluster + weekly_escalations, est_weekly_cost_usd, dislike_count, signal_count, ready_for_fix, label, snoozed_until]}`; `dislike_count` = member calls with a thumbs down in the last 28 days, `signal_count` = distinct member escalations plus thumbs-down calls in that window ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)) |
| GET | `/api/insights/clusters/{id}` | cluster + member calls (analysis + resolution notes + `feedback`) + proposals; every cluster (list and detail) also carries `human_answer`, `reopened_at`, `needs_answer` (a `missing_knowledge` cluster with no specialist note and no `human_answer`) and `fix` (`{proposal_id, version, decided_at, before_per_week, after_per_week, held}` or `null`, [/architecture/learning-actions.md](/architecture/learning-actions.md)) |
| POST | `/api/insights/clusters/{id}/draft-fix` | → `{job_id}` (proposal arrives via `proposal.updated` event); 409 if not ready; 409 `answer_needed` when `needs_answer` |
| POST | `/api/insights/clusters/{id}/ignore` | → cluster |
| GET | `/api/proposals/{id}` | proposal (with `origin`) + draft doc + `original_doc` (the article a `knowledge_edit` revises, else `null`) + latest eval run (summary with its gate + results, each with `repeat`, `failures`, `call_id` and `scenario_name`) |
| PUT | `/api/proposals/{id}` | `{title?, payload?}` → proposal (status back to `draft`) |
| POST | `/api/proposals/{id}/evaluate` | → `{eval_run_id}` |
| GET | `/api/insights/inbox` | query `agent_id?` → `{items: [proposal + cluster name + latest eval summary with its gate]}`: proposals in `ready` that nobody decided, newest first ([/architecture/self-learning.md](/architecture/self-learning.md), Review) |
| GET | `/api/learning/runs` | → `{items: [{id, trigger, status, since, summary, started_at, finished_at}]}`, newest first, at most 30 |
| POST | `/api/learning/run` | → `{learning_run_id}`; 409 `run_in_progress` |
| POST | `/api/proposals/{id}/approve` | `{decided_by, note?, force?}` → `{proposal, version, draft_kept}` (the version is the published config plus the change; `draft_kept` is true when the builder's unpublished draft edits were kept as a draft, CP-0033); 409 `evaluation_gate` when the gate failed and no `force` with a note ([/architecture/fleet-learning.md](/architecture/fleet-learning.md)) |
| POST | `/api/proposals/{id}/reject` | `{decided_by, note}` → proposal |
| GET | `/api/insights/actions` | query `agent_id?`, `status?` (default `open`; `all`) → `{items: [{id, agent_id, agent_name, kind, key, severity, status, title, detail, evidence, impact, closed_by, note, closed_at, created_at, updated_at}]}`, ranked ([/architecture/learning-actions.md](/architecture/learning-actions.md)) |
| POST | `/api/actions/{id}/done` | `{by, note?}` → action; 409 `invalid_state` unless open |
| POST | `/api/actions/{id}/dismiss` | `{by, note?}` → action; 409 `invalid_state` unless open |
| POST | `/api/actions/{id}/answer` | `{answer, by}` → action (an open `answer_needed`; queues `draft_and_evaluate`); 422 `answer_too_short` under 20 characters; 409 `invalid_state` for another kind or a closed action |

## Evaluation
| Method | Path | Body / query → Result |
|---|---|---|
| GET | `/api/test-runs/{id}` | → run + `results: [{scenario_id, scenario, repeat, passed, failures, call_id, scorecard: {score, hard_fail, failed_checks}}]` |
| GET | `/api/evaluation/summary` | query `agent_id` (required), `days` (7\|28\|90, default 28), `include_seed=true` → `{versions: [{version_id, version, published_at, calls, scored, containment_rate, correct_escalation_rate, unnecessary_escalation_rate, abandonment_rate, hard_fail_calls, thumbs_up_rate, first_response_ms, latency_p50_ms, latency_p95_ms, drift: ["goal_met"\|"grounded"\|"containment"], check_pass_rates: {key: rate}}], checks: [{key, group, method, hard_gate, text, pass_rate, decided, reviews, agreement, catch_rate, baseline, calibrated}], daily: [{date, calls, containment_rate, goal_met_rate, grounded_rate, hard_fails}]}`; rates are 0–1 or `null` without data; another `days` → 422 `invalid_days` ([/architecture/call-scoring.md](/architecture/call-scoring.md)) |
| GET | `/api/evaluation/scorecards` | query `agent_id` (required), `version_id?`, `check?` (key), `verdict?`, `hard_fail?`, `reviewed?`, `days`, `include_seed=true` → `{items: [{call_id, started_at, version, outcome, feedback, score, hard_fail, judged, failed_checks: [key], review_count}]}`, newest first, at most 200 |
| GET | `/api/routing/cases` | query `scope?` → `{items: [{id, utterance, expected_agent_id, expected_agent_name, scope, source, enabled}]}` ([/architecture/capability-catalog.md](/architecture/capability-catalog.md)) |
| POST | `/api/routing/cases` | `{utterance, expected_agent_id, enabled?}` → case (`source: manual`, scope from the agent); 422 when the agent is not routable; 409 `too_many_cases` (500) |
| PUT / DELETE | `/api/routing/cases/{id}` | any subset → case / 204 |
| POST | `/api/routing/runs` | `{compare?: bool}` → `{eval_run_id}`; with `compare` the run scores both routing modes ([/architecture/capability-catalog.md](/architecture/capability-catalog.md), CAT-09); 409 `run_in_progress` |
| GET | `/api/routing/runs` | → `{items: [{id, trigger, status, summary, created_at, finished_at}]}`, newest first, at most 50 |
| GET | `/api/routing/runs/{id}` | → run + `results: [{case_id, utterance, expected_agent_id, chosen_agent_id, method, confidence, passed, latency_ms}]` |
| GET | `/api/routing/summary` | query `days` (7\|28\|90) → `{decisions, by_method, stage_b_rate, fallback_rate, clarification_rate, misroute_rate, transfers_per_conversation, decision_ms: {p50, p95}, by_agent: [...]}` ([/architecture/agent-transfer.md](/architecture/agent-transfer.md)) |
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
- **API-10** — Given `POST /api/api-keys`, then only that response contains the key; `PUT` cannot change the scope (422); `DELETE` revokes it and the key then gets 401 on `/v1`; a 21st active key is 409 `too_many_keys`.
- **API-11** — Given the use-case endpoints, when a use case is created, edited and deleted for a published agent, then each change is listed by `GET /api/use-cases?agent_id=` and queues one `index_capabilities` job for that agent.
- **API-12** — Given a playground conversation created with `POST /api/conversations`, then it appears in `GET /api/conversations` with `source: playground`, its segments appear in `GET /api/calls?conversation_id=` with `segment` and `routed_by`, and it never produces webhooks.
- **API-15** — Given an open `check_failing` action, when `POST /api/actions/{id}/dismiss` is sent, then it is `dismissed` with `closed_by` and `closed_at`, a second dismiss returns 409 `invalid_state`, `GET /api/insights/actions` no longer lists it and `?status=all` does; `POST /api/actions/{id}/answer` on it returns 409; another tenant gets 404.
- **API-14** — Given `POST /api/knowledge/sources` for the fixture site, then the response is 202 with `status: indexing` and exactly one `sync_knowledge_source` job is queued; `GET /api/knowledge/sources/{id}` shows `page_count` rising until `ready`; a second `POST …/sync` while the first runs answers 409 `sync_in_progress`; another tenant gets 404.
- **API-13** — Given `PUT /api/tenant-settings/front-desk` with a default member agent that is internal, a pipeline the tenant does not allow, or `max_clarifications: 3`, then the response is 422 and nothing changes; `GET` on a tenant without settings returns the defaults.
