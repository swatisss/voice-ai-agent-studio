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

**agents** — `id`, `tenant_id`, `name`, `description`, `draft_config` JSON ([/data/agent-config.md](/data/agent-config.md)), `published_version_id` (nullable FK), `created_at`, `updated_at`

**personas** — `id`, `tenant_id`, `name`, `description`, `voice`, `speed` float, `greeting`, `disclosure`, `opening`, `style`, `created_at`, `updated_at` ([/architecture/personas.md](/architecture/personas.md))

**agent_versions** — `id`, `tenant_id`, `agent_id`, `version` int (1..n per agent, unique with agent_id), `config` JSON (snapshot), `change_note`, `source_proposal_id` (nullable), `created_at`

**tools** — `id`, `tenant_id`, `name` (unique per tenant), `description`, `method`, `url`, `parameters` JSON, `requires_verification` bool, `is_verification` bool, `timeout_s` int, `status` (`active`|`draft`), `created_at`, `updated_at`

**skills** — `id`, `tenant_id`, `name`, `description`, `instructions` text, `required_tools` JSON list, `escalate_when` text, `status` (`active`|`draft`), `created_at`, `updated_at`

**knowledge_docs** — `id`, `tenant_id`, `title`, `source_type` (`text`|`file`|`url`|`okf`|`proposal`), `source_ref`, `content` text, `meta` JSON, `status` (`active`|`draft`|`archived`), `created_at`

**knowledge_chunks** — `id`, `tenant_id`, `doc_id` (FK, cascade delete), `ordinal`, `heading`, `content`, `embedding` JSON (list of float)

**calls** — `id`, `tenant_id`, `agent_id`, `agent_version_id`, `channel` (`voice`|`text`|`simulation`), `status` (`active`|`escalated`|`ended`), `outcome` (nullable: `resolved`|`escalated`|`abandoned`), `caller_ref` (nullable), `started_at`, `ended_at`, `end_reason`, `turn_count`, `tokens_in`, `tokens_out`, `llm_cost_usd` float, `latency_p50_ms` (nullable), `is_seed` bool, `is_eval` bool, `meta` JSON (`state`, `history`, and the live overrides `live.persona_id` and `live.turn_detection`)

**call_events** — `id`, `tenant_id`, `call_id` (indexed), `seq` int (1..n per call), `at`, `kind` (`user`|`assistant`|`tool_call`|`tool_result`|`system`), `text` (nullable), `data` JSON (tool name/args/result, `latency_ms`, usage)

**escalations** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `status` (`waiting`|`accepted`|`resolved`), `reason_category`, `reason_detail`, `packet` JSON (nullable), `packet_status` (`pending`|`ready`|`fallback`), `assignee` (nullable), `disposition` (nullable), `resolution_note` (nullable), `created_at`, `accepted_at`, `resolved_at`

**call_analyses** — `id`, `tenant_id`, `call_id` (unique), `agent_id`, `outcome`, `intent`, `root_cause`, `fixable` bool, `gap_summary`, `caller_goal`, `resolution_summary`, `sentiment_start`, `sentiment_end`, `embedding` JSON (nullable), `cluster_id` (nullable), `source` (`llm`|`seed`), `created_at`

**clusters** — `id`, `tenant_id`, `agent_id`, `name`, `description`, `root_cause`, `fixable` bool, `centroid` JSON, `call_count`, `escalation_count`, `first_seen_at`, `last_seen_at`, `status` (`open`|`fix_proposed`|`fixed`|`ignored`), `created_at`, `updated_at`

**fix_proposals** — `id`, `tenant_id`, `agent_id`, `cluster_id`, `kind` (`knowledge_article`|`skill`|`policy_rule`), `title`, `rationale`, `payload` JSON, `draft_doc_id` (nullable), `status` (`draft`|`evaluating`|`ready`|`approved`|`rejected`), `latest_eval_run_id` (nullable), `resulting_version_id` (nullable), `decided_by`, `decision_note`, `created_at`, `decided_at`

**eval_runs** — `id`, `tenant_id`, `agent_id`, `proposal_id`, `baseline_version_id`, `status` (`running`|`done`|`failed`), `summary` JSON, `error`, `created_at`, `finished_at`

**eval_results** — `id`, `tenant_id`, `eval_run_id`, `case_key`, `case_type` (`cluster`|`regression`), `arm` (`baseline`|`candidate`), `call_id`, `expected`, `passed` bool, `judge` JSON, `created_at`

**eval_scenarios** — `id`, `tenant_id`, `agent_id`, `name`, `caller_goal`, `caller_profile` JSON, `expected` (`resolved`|`escalated`), `created_at`

**jobs** — `id`, `tenant_id`, `kind`, `payload` JSON, `dedupe_key` (nullable, indexed), `status` (`queued`|`running`|`done`|`failed`), `attempts`, `last_error`, `run_after`, `created_at`, `updated_at`

# Relationships

```
tenant ─┬─ agent ─┬─ agent_version ── call ─┬─ call_event
        │         │                         ├─ escalation
        │         │                         └─ call_analysis ── cluster ── fix_proposal ── eval_run ── eval_result
        │         └─ eval_scenario
        ├─ tool, skill, knowledge_doc ── knowledge_chunk
        └─ job
```

# Acceptance

- **DM-01** — Given a fresh database, when the app starts, then all 18 tables exist.
- **DM-02** — Given an agent, when two versions are published, then their `version` numbers are 1 and 2 and both configs are retained unchanged.
- **DM-03** — Given a knowledge doc is deleted, then its chunks are deleted.
