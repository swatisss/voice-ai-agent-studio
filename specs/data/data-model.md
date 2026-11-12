---
type: Data Model
title: Data model
description: All tables, columns, enums and relationships of the platform; portable across SQLite and Postgres.
status: stable
tags: [data, schema]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Conventions

* IDs: 32-char lowercase hex UUIDs (`uuid4().hex`), except `tenants.id` (slug).
* Timestamps: timezone-aware UTC, column suffix `_at`.
* JSON columns use SQLAlchemy `JSON` (TEXT on SQLite, JSON on Postgres).
* Every table except `tenants` has `tenant_id` (FK `tenants.id`, indexed, not null).
* Schema is created with `metadata.create_all` at startup (v1 has no migrations; schema changes need a CP and `seed --reset`).

# Tables

**tenants** — `id` (slug PK), `name`, `industry`, `created_at`

**tenant_settings** — `tenant_id` (PK, FK `tenants.id`), `allowed_pipelines` JSON list, `openai_platform_fallback` bool, `front_desk` JSON (nullable; [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)), `updated_at`; no row means the defaults ([/architecture/tenant-settings.md](/architecture/tenant-settings.md))

**tenant_credentials** — `id`, `tenant_id`, `provider` (`openai`; unique with `tenant_id`), `ciphertext` (Fernet token, never the plain key), `last4`, `created_at`, `updated_at`

**api_keys** — `id`, `tenant_id`, `name` (unique per tenant), `prefix` (first 12 chars), `key_hash` (SHA-256 hex, unique), `scope` (`member`|`staff`), `rate_limit_per_min` int, `max_concurrent_voice` int, `created_at`, `last_used_at` (nullable), `revoked_at` (nullable) ([/api/public-api.md](/api/public-api.md))

**webhook_endpoints** — `id`, `tenant_id`, `url`, `events` JSON list, `include_transcript` bool, `enabled` bool, `secret_ciphertext` (Fernet), `previous_secret_ciphertext` (nullable, kept 24 h), `secret_rotated_at`, `created_at`, `updated_at` ([/architecture/webhooks.md](/architecture/webhooks.md))

**webhook_deliveries** — `id`, `tenant_id`, `endpoint_id`, `event_id` (`evt_…`), `type`, `conversation_id`, `payload` JSON, `status` (`pending`|`delivered`|`failed`), `attempts` int, `last_status_code` (nullable), `last_error` (nullable), `next_attempt_at`, `created_at`, `delivered_at` (nullable)

**conversations** — `id`, `tenant_id`, `source` (`api`|`playground`|`phone`), `api_key_id` (nullable), `channel` (`text`|`voice`), `transport` (`text`|`websocket`|`media-stream`|`webrtc`|`twilio`|`browser`), `scope` (`member`|`staff`), `status` (`active`|`escalated`|`ended`), `outcome` (nullable, the last segment's), `end_reason` (nullable), `external_id` (nullable, ≤ 128), `metadata` JSON, `current_call_id` (nullable), `transfer_count` int, `clarifications` int, `routing` JSON list (decisions, [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md)), `settings` JSON (the conversation's persona, voice and pipeline), `started_at`, `ended_at`

**capability_profiles** — `id`, `tenant_id`, `agent_id` (unique), `agent_version_id`, `scope`, `card` JSON (name, description, skills, tools, knowledge, generated examples), `summary`, `input_hash`, `status` (`ready`|`indexing`|`failed`), `error` (nullable), `built_at` ([/architecture/capability-catalog.md](/architecture/capability-catalog.md))

**capability_entries** — `id`, `tenant_id`, `agent_id` (indexed), `profile_id` (FK, cascade delete), `kind` (`description`|`use_case`|`utterance`|`generated`|`tool`), `ref` (use case id or tool name, nullable), `text`, `embedding` JSON

**routing_cases** — `id`, `tenant_id`, `utterance` (≤ 300), `expected_agent_id`, `scope`, `source` (`generated`|`manual`), `use_case_id` (nullable, generated cases), `enabled` bool, `created_at`, `updated_at`

**agents** — `id`, `tenant_id`, `name`, `description`, `draft_config` JSON ([/data/agent-config.md](/data/agent-config.md)), `published_version_id` (nullable FK), `created_at`, `updated_at`

**personas** — `id`, `tenant_id`, `name`, `description`, `voice`, `speed` float, `greeting`, `disclosure`, `opening`, `style`, `created_at`, `updated_at` ([/architecture/personas.md](/architecture/personas.md))

**agent_versions** — `id`, `tenant_id`, `agent_id`, `version` int (1..n per agent, unique with agent_id), `config` JSON (snapshot), `change_note`, `source_proposal_id` (nullable), `published_by` (nullable; the signed-in publisher, "Studio" with sign-in off, [/architecture/studio-auth.md](/architecture/studio-auth.md)), `created_at`

**tools** — `id`, `tenant_id`, `name` (unique per tenant), `description`, `method`, `url`, `parameters` JSON, `requires_verification` bool, `is_verification` bool, `timeout_s` int, `status` (`active`|`draft`), `created_at`, `updated_at`

**skills** — `id`, `tenant_id`, `name`, `description`, `instructions` text, `required_tools` JSON list, `escalate_when` text, `status` (`active`|`draft`), `created_at`, `updated_at`

**knowledge_docs** — `id`, `tenant_id`, `title`, `source_type` (`text`|`file`|`url`|`okf`|`proposal`), `source_ref`, `content` text, `meta` JSON, `status` (`active`|`draft`|`archived`), `created_at`

**knowledge_chunks** — `id`, `tenant_id`, `doc_id` (FK, cascade delete), `ordinal`, `heading`, `content`, `embedding` JSON (list of float), `content_hash` (SHA-256 of the doc content the chunk was cut from; nullable for chunks made before CP-0031)

**knowledge_sources** — `id`, `tenant_id`, `kind` (`website`), `title`, `start_url`, `scope` (`page`|`section`), `max_pages`, `refresh` (`off`|`daily`|`weekly`), `status` (`indexing`|`ready`|`partial`|`failed`|`archived`), `page_count`, `found_count`, `last_synced_at`, `next_sync_at`, `last_run` JSON (added, changed, unchanged, archived, skipped `[{url, reason}]`), `error`, `created_at`, `updated_at` ([/architecture/knowledge.md](/architecture/knowledge.md), CP-0031). `knowledge_docs` gains a nullable `source_id` (FK), `miss_count` (consecutive syncs that found the page gone) and `updated_at` (null for docs made before CP-0031).

**calls** — `id`, `tenant_id`, `agent_id`, `agent_version_id`, `channel` (`voice`|`text`|`simulation`), `direction` (`inbound`|`outbound`|`internal`), `status` (`active`|`escalated`|`ended`), `outcome` (nullable: `resolved`|`escalated`|`abandoned`|`transferred`), `caller_ref` (nullable), `started_at`, `ended_at`, `end_reason` (`end_call`|`farewell`|`handoff`|`idle`|`max_duration`|`hangup`|`error`|`transfer`), `turn_count`, `tokens_in`, `tokens_out`, `llm_cost_usd` float, `latency_p50_ms` (nullable), `is_seed` bool, `is_eval` bool, `conversation_id` (nullable, indexed), `segment` int (nullable; 1..n within a conversation), `routed_by` (nullable: `explicit`|`single`|`embedding`|`decision`|`llm`|`clarified`|`default`|`transfer`), `meta` JSON (`routing` for a routed segment, `handoff` `{reason, summary, from_call_id}` for a transferred one, `state`, `history`, the live overrides `live.persona_id` and `live.turn_detection`, `context` for outbound calls, `telephony` for phone calls: `{provider, call_sid, from_last4, to}`, and `identification` when the calling number is registered: `{member_ref, first_name, method, attestation}`)

**call_feedback** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `rating` (`up`|`down`), `comment` (nullable, ≤ 300 chars), `created_at`, `updated_at`; one row per call, replaced when the caller answers again; never created for simulation calls ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md))

**contact_messages** — `id`, `tenant_id`, `call_id` (indexed), `agent_id`, `seq` int (1..3 per call, sending order), `channel` (`email`|`sms`|`call`), `destination` (`registered`|`other`), `to_masked` (≤ 80 chars; the full address is never stored), `subject` (nullable), `body`, `provider` (`brevo`|`twilio`|`outbox`|`simulated`), `status` (`sent`|`outbox`|`simulated`|`failed`), `provider_ref` (nullable), `error` (nullable, ≤ 300 chars), `redirected` bool, `created_at`; one row per confirmed send of a contact tool ([/architecture/contact-tools.md](/architecture/contact-tools.md))

**call_events** — `id`, `tenant_id`, `call_id` (indexed), `seq` int (1..n per call), `at`, `kind` (`user`|`assistant`|`tool_call`|`tool_result`|`system`), `text` (nullable), `data` JSON (tool name/args/result, `latency_ms`, usage)

**escalations** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `status` (`waiting`|`accepted`|`resolved`), `reason_category`, `reason_detail`, `packet` JSON (nullable), `packet_status` (`pending`|`ready`|`fallback`), `assignee` (nullable), `disposition` (nullable), `resolution_note` (nullable), `created_at`, `accepted_at`, `resolved_at`

**call_analyses** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `outcome`, `intent`, `root_cause`, `fixable` bool, `gap_summary`, `caller_goal`, `resolution_summary`, `sentiment_start`, `sentiment_end`, `signals` JSON list (quality signals of a re-analysis, [/architecture/self-learning.md](/architecture/self-learning.md)), `embedding` JSON (nullable), `cluster_id` (nullable), `source` (`llm`|`seed`), `created_at`

**clusters** — `id`, `tenant_id`, `agent_id`, `name`, `description`, `root_cause`, `fixable` bool, `centroid` JSON, `call_count`, `escalation_count`, `first_seen_at`, `last_seen_at`, `status` (`open`|`fix_proposed`|`fixed`|`ignored`), `snoozed_until` (nullable), `human_answer` (nullable text: a reviewer's answer to an `answer_needed` action), `human_answer_by` (nullable), `reopened_at` (nullable: when a run found the fix did not hold), `created_at`, `updated_at`

**fix_proposals** — `id`, `tenant_id`, `agent_id`, `cluster_id`, `kind` (`knowledge_article`|`knowledge_edit`|`tool_attach`|`skill`|`policy_rule`|`routing_update`), `origin` (`manual`|`nightly`, default `manual`), `title`, `rationale`, `payload` JSON (may carry `scenarios`), `draft_doc_id` (nullable), `status` (`draft`|`evaluating`|`ready`|`approved`|`rejected`), `latest_eval_run_id` (nullable), `resulting_version_id` (nullable), `decided_by`, `decision_note`, `created_at`, `decided_at`

**eval_runs** — `id`, `tenant_id`, `agent_id` (nullable; `null` for routing runs), `kind` (`proposal`|`suite`|`routing`, default `proposal`), `proposal_id` (nullable; set for proposal runs), `baseline_version_id` (nullable for a suite run on a draft of an unpublished agent; for suite runs the version the target is based on), `target` (`published`|`draft`|`version`, suite runs), `config` JSON (suite runs: the resolved config simulated), `repeats` int (default 1), `trigger` (`manual`|`builder`|`publish`|`proposal`|`catalog`|`target`), `scenario_ids` JSON list, `status` (`running`|`done`|`failed`), `summary` JSON, `error`, `created_at`, `finished_at` ([/architecture/test-suites.md](/architecture/test-suites.md))

**eval_results** — `id`, `tenant_id`, `eval_run_id`, `case_key`, `case_type` (`cluster`|`regression`|`suite`|`routing`), `arm` (`baseline`|`candidate`|`target`), `scenario_id` (nullable), `repeat` int (1..k, default 1), `scenario` JSON (suite runs: the scenario as it ran), `call_id`, `expected`, `passed` bool, `failures` JSON list of strings, `judge` JSON, `created_at`

**eval_scenarios** — `id`, `tenant_id`, `agent_id`, `name`, `caller_goal`, `caller_profile` JSON, `persona` (`calm`|`confused`|`impatient`|`adversarial`, default `calm`), `language` (`en`|`hi`|`mixed`, default `en`, CP-0037), `expected` (`resolved`|`escalated`), `required_tools` JSON, `forbidden_tools` JSON, `expected_results` JSON, `memory` JSON list, `enabled` bool, `created_at`, `updated_at`; existing rows get the defaults on start (empty lists, `enabled: true`)

**call_scorecards** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `agent_version_id`, `measures` JSON, `checks` JSON list (`{key, group, method, hard_gate, text, verdict, reason, evidence}`), `hard_fail` bool, `score` float (nullable), `judged` bool, `judge_model` (nullable), `source` (`llm`|`seed`), `created_at`, `updated_at` ([/architecture/call-scoring.md](/architecture/call-scoring.md))

**check_reviews** — `id`, `tenant_id`, `scorecard_id`, `call_id`, `agent_id`, `check_key` (unique with `scorecard_id`), `judge_verdict` (copied when reviewed), `verdict` (`pass`|`fail`|`n/a`), `note` (nullable, ≤ 300 chars), `reviewer`, `created_at`, `updated_at`

**use_cases** — `id`, `tenant_id`, `agent_id`, `category`, `title`, `summary`, `channels` JSON list, `sample_utterances` JSON list, `demo_callers` JSON list, `sort` int, `created_at`, `updated_at` ([/product/use-cases.md](/product/use-cases.md); editable, [/architecture/capability-catalog.md](/architecture/capability-catalog.md))

**phone_numbers** — `id`, `tenant_id`, `e164` (unique across all tenants), `target` (`agent`|`front_desk`, default `agent`), `agent_id` (nullable; set for `agent`), `label` (nullable), `created_at`; routes an inbound phone number to the agent's published version or to the front desk ([/architecture/telephony.md](/architecture/telephony.md))

**member_memories** — `id`, `tenant_id`, `agent_id`, `member_ref` (indexed with `tenant_id`, `agent_id`), `kind` (`episode`|`fact`), `category`, `text`, `status` (`active`|`retired`), `valid_at`, `invalid_at` (nullable), `superseded_by` (nullable), `expires_at`, `source_call_id`, `source_seq` (nullable), `embedding` JSON, `prompt_version`, `created_at`, `updated_at` ([/architecture/agent-memory.md](/architecture/agent-memory.md))

**memory_events** — `id`, `tenant_id`, `agent_id` (nullable for erasure), `member_ref`, `memory_id` (nullable), `action` (`added`|`superseded`|`confirmed`|`restored`|`expired`|`erased`), `actor` (`agent`|`studio`|`system`), `call_id` (nullable), `text_before`, `text_after`, `reason` (all nullable; emptied by expiry and erasure), `at`

**learning_runs** — `id`, `tenant_id`, `trigger` (`nightly`|`manual`), `status` (`running`|`done`|`failed`), `since` (start of the reviewed window), `summary` JSON (per agent: calls reviewed, signals by kind, re-analysed, ready clusters, proposals drafted and passed, clusters reopened, actions opened, resolved and open), `error`, `started_at`, `finished_at` ([/architecture/self-learning.md](/architecture/self-learning.md))

**learning_actions** — `id`, `tenant_id`, `agent_id`, `kind` (`fix_not_holding`|`answer_needed`|`check_failing`|`drift`|`scenario_failing`), `key` (the finding, e.g. `check_failing:{version}:{check}`), `severity` (`high`|`medium`), `status` (`open`|`done`|`dismissed`|`resolved`), `title`, `detail`, `evidence` JSON, `impact` (float), `closed_by`, `note`, `closed_at`, `suppressed_until` (nullable), `created_at`, `updated_at` ([/architecture/learning-actions.md](/architecture/learning-actions.md))

**jobs** — `id`, `tenant_id`, `kind`, `payload` JSON, `dedupe_key` (nullable, indexed), `status` (`queued`|`running`|`done`|`failed`), `attempts`, `last_error`, `run_after`, `created_at`, `updated_at`

# Relationships

```
tenant ─┬─ agent ─┬─ agent_version ── call ─┬─ call_event
        │         │                         ├─ escalation
        │         │                         ├─ contact_message
        │         │                         ├─ call_scorecard ── check_review
        │         │                         └─ call_analysis ── cluster ── fix_proposal ── eval_run ── eval_result
        │         ├─ eval_scenario
        │         └─ capability_profile ── capability_entry
        ├─ conversation ── call (segments 1..n)
        ├─ api_key, webhook_endpoint ── webhook_delivery, routing_case
        ├─ tool, skill, knowledge_doc ── knowledge_chunk
        └─ job
```

# Acceptance

- **DM-01** — Given a fresh database, when the app starts, then all 38 tables exist and `eval_runs`, `eval_results` and `eval_scenarios` have the CP-0021 columns (added with their defaults to an existing database); given an existing database without `call_feedback`, `phone_numbers`, `tenant_settings`, `tenant_credentials`, `member_memories`, `memory_events`, `call_scorecards`, `check_reviews`, `learning_runs`, `api_keys`, `conversations`, `webhook_endpoints`, `webhook_deliveries`, `capability_profiles`, `capability_entries`, `routing_cases`, `knowledge_sources`, `learning_actions` or `contact_messages`, when the app starts, then those tables are created and existing rows are untouched.
- **DM-15** — Given an existing database without `contact_messages`, when the app starts, then the table is created and no other table or row changes; a confirmed send stores `to_masked` and never the full address.
- **DM-02** — Given an agent, when two versions are published, then their `version` numbers are 1 and 2 and both configs are retained unchanged.
- **DM-03** — Given a knowledge doc is deleted, then its chunks are deleted.
- **DM-14** — Given an existing database without `agent_versions.published_by`, when the app starts, then the column is added as null and existing versions are unchanged.
- **DM-13** — Given an existing database without `clusters.human_answer`, `clusters.human_answer_by` and `clusters.reopened_at`, when the app starts, then the columns are added as null and existing clusters keep their status.
- **DM-12** — Given an existing database without `knowledge_docs.source_id`, `knowledge_docs.miss_count`, `knowledge_docs.updated_at` and `knowledge_chunks.content_hash`, when the app starts, then the columns are added (null or 0), existing docs have no source, and search over them is unchanged.
- **DM-10** — Given an existing database without the CP-0023…CP-0026 columns (`calls.conversation_id`, `segment`, `routed_by`; `phone_numbers.target`; `tenant_settings.front_desk`; `use_cases.updated_at`; nullable `eval_runs.agent_id` and `phone_numbers.agent_id`), when the app starts, then they are added with their defaults, existing calls have no conversation, existing numbers have target `agent`, and no row is lost.
