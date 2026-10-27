---
type: Component Spec
title: Call admission
description: The one place that decides whether a voice call may start and how it will run - pipeline allowed, provider credential available - used by the REST call start, the voice sockets and the Twilio webhook.
status: stable
tags: [architecture, voice, telephony, tenancy, realtime]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Why one admission step

A voice call can start three ways: `POST /api/calls` (browser Test call), the Twilio voice webhook ([/architecture/telephony.md](/architecture/telephony.md)) and, after either, the voice socket that carries the audio (browser [/api/voice-protocol.md](/api/voice-protocol.md) or Twilio stream). Before this spec each path decided "is this pipeline allowed, is there a usable key" on its own, with different gaps: `POST /api/calls` never checked a key, and a phone call resolved the realtime key twice. Admission is the single rule set; the three paths only translate its answer into their transport.

It lives in its own spec because it spans four others (REST API, telephony, realtime voice, tenant settings) and none of them owns the decision.

# The decision

**Input:** tenant, the agent version's config snapshot, channel (`voice` only; text calls and evaluation runs are not admitted, they never use a voice provider).

**Checks, in order** (the first failure is the refusal):

| # | Check | Refusal reason |
|---|---|---|
| 1 | The version's pipeline (`cascade` unless `voice.pipeline` is `realtime`, RV-01) is in the tenant's `allowed_pipelines` ([/architecture/tenant-settings.md](/architecture/tenant-settings.md)) | `pipeline_not_allowed` |
| 2 | A usable credential exists: `cascade` → `DEEPGRAM_API_KEY`; `realtime` → the tenant's own OpenAI key, else the platform `OPENAI_API_KEY` when the tenant allows the fallback (MT-11) | `voice_unavailable` |

**Result:** a refusal reason, or a **call plan**: `pipeline` (`cascade` | `realtime`), `credential_source` (`platform` for cascade; `tenant` or `platform` for realtime) and, for realtime, the speech `model_ref` (agent's `models.speech` or the role default). The plan never contains the key itself.

# Where it runs and how refusals map

| Path | When | Refusal maps to | On admission |
|---|---|---|---|
| `POST /api/calls` with `channel: voice` | before the call row is created | 409 with the reason as `error` (`pipeline_not_allowed` or `voice_unavailable`); **no call row** | the plan is stored on the call (`meta.admission`) and returned in `settings` |
| Twilio voice webhook | after the number, published version and answering-mode checks of [/architecture/telephony.md](/architecture/telephony.md) | "not in service" TwiML and `<Hangup/>`; no call row | the plan is stored on the call, then the stream TwiML is returned |
| Voice socket (browser or Twilio stream) | when it opens, before any provider connection | close `4500` with the reason as close reason | the provider connection is opened with the credential read **from the plan's `credential_source`** |

**One resolution per call.** The source is chosen once, when the call is created, and stored in the plan. The socket reads the key from that same source only: a call planned on the tenant's key never falls back to the platform key, and vice versa. If the source no longer yields a key when the socket opens (the tenant removed its key, the vault key changed, the platform key was unset), the socket closes with `4500 voice_unavailable`. The allowlist is checked again at the socket (check 1) so a pipeline disabled after the call was created is still refused.

A call created before this spec (no `meta.admission`) is admitted at the socket as if it were new.

`settings.openai_key_source` in call responses ([/api/rest-api.md](/api/rest-api.md)) is the plan's `credential_source` for realtime calls and is present from call creation.

# Acceptance

- **ADM-01** — Given each combination of tenant allowlist (`["cascade"]`, `["cascade","realtime"]`), pipeline (`cascade`, `realtime`), Deepgram key (set, unset), tenant OpenAI key (stored, none) and platform OpenAI key with fallback (set and on, set and off, unset), when admission runs, then it returns `pipeline_not_allowed` when the pipeline is not allowed, else `voice_unavailable` when no credential exists, else a plan whose `credential_source` follows MT-11; the plan never contains a key.
- **ADM-02** — Given a voice agent whose pipeline has no usable credential, when `POST /api/calls` with `channel: voice` is sent, then the response is 409 `voice_unavailable` and no call row exists; the same request with `channel: text` succeeds.
- **ADM-03** — Given the same tenant and agent state, when a voice call is started through `POST /api/calls`, the Twilio webhook and the voice socket, then all three refuse or admit alike, mapped to 409, "not in service" TwiML and close `4500` with the same reason.
- **ADM-04** — Given a realtime call planned on the tenant's own key, when the key is removed before the socket opens, then the socket closes with `4500 voice_unavailable` and no provider connection is attempted with the platform key, even with the fallback on.
- **ADM-05** — Given a realtime phone call admitted by the webhook with `credential_source: platform`, when the tenant stores its own key before the stream opens, then the stream still connects with the platform key (the source is chosen once per call); and `GET /api/calls/{id}` shows `settings.openai_key_source` from the moment the call exists.
