---
type: Change Proposal
title: CP-0014 Tenant pipeline allowlist and per-tenant OpenAI key
description: Realtime speech-to-speech becomes opt-in per tenant (enforced on save, publish and call start), and a tenant can run its realtime calls on its own encrypted OpenAI key with optional platform fallback.
status: stable
cp_state: implemented
tags: [tenancy, security, realtime, openai]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Why

CP-0012 made the voice pipeline a per-agent choice. On a multi-tenant platform that leaves two gaps:

1. **No tenant-level control.** Any tenant can move any agent to the realtime pipeline. The realtime pipeline costs more per minute, controls exact wording less tightly, and its HIPAA/BAA coverage is not yet confirmed in writing (research note 12 in `.scratch/speech-to-speech-voice/research/`). It should be switched on per business unit, deliberately, for example for a benefits Q&A pilot only.
2. **One OpenAI account for everyone.** `gateway.provider_key("openai")` reads the platform `OPENAI_API_KEY`. A tenant that has its own OpenAI agreement, data-retention settings or budget cannot use it, and all tenants share one rate limit and one bill.

# What changes

* Each tenant has **settings**: `allowed_pipelines` (default `["cascade"]`, `cascade` always included) and `openai_platform_fallback` (default `true`).
* Saving or publishing an agent on the realtime pipeline needs the tenant to allow it (422 `pipeline_not_allowed`). Voice calls, voice sockets and the Twilio webhook check it again at call start. Dropping `realtime` while an agent still uses it is refused (409 `pipeline_in_use`). Existing tenants that already run a realtime agent are allowed it automatically at startup.
* A tenant can store **its own OpenAI key**, write-only, encrypted with Fernet under a new platform secret `TENANT_SECRETS_KEY`. Realtime calls use the tenant key, else the platform key if fallback is on, else they are unavailable. The call records which key served it.
* A new **Settings** page (eighth navigation item) shows and edits both; the builder's *Realtime* card is disabled with a pointer to Settings when the tenant does not allow it.

# Affected specs

* [/architecture/tenant-settings.md](/architecture/tenant-settings.md) - **new**: settings, enforcement points, key resolution, secret storage; MT-05…MT-12
* [/architecture/multi-tenancy.md](/architecture/multi-tenancy.md) - isolation rule 7 (credentials), link to tenant settings
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md) - keys needed, configuration and selection now go through tenant settings; RV-03 reworded, RV-16 added
* [/architecture/telephony.md](/architecture/telephony.md) - webhook checks allowlist and the tenant's key resolution; TEL-03 widened
* [/architecture/deployment.md](/architecture/deployment.md) - `TENANT_SECRETS_KEY` secret
* [/architecture/tech-stack.md](/architecture/tech-stack.md) - `cryptography` package
* [/data/data-model.md](/data/data-model.md) - `tenant_settings`, `tenant_credentials`; 23 tables; DM-01 reworded
* [/data/agent-config.md](/data/agent-config.md) - `voice.pipeline` must be allowed by the tenant
* [/api/rest-api.md](/api/rest-api.md) - tenant settings and key endpoints, `settings.openai_key_source`, new errors
* [/ui/settings.md](/ui/settings.md) - **new** page; UI-40
* [/ui/app-shell.md](/ui/app-shell.md) - Settings navigation item; UI-29 reworded (eight items)
* [/ui/agent-builder.md](/ui/agent-builder.md) - Realtime card disabled when not allowed; UI-41
* [/demo-data/evergreen-health.md](/demo-data/evergreen-health.md) - seeded settings per tenant; UC-06

# Acceptance criteria

New: MT-05…MT-12 ([tenant settings](/architecture/tenant-settings.md)), RV-16, UI-40, UI-41, UC-06. Reworded: RV-03, TEL-03, DM-01, UI-29.

# Tasks

1. Spec edits (this CP).
2. Data model: `tenant_settings` and `tenant_credentials` models; startup grandfathering of tenants with realtime agents — covers DM-01, MT-12.
3. `voiceai/secrets.py` (Fernet encrypt/decrypt from `TENANT_SECRETS_KEY`), `cryptography` dependency, setting in `config.py`, `.env.example`, `scripts/setup.py` generates the key — covers MT-09, MT-10.
4. Tenant settings repository and routes `GET/PUT /api/tenant-settings`, `PUT/DELETE /api/tenant-settings/openai-key` — covers MT-05, MT-07, MT-09.
5. Enforcement in agent save/publish, `POST /api/calls`, `serve_voice` and the Twilio webhook — covers MT-06, MT-08, TEL-03.
6. Tenant-aware OpenAI key resolution for the realtime pipeline (`serve_voice`, telephony pre-check), `settings.openai_key_source` on the call — covers MT-11, RV-03, RV-16.
7. Seed: `evergreen-care` allows both pipelines, `evergreen-sandbox` defaults — covers UC-06.
8. Web: Settings page, navigation item, builder Realtime card state, `lib/api.ts` calls — covers UI-29, UI-40, UI-41.
9. Tests citing the IDs above; runbook/deploy script mention of `TENANT_SECRETS_KEY`.

# Risks and rollout

* **Existing databases:** two new tables are created at startup (no migration needed); grandfathering keeps the Insurance Claims Agent working without `seed --reset`.
* **Lost `TENANT_SECRETS_KEY`:** stored tenant keys become unreadable; tenants fall back to the platform key if allowed, else realtime calls are unavailable until the key is saved again. Rotation is out of scope.
* **No authentication in v1:** anyone who can select a tenant can replace its key or allow realtime. The key cannot be read back. Acceptable for the demo; must be revisited with auth.
* **Deploy:** `infra/deploy-cloudrun.sh` attaches `TENANT_SECRETS_KEY` when the secret exists; without it, tenants simply cannot store keys.

# Out of scope

* Per-tenant keys for chat roles (Groq, OpenRouter, OpenAI chat), Deepgram or Twilio.
* Testing a key against OpenAI on save; key rotation or re-encryption; per-tenant Secret Manager entries.
* Tracking BAA status per tenant, per-tenant spend limits or quotas.
* Authentication and roles for who may change settings.
