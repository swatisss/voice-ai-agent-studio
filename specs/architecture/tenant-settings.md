---
type: Component Spec
title: Tenant settings and credentials
description: Per-tenant voice pipeline allowlist (realtime is opt-in) and a per-tenant OpenAI key for the realtime pipeline - storage, encryption, resolution order and enforcement points.
status: stable
tags: [architecture, tenancy, security, realtime, openai]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Why

The voice pipeline is chosen per agent ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)), but nothing stops any tenant from switching an agent to the realtime pipeline, and every realtime call is paid for and contracted under the single platform `OPENAI_API_KEY`. A multi-tenant platform needs two things per tenant: a decision whether the realtime pipeline may be used at all (it has different cost, wording control and compliance coverage), and the option to run that tenant's realtime calls on the tenant's own OpenAI account.

# Settings

Each tenant has at most one `tenant_settings` row ([/data/data-model.md](/data/data-model.md)). No row means the defaults.

| Setting | Values | Default (no row) |
|---|---|---|
| `allowed_pipelines` | non-empty list from `cascade`, `realtime`; MUST contain `cascade` (it is the default pipeline and the way back) | `["cascade"]` |
| `openai_platform_fallback` | `true`: a realtime call of this tenant uses the platform `OPENAI_API_KEY` when the tenant has no key of its own. `false`: the tenant's own key is required | `true` |

Changing `allowed_pipelines` to drop `realtime` while any agent of the tenant has `voice.pipeline: realtime` in its draft or its published version is refused with 409 `pipeline_in_use`; the error names the agents. Switch them to `cascade` and republish first.

**Existing tenants.** At startup, a tenant without a settings row that already has an agent on the realtime pipeline (draft or published) gets a row with `allowed_pipelines: ["cascade","realtime"]`, so upgrading does not take a working realtime agent off the air. Tenants without such an agent keep the defaults.

# Enforcement points

| Where | Check | Result when not allowed |
|---|---|---|
| `PUT /api/agents/{id}` with a draft whose `voice.pipeline` is `realtime` | tenant allows `realtime` | 422 `pipeline_not_allowed` |
| `POST /api/agents/{id}/publish` | same, on the draft being published | 422 `pipeline_not_allowed` |
| `POST /api/calls` with `channel: voice` | the published version's pipeline is allowed | 409 `pipeline_not_allowed` |
| Voice WebSocket (browser and Twilio stream) at connect | same | close `4500`, reason `pipeline_not_allowed` |
| Twilio voice webhook | same | "not in service" TwiML and `<Hangup/>`, no call row ([/architecture/telephony.md](/architecture/telephony.md)) |

The text channel and evaluation runs of a realtime agent use the text brain ([/architecture/realtime-voice.md](/architecture/realtime-voice.md)) and are not affected by the allowlist.

# Per-tenant OpenAI key

* A tenant MAY store one OpenAI API key (`tenant_credentials`, provider `openai`). It is used **only for the realtime pipeline** (the `speech` role). Chat roles keep using the platform keys of [/architecture/llm-gateway.md](/architecture/llm-gateway.md).
* **Write-only.** The API never returns the key, in any response, event, log line or error. It returns only `key_set`, `key_last4` and `key_updated_at`.
* **Format check on save:** starts with `sk-`, 20–300 characters, no whitespace; otherwise 422 `invalid_key`. The key is not tested against OpenAI on save (no network in this path); a wrong key shows up as a failed call (RV-13).

## Resolution order for a realtime call

1. The tenant's own key, if stored and decryptable → **source `tenant`**.
2. Else, if `openai_platform_fallback` is `true` and the platform `OPENAI_API_KEY` is set → **source `platform`**.
3. Else the pipeline is unavailable: the voice socket closes with `4500 voice_unavailable`, the Twilio webhook answers "not in service".

There is no fallback from a stored tenant key that OpenAI rejects to the platform key: a rejected key fails the call (RV-13), so a tenant's traffic is never silently billed to the platform. The source used is recorded on the call (`settings.openai_key_source`: `tenant` or `platform`, [/api/rest-api.md](/api/rest-api.md)), so cost can be attributed.

## Secret storage

* Keys are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256, Python `cryptography` package) under the platform secret `TENANT_SECRETS_KEY` (a Fernet key: 32 url-safe base64 bytes), read from the environment or `apps/api/.env` like the provider keys. On Cloud Run it comes from Secret Manager ([/architecture/deployment.md](/architecture/deployment.md)).
* `TENANT_SECRETS_KEY` unset → saving a key returns 503 `secrets_unavailable`; already stored keys cannot be decrypted and count as not set (with a warning log, never the ciphertext).
* When `scripts/setup.py` creates `apps/api/.env`, it fills in a newly generated `TENANT_SECRETS_KEY`; an existing `.env` is left untouched (SDD-09) and setup prints the one-line command that generates a key when the file has none. Losing or changing it makes stored keys unreadable; tenants then save their key again.
* v1 has no authentication ([/product/scope.md](/product/scope.md)): whoever can select a tenant can replace or remove its key, but cannot read it back.

# Acceptance

- **MT-05** — Given a tenant with no settings row, when `GET /api/tenant-settings` is requested, then it returns `allowed_pipelines: ["cascade"]`, `openai.platform_fallback: true` and `openai.key_set: false`.
- **MT-06** — Given a tenant whose `allowed_pipelines` is `["cascade"]`, when an agent draft with `voice.pipeline: "realtime"` is saved or published, then the response is 422 `pipeline_not_allowed` and nothing changes; after `realtime` is allowed the same save and publish succeed.
- **MT-07** — Given `PUT /api/tenant-settings` with `allowed_pipelines` that is empty, lacks `cascade` or contains an unknown value, then the response is 422; given it drops `realtime` while an agent of the tenant has `voice.pipeline: "realtime"` in its draft or published version, then the response is 409 `pipeline_in_use` naming that agent and the settings are unchanged.
- **MT-08** — Given a published realtime agent whose tenant no longer allows `realtime` (row changed directly in the database), when a voice call is created, its voice socket opens or its phone number is called, then the responses are 409 `pipeline_not_allowed`, close `4500` with reason `pipeline_not_allowed`, and "not in service" TwiML with no call row; a text call to the same agent still works.
- **MT-09** — Given `PUT /api/tenant-settings/openai-key` with a valid-format key, then the response and every later `GET` contain `key_set: true` and the last four characters only; the stored column does not contain the key in plain text; no response body, stored event or log record of the request contains the key; a key without the `sk-` prefix returns 422 `invalid_key`; `DELETE` returns 204 and `key_set: false` afterwards.
- **MT-10** — Given `TENANT_SECRETS_KEY` unset, when a key is saved, then the response is 503 `secrets_unavailable`; given a key stored under a different `TENANT_SECRETS_KEY`, then it counts as not set.
- **MT-11** — Given a realtime call, then the provider connection uses the tenant's key when one is stored (`openai_key_source: tenant`), else the platform key when `openai_platform_fallback` is true (`platform`), else the socket closes with 4500 `voice_unavailable`; tenant A's key is never used for tenant B's call.
- **MT-12** — Given an existing database where tenant `evergreen-care` has a realtime agent and no settings row, when the app starts, then that tenant's `allowed_pipelines` is `["cascade","realtime"]` and a tenant without realtime agents still has the defaults.
