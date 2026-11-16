---
type: Change Proposal
title: CP-0043 Remove Groq as an LLM provider
description: The product no longer uses Groq; OpenAI becomes the primary provider of every chat role, OpenRouter stays an optional fallback, and every Groq key, model, health dot and runbook line goes.
status: stable
cp_state: implemented
tags: [llm, gateway, providers]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The owner has decided the product will not use Groq. Today Groq is the default primary of every chat role ([ADR-0003](/decisions/adr-0003-llm-gateway.md), kept primary by [ADR-0007](/decisions/adr-0007-openai-provider.md)), a required key in setup, the launcher, the phone demo and the Cloud Run deploy, and a health dot in the UI. Leaving it in means a new machine is told to get a Groq key that nothing should use, and every turn on an OpenAI-only setup pays a skipped-provider hop for nothing.

# What changes

1. **No `groq` provider.** `config/models.yaml` loses the provider and both `groq:` models; `GROQ_API_KEY`, `Settings.groq_api_key`, the `x_groq` usage reading and the `groq` entry of `/healthz` `providers` are removed. A `groq:` ref in an agent override or `LLM_ROLE_*` line is no longer a known provider and is rejected like any unknown provider.
2. **OpenAI is the primary of every chat role.** All of `realtime`, `analysis`, `drafting`, `simulator`, `judge`, `turn` and `router` default to `openai:gpt-4.1-mini` (the one chat model already priced). Each role keeps one optional fallback on OpenRouter (`openai/gpt-oss-120b`; `-20b` for `turn`), used on a connection error, timeout, 429 or 5xx, and skipped when there is no `OPENROUTER_API_KEY`. The `speech` role is unchanged.
3. **Keys.** `OPENAI_API_KEY` is the one required LLM key (plus `DEEPGRAM_API_KEY` for cascade voice); `OPENROUTER_API_KEY` is optional. Setup, the dev launcher pre-flight, the phone demo pre-flight, the Cloud Run deploy script and `.env.example` ask for these and no longer mention Groq. The dev launcher's "no LLM key" warning is raised when neither `OPENAI_API_KEY` nor `OPENROUTER_API_KEY` is set; the OpenRouter-only `LLM_ROLE_*` advice goes, because with no OpenAI key the OpenRouter fallback answers by itself.
4. **UI.** The app shell's provider health dots show OpenRouter, OpenAI and Deepgram (they are read from `/healthz`; no Groq dot).
5. **Docs.** README, demo guide, runbooks (local, phone, GCP), deployment, tech stack, system overview, voice pipeline, demo script and the dev-launcher and phone-demo specs drop Groq. The local runbook's "Groq 429" troubleshooting row and the "OpenAI role lines to dodge Groq" block are removed (OpenAI is now the default, so no role lines are needed). Historical records (ADR-0003, ADR-0007, CP-0001..CP-0014, spikes, old log entries) are **not** rewritten; ADR-0003 and ADR-0007 gain a one-line "superseded in part by CP-0043" note.

Behavior seen by a user: on a machine with only `OPENAI_API_KEY`, nothing changes except one fewer skipped hop; a machine that had only `GROQ_API_KEY` stops working until it adds an OpenAI (or OpenRouter) key.

# Affected specs

* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - providers, role defaults, config sample, quirks, LG-05, LG-06, LG-10 reworded; LG-15 new.
* [/architecture/deployment.md](/architecture/deployment.md) - secrets, `/healthz` shape, DEP-01 reworded.
* [/architecture/tech-stack.md](/architecture/tech-stack.md), [/architecture/system-overview.md](/architecture/system-overview.md), [/architecture/voice-pipeline.md](/architecture/voice-pipeline.md), [/architecture/index.md](/architecture/index.md) - provider lists and latency target.
* [/build/dev-launcher.md](/build/dev-launcher.md) (DEV-06), [/build/phone-demo.md](/build/phone-demo.md) (DEV-07), [/build/runbook-local.md](/build/runbook-local.md), [/build/runbook-phone.md](/build/runbook-phone.md), [/build/runbook-gcp.md](/build/runbook-gcp.md) - key lists and troubleshooting.
* [/ui/app-shell.md](/ui/app-shell.md) - provider dots.
* [/product/demo-script.md](/product/demo-script.md) - fallback line.
* [/decisions/adr-0003-llm-gateway.md](/decisions/adr-0003-llm-gateway.md), [/decisions/adr-0007-openai-provider.md](/decisions/adr-0007-openai-provider.md), [/decisions/index.md](/decisions/index.md) - superseded-in-part notes.

# Acceptance criteria

* **LG-05, LG-06, LG-10** (existing IDs, reworded in place, no new meaning needed): cost check and the role-override example move to `openai:gpt-4.1-mini`; LG-10 becomes "primary is OpenAI, the OpenRouter fallback is skipped without a key, an OpenAI 429 with an OpenRouter key is served by OpenRouter".
* **DEP-01, DEV-06, DEV-07** reworded: the key lists have no Groq.
* **LG-15** (new, defined in [/architecture/llm-gateway.md](/architecture/llm-gateway.md)): no Groq provider, model or `/healthz` key anywhere; a `groq:` ref is rejected as an unknown provider; every chat role is OpenAI primary with one OpenRouter fallback.

# Tasks

1. Spec edits and this proposal (done in this CP).
2. Backend: remove the provider and models from `models.yaml`, re-point the seven role defaults, drop `groq_api_key`, the `x_groq` read and the `groq` provider key in `gateway.py`, `routes/meta.py` — covers LG-15, LG-10.
3. Scripts: `setup.py`, `dev.py`, `stack.py` example, `phone_demo.py`, `scripts/demo/fake_server.py`, `infra/deploy-cloudrun.sh` (required secrets become `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`), `.env.example` (and drop the OpenRouter-only advice in `dev.py`) — covers DEV-06, DEV-07, DEP-01.
4. Tests: move `test_llm_gateway.py` (fallback, cost, override, 429 tests), `test_dev_launcher.py`, `test_setup_script.py`, `test_phone_demo.py`, `test_realtime_config.py`, `conftest.py` off Groq; add LG-15.
5. Docs: README and `docs/demo-guide.md`.
6. Web: confirm the provider dots come from `/healthz` and show no Groq dot (no change expected) — covers the app-shell wording.
7. `python scripts/spec_check.py`, backend tests, web build.

# Risks and rollout

* **Latency and cost.** `gpt-4.1-mini` is priced at 0.40/1.60 per 1M tokens against Groq's 0.15/0.60, and the realtime target latency in the voice-pipeline spec was set on Groq. The target line is reworded to "on the primary model" and should be re-measured on the first live run (which needs the owner's approval).
* **Existing `.env` files** that set `GROQ_API_KEY` keep working syntactically (unknown variables are ignored) but supply no LLM. The launcher warning covers it.
* **Stored agent versions** that pin a `groq:` model in `config.models.realtime` would no longer resolve. The seed data pins none (checked); a local database that does needs the agent re-saved on a current model.
* The uncommitted CP-0042 work on this branch is unrelated; commit it separately.

# Out of scope

* Changing OpenRouter, the OpenAI realtime `speech` role, or adding other chat models (`gpt-4.1-nano`, reasoning-family models).
* Rewriting history in old CPs, ADRs, spikes and the log.
