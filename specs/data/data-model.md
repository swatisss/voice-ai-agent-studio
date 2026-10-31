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

**tenant_settings** — `tenant_id` (PK, FK `tenants.id`), `allowed_pipelines` JSON list, `openai_platform_fallback` bool, `updated_at`; no row means the defaults ([/architecture/tenant-settings.md](/architecture/tenant-settings.md))

**tenant_credentials** — `id`, `tenant_id`, `provider` (`openai`; unique with `tenant_id`), `ciphertext` (Fernet token, never the plain key), `last4`, `created_at`, `updated_at`

**agents** — `id`, `tenant_id`, `name`, `description`, `draft_config` JSON ([/data/agent-config.md](/data/agent-config.md)), `published_version_id` (nullable FK), `created_at`, `updated_at`

**personas** — `id`, `tenant_id`, `name`, `description`, `voice`, `speed` float, `greeting`, `disclosure`, `opening`, `style`, `created_at`, `updated_at` ([/architecture/personas.md](/architecture/personas.md))

**agent_versions** — `id`, `tenant_id`, `agent_id`, `version` int (1..n per agent, unique with agent_id), `config` JSON (snapshot), `change_note`, `source_proposal_id` (nullable), `created_at`

**tools** — `id`, `tenant_id`, `name` (unique per tenant), `description`, `method`, `url`, `parameters` JSON, `requires_verification` bool, `is_verification` bool, `timeout_s` int, `status` (`active`|`draft`), `created_at`, `updated_at`

**skills** — `id`, `tenant_id`, `name`, `description`, `instructions` text, `required_tools` JSON list, `escalate_when` text, `status` (`active`|`draft`), `created_at`, `updated_at`

**knowledge_docs** — `id`, `tenant_id`, `title`, `source_type` (`text`|`file`|`url`|`okf`|`proposal`), `source_ref`, `content` text, `meta` JSON, `status` (`active`|`draft`|`archived`), `created_at`

**knowledge_chunks** — `id`, `tenant_id`, `doc_id` (FK, cascade delete), `ordinal`, `heading`, `content`, `embedding` JSON (list of float)

**calls** — `id`, `tenant_id`, `agent_id`, `agent_version_id`, `channel` (`voice`|`text`|`simulation`), `direction` (`inbound`|`outbound`|`internal`), `status` (`active`|`escalated`|`ended`), `outcome` (nullable: `resolved`|`escalated`|`abandoned`), `caller_ref` (nullable), `started_at`, `ended_at`, `end_reason` (`end_call`|`farewell`|`handoff`|`idle`|`max_duration`|`hangup`|`error`), `turn_count`, `tokens_in`, `tokens_out`, `llm_cost_usd` float, `latency_p50_ms` (nullable), `is_seed` bool, `is_eval` bool, `meta` JSON (`state`, `history`, the live overrides `live.persona_id` and `live.turn_detection`, `context` for outbound calls, `telephony` for phone calls: `{provider, call_sid, from_last4, to}`, and `identification` when the calling number is registered: `{member_ref, first_name, method, attestation}`)

**call_feedback** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `rating` (`up`|`down`), `comment` (nullable, ≤ 300 chars), `created_at`, `updated_at`; one row per call, replaced when the caller answers again; never created for simulation calls ([/architecture/call-ending-and-feedback.md](/architecture/call-ending-and-feedback.md))

**call_events** — `id`, `tenant_id`, `call_id` (indexed), `seq` int (1..n per call), `at`, `kind` (`user`|`assistant`|`tool_call`|`tool_result`|`system`), `text` (nullable), `data` JSON (tool name/args/result, `latency_ms`, usage)

**escalations** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `status` (`waiting`|`accepted`|`resolved`), `reason_category`, `reason_detail`, `packet` JSON (nullable), `packet_status` (`pending`|`ready`|`fallback`), `assignee` (nullable), `disposition` (nullable), `resolution_note` (nullable), `created_at`, `accepted_at`, `resolved_at`

**call_analyses** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `outcome`, `intent`, `root_cause`, `fixable` bool, `gap_summary`, `caller_goal`, `resolution_summary`, `sentiment_start`, `sentiment_end`, `embedding` JSON (nullable), `cluster_id` (nullable), `source` (`llm`|`seed`), `created_at`

**clusters** — `id`, `tenant_id`, `agent_id`, `name`, `description`, `root_cause`, `fixable` bool, `centroid` JSON, `call_count`, `escalation_count`, `first_seen_at`, `last_seen_at`, `status` (`open`|`fix_proposed`|`fixed`|`ignored`), `created_at`, `updated_at`

**fix_proposals** — `id`, `tenant_id`, `agent_id`, `cluster_id`, `kind` (`knowledge_article`|`skill`|`policy_rule`), `title`, `rationale`, `payload` JSON, `draft_doc_id` (nullable), `status` (`draft`|`evaluating`|`ready`|`approved`|`rejected`), `latest_eval_run_id` (nullable), `resulting_version_id` (nullable), `decided_by`, `decision_note`, `created_at`, `decided_at`

**eval_runs** — `id`, `tenant_id`, `agent_id`, `kind` (`proposal`|`suite`, default `proposal`), `proposal_id` (nullable; set for proposal runs), `baseline_version_id` (nullable for a suite run on a draft of an unpublished agent; for suite runs the version the target is based on), `target` (`published`|`draft`|`version`, suite runs), `config` JSON (suite runs: the resolved config simulated), `repeats` int (default 1), `trigger` (`manual`|`builder`|`publish`|`proposal`), `scenario_ids` JSON list, `status` (`running`|`done`|`failed`), `summary` JSON, `error`, `created_at`, `finished_at` ([/architecture/test-suites.md](/architecture/test-suites.md))

**eval_results** — `id`, `tenant_id`, `eval_run_id`, `case_key`, `case_type` (`cluster`|`regression`|`suite`), `arm` (`baseline`|`candidate`|`target`), `scenario_id` (nullable), `repeat` int (1..k, default 1), `scenario` JSON (suite runs: the scenario as it ran), `call_id`, `expected`, `passed` bool, `failures` JSON list of strings, `judge` JSON, `created_at`

**eval_scenarios** — `id`, `tenant_id`, `agent_id`, `name`, `caller_goal`, `caller_profile` JSON, `persona` (`calm`|`confused`|`impatient`|`adversarial`, default `calm`), `expected` (`resolved`|`escalated`), `required_tools` JSON, `forbidden_tools` JSON, `expected_results` JSON, `memory` JSON list, `enabled` bool, `created_at`, `updated_at`; existing rows get the defaults on start (empty lists, `enabled: true`)

**call_scorecards** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `agent_version_id`, `measures` JSON, `checks` JSON list (`{key, group, method, hard_gate, text, verdict, reason, evidence}`), `hard_fail` bool, `score` float (nullable), `judged` bool, `judge_model` (nullable), `source` (`llm`|`seed`), `created_at`, `updated_at` ([/architecture/call-scoring.md](/architecture/call-scoring.md))

**check_reviews** — `id`, `tenant_id`, `scorecard_id`, `call_id`, `agent_id`, `check_key` (unique with `scorecard_id`), `judge_verdict` (copied when reviewed), `verdict` (`pass`|`fail`|`n/a`), `note` (nullable, ≤ 300 chars), `reviewer`, `created_at`, `updated_at`

**use_cases** — `id`, `tenant_id`, `agent_id`, `category`, `title`, `summary`, `channels` JSON list, `sample_utterances` JSON list, `demo_callers` JSON list, `sort` int, `created_at` ([/product/use-cases.md](/product/use-cases.md))

**phone_numbers** — `id`, `tenant_id`, `e164` (unique across all tenants), `agent_id`, `label` (nullable), `created_at`; routes an inbound phone number to the agent's published version ([/architecture/telephony.md](/architecture/telephony.md))

**member_memories** — `id`, `tenant_id`, `agent_id`, `member_ref` (indexed with `tenant_id`, `agent_id`), `kind` (`episode`|`fact`), `category`, `text`, `status` (`active`|`retired`), `valid_at`, `invalid_at` (nullable), `superseded_by` (nullable), `expires_at`, `source_call_id`, `source_seq` (nullable), `embedding` JSON, `prompt_version`, `created_at`, `updated_at` ([/architecture/agent-memory.md](/architecture/agent-memory.md))

**memory_events** — `id`, `tenant_id`, `agent_id` (nullable for erasure), `member_ref`, `memory_id` (nullable), `action` (`added`|`superseded`|`confirmed`|`restored`|`expired`|`erased`), `actor` (`agent`|`studio`|`system`), `call_id` (nullable), `text_before`, `text_after`, `reason` (all nullable; emptied by expiry and erasure), `at`

**jobs** — `id`, `tenant_id`, `kind`, `payload` JSON, `dedupe_key` (nullable, indexed), `status` (`queued`|`running`|`done`|`failed`), `attempts`, `last_error`, `run_after`, `created_at`, `updated_at`

# Relationships

```
tenant ─┬─ agent ─┬─ agent_version ── call ─┬─ call_event
        │         │                         ├─ escalation
        │         │                         ├─ call_scorecard ── check_review
        │         │                         └─ call_analysis ── cluster ── fix_proposal ── eval_run ── eval_result
        │         └─ eval_scenario
        ├─ tool, skill, knowledge_doc ── knowledge_chunk
        └─ job
```

# Acceptance

- **DM-01** — Given a fresh database, when the app starts, then all 27 tables exist and `eval_runs`, `eval_results` and `eval_scenarios` have the CP-0021 columns (added with their defaults to an existing database); given an existing database without `call_feedback`, `phone_numbers`, `tenant_settings`, `tenant_credentials`, `member_memories`, `memory_events`, `call_scorecards` or `check_reviews`, when the app starts, then those tables are created and existing rows are untouched.
- **DM-02** — Given an agent, when two versions are published, then their `version` numbers are 1 and 2 and both configs are retained unchanged.
- **DM-03** — Given a knowledge doc is deleted, then its chunks are deleted.
