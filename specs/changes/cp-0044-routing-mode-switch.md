---
type: Change Proposal
title: CP-0044 Switch between embedding and decision-model routing in the playground
description: Settings keeps the front desk's routing mode; Full flow gets a per-conversation Embedding | Decision model switch so a tester can compare the two on the same phrase.
status: stable
cp_state: implemented
tags: [routing, playground, front-desk]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The two routing modes behave differently (spike S5: the embedding is fast and rarely wrong but asks often; the decision model, Jev when configured, decides far more requests but takes about 0.5 s). Today the mode is one tenant-wide front-desk setting, so comparing them on a phrase means saving Settings, starting a call, saving again. The owner wants to flip between them where they test.

# What changes

1. **Setup flag.** Already present: Settings → Front desk → **Routing** (*Embedding* | *Decision model*), saved as `front_desk.routing_mode`. Only its help text changes: it is the default for every conversation.
2. **Playground switch.** The Test call page's Full flow gets a **Routing** switch (*Embedding* | *Decision model*) in the top row. It starts on the Settings value, is sent with **Start call** / **Start chat**, and is locked while a conversation is active. *Decision model* is disabled with a reason when the server has none configured or PHI mode blocks it.
3. **Per-conversation override.** `POST /api/conversations` (Studio) accepts `routing_mode`, stored on the conversation and used for every decision of it (start, clarified, transfer). The public `/v1` API does not accept it. Fallbacks to the embedding (not configured, PHI mode, timeout) work exactly as before and are recorded.
4. The UI keeps the platform's vendor-neutral wording ("Decision model"); Jev is whatever `DECISION_MODEL_*` points at.

# Affected specs

* [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md) - per-conversation override, RTE-22.
* [/api/rest-api.md](/api/rest-api.md) - `routing_mode` on `POST /api/conversations`.
* [/data/data-model.md](/data/data-model.md) - nullable `conversations.routing_mode` (added to an existing database with its default).
* [/ui/test-call.md](/ui/test-call.md) - Routing switch, UI-76; [/ui/settings.md](/ui/settings.md) - help text.

# Acceptance criteria

* **RTE-22** (override semantics, validation, public API ignores it) and **UI-76** (the switch), both defined in the specs above.

# Tasks

1. Spec edits and this proposal (done in this CP).
2. Backend: `conversations.routing_mode` column and migration, accept and validate it in `POST /api/conversations`, pass it to `supervisor.route` as the mode in force — covers RTE-22.
3. Web: Routing switch in the Test call Full flow, disabled states from `/healthz`, lock while active — covers UI-76.
4. Tests on the fake LLM and a fake decision-model server; update the data-model migration test.
5. `python scripts/spec_check.py`, backend tests, web build.

# Risks and rollout

* Small: a nullable column and one parameter. Existing conversations have `null` and keep using the front desk's setting.
* Comparing modes needs a configured decision model; a live Jev comparison is a paid call and needs the owner's go-ahead.

# Out of scope

* A per-agent routing mode (routing is the front desk's job, not an agent's).
* Renaming the option to a vendor name, or running both modes on one phrase side by side (the routing suite's *Compare modes* already does that on a suite).
