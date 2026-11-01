---
type: Change Proposal
title: CP-0029 Configurable decision-model time budgets so voice can use the decision model
description: The decision model's time budget per channel (fixed at 350 ms in voice and 1.5 s in text) becomes two environment settings, so a hosted decision model measured at about 550 ms can decide voice conversations while the caller hears the connecting message; the embedding stays the fallback.
status: draft
cp_state: implemented
tags: [routing, voice, configuration]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-11-01T00:00:00Z" }
---

# Why

Hosted Jev was measured against the embedding on 2026-11-01 ([spikes](/verification/spikes.md) S5): it decided 37 of 38 answerable routing cases (34 right) where the embedding decided 14 (all right), at p50 551 ms and p95 671 ms. The voice budget is fixed at 350 ms, so in voice every request times out and the embedding decides (checked the same day: `fallbacks: timeout` on every voice decision). The product owner decided: "for voice also use Jev".

The caller already hears the `connecting_message` ("One moment while I connect you.", about 1.5 s of speech) while the decision model runs, so a budget of about one second adds no silence.

# What changes

* Two new environment settings next to the other `DECISION_MODEL_*` settings ([/architecture/supervisor-routing.md](/architecture/supervisor-routing.md), Decision model):

  | Variable | Meaning | Default |
  |---|---|---|
  | `DECISION_MODEL_TIMEOUT_VOICE_MS` | time budget for one decision-model request in voice (start, clarified and transfer decisions) | 350 |
  | `DECISION_MODEL_TIMEOUT_TEXT_MS` | the same in text, API, playground text and the routing suite | 1500 |

  Values are whole milliseconds from 100 to 5000; a value outside that range, or not a number, is replaced by the nearest bound or the default and logged once at startup.
* Defaults are today's values, so nothing changes until a deployment sets them. `.env.example` recommends `DECISION_MODEL_TIMEOUT_VOICE_MS=1000` for a hosted model.
* When the budget runs out the request is abandoned and the embedding decides, as today (`fallbacks: timeout`). An unreachable model (connection error) fails at once and does not wait for the budget.
* `GET /healthz` adds `timeouts_ms: {voice, text}` to `router.decision_model`, the budgets in force.

# Affected specs

* [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md) - Decision model table gains the two settings; the fixed timeouts line now names them; RTE-16, RTE-17 added.
* [/architecture/deployment.md](/architecture/deployment.md) - the Public API and routing row lists the two settings.

# Acceptance criteria

New: RTE-16 (voice and text budgets in force, embedding fallback on timeout), RTE-17 (bounds, defaults and `/healthz`). Each is written in [/architecture/supervisor-routing.md](/architecture/supervisor-routing.md).

# Tasks

1. Spec edits (this CP): supervisor routing (settings, RTE-16, RTE-17), deployment.
2. Backend: settings `decision_model_timeout_voice_ms` and `decision_model_timeout_text_ms` with clamping in `voiceai/config.py`; `voiceai/routing/decision.py` reads them instead of `TIMEOUT_S`; `/healthz` reports them — covers RTE-16, RTE-17.
3. Tests in `tests/test_supervisor_routing.py` citing RTE-16 and RTE-17 (fake decision server with a delay; no network).
4. `.env.example` and `infra/deploy-cloudrun.sh` carry the two variables; the local `.env` sets the voice budget to 1000.

# Risks and rollout

* A long budget delays the agent's first line when the model is slow: at most the budget, while the connecting message plays. A budget above about 1.5 s can leave silence after the message; the recommended value is 1000.
* On Cloud Run `PHI_MODE` still blocks a hosted model, so the setting has no effect there until a BAA exists.
* The budget is per request; a transfer decision in voice uses the same budget.

# Out of scope

* Making `decision_model` the default routing mode.
* What the decision model sees (the profile summary, its 600-char limit, knowledge titles).
* Per-tenant budgets (the budget depends on the model and the deployment, not the tenant).
