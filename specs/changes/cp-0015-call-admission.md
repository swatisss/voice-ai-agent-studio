---
type: Change Proposal
title: CP-0015 Call admission
description: One admission step decides whether a voice call may start (pipeline allowed, credential available) for the REST call start, the voice sockets and the Twilio webhook; voice calls with no usable key are refused up front.
status: stable
cp_state: implemented
tags: [architecture, voice, telephony, tenancy]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-27T00:00:00Z" }
---

# Why

The architecture review of 2026-10-27 found the call-start decision written three times, each slightly different:

* `routes/calls.py` `start_call` checks the pipeline allowlist (CP-0014) for voice calls but never a key, so it creates a call row that then fails when the socket opens.
* `routes/calls.py` `serve_voice` checks the allowlist again, resolves the provider key (Deepgram, or the tenant/platform OpenAI key of MT-11) and writes `openai_key_source`.
* `routes/telephony.py` `voice_webhook` checks the allowlist and resolves the realtime key, then `serve_voice` resolves it a second time on the stream.
* `pipeline_of(version.config)` plus loading the version is repeated in all three and in `live_settings`.

Every new rule (CP-0014 added one) has to be added in three places and tested through three transports.

# What changes

* A **call admission** step ([/architecture/call-admission.md](/architecture/call-admission.md)) decides once: pipeline allowed, credential available, and returns a refusal reason or a call plan (pipeline, credential source, speech model). The plan is stored on the call; the key itself never is.
* `POST /api/calls` with `channel: voice` now also refuses with **409 `voice_unavailable`** when the pipeline has no usable key (chosen in review: "refuse up front"). No call row is created.
* The voice socket reads the key from the plan's source only: no switch between tenant and platform key mid-call.
* `settings.openai_key_source` is present from call creation instead of from socket connect.
* The three routes keep only the transport mapping (409 / close 4500 / "not in service" TwiML).

# Affected specs

* [/architecture/call-admission.md](/architecture/call-admission.md) - **new**: the decision, the mapping per path, one resolution per call; ADM-01…ADM-05
* [/architecture/tenant-settings.md](/architecture/tenant-settings.md) - the enforcement table points at admission; resolution order unchanged
* [/architecture/telephony.md](/architecture/telephony.md) - webhook step 2 delegates the pipeline and key checks to admission
* [/architecture/realtime-voice.md](/architecture/realtime-voice.md) - key resolution sentence points at admission
* [/api/rest-api.md](/api/rest-api.md) - `POST /api/calls` 409 `voice_unavailable`; `openai_key_source` from call creation
* [/process/conventions.md](/process/conventions.md) - new acceptance prefix `ADM`
* [/architecture/index.md](/architecture/index.md) - entry

# Acceptance criteria

New: ADM-01…ADM-05. Unchanged and still valid (now satisfied through admission): VO-05, RV-03, MT-08, MT-11, TEL-03, RV-16.

# Tasks

1. Spec edits (this CP).
2. `voiceai/admission.py`: the decision (pure over tenant settings, settings and the version config) — covers ADM-01.
3. `POST /api/calls`, `serve_voice`, the Twilio webhook and stream call admission and map refusals; plan stored in `meta.admission`; remove the duplicated checks — covers ADM-02, ADM-03, ADM-05.
4. The socket reads the key from the planned source only — covers ADM-04.
5. Tests: one decision-table test for admission; one transport test per path for the mapping; existing VO-05, RV-03, MT-08, MT-11, TEL-03 tests keep passing.

# Risks and rollout

* **Depends on CP-0014** (allowlist and tenant keys) being committed first.
* **Behaviour change in the Test call page:** a voice call with no key now fails at "Start call" with a 409 instead of when the socket opens; the page already shows API errors as a toast, which is all it does for `voice_unavailable` (decided in review: no special UI).
* Calls created before this change have no plan; they are admitted at the socket.

# Out of scope

* Admission for text calls or evaluation runs.
* Telephony checks that are not about the pipeline (unmapped number, unpublished agent, outbound agents do not answer) stay in the webhook.
* Concurrency limits or per-tenant quotas at admission.
