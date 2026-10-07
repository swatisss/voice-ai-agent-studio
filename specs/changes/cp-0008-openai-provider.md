---
type: Change Proposal
title: CP-0008 OpenAI as a third LLM provider
description: Add OpenAI (key from apps/api/.env) next to Groq and OpenRouter so any role can run on an OpenAI model and every role can fall back to one, removing the Groq free-tier 8,000 tokens-per-minute wall.
status: stable
cp_state: implemented
tags: [llm, gateway, providers]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-07T00:00:00Z" }
---

# Why

A live test of the Customer Care Agent with a valid Groq key failed on tool-calling turns. The Groq `on_demand` tier caps `openai/gpt-oss-120b` (and `-20b`) at **8,000 tokens per minute**. Each realtime request is about 2.9K tokens (the system prompt carries the agent's skills) and one turn that calls tools makes two to four requests, so a single turn can exceed the cap; the agent then says "I'm having trouble right now" and escalates, and the packet and analysis calls, which share the same model quota, fail as well. The only fallback today is OpenRouter, which needs a second key.

The team already holds an OpenAI API key. OpenAI exposes the same OpenAI-compatible chat API the gateway already speaks, so adding it is configuration plus a small amount of key handling, not a new client.

# What changes

1. **A third provider, `openai`**, with base URL `https://api.openai.com/v1` and the key `OPENAI_API_KEY`, read from the process environment or from `apps/api/.env` exactly like the Groq and OpenRouter keys.
2. **Two OpenAI models** in the price table: `openai:gpt-4.1-mini` (agent, analysis, drafting, judge) and `openai:gpt-4.1-nano` (simulator, turn detection). Both are ordinary chat models: streaming, tool calls and JSON output work as for the other providers. They appear in the agent builder's model list and in `GET /api/models`.
3. **Every role's fallback chain ends with an OpenAI model.** Groq stays the default primary (cheapest, fastest). When Groq answers 429 or 5xx and OpenRouter has no key (skipped), the request is served by OpenAI. A deployment with *only* an OpenAI key therefore works with no `LLM_ROLE_*` lines at all.
4. **Switching roles** to OpenAI is one setting per role (`LLM_ROLE_REALTIME=openai:gpt-4.1-mini`, and so on); the runbook gives the six lines. This skips the failed Groq attempt on every turn when Groq is known to be limited.
5. **Visibility**: `/healthz` reports `providers.openai` (key configured) and the header shows its health dot; the dev launcher counts an OpenAI key as an LLM key (no "agent replies will fail" warning, no `LLM_ROLE_*` advice when an OpenAI key is present).
6. **Deployment**: `OPENAI_API_KEY` becomes an optional Secret Manager secret; the deploy script attaches optional secrets (`OPENROUTER_API_KEY`, `OPENAI_API_KEY`) only when they exist, so a missing optional key no longer fails the deploy.

# Affected specs

* [/architecture/llm-gateway.md](/architecture/llm-gateway.md) - provider, models, fallback chains, quirks, LG-08…LG-11.
* [/decisions/adr-0007-openai-provider.md](/decisions/adr-0007-openai-provider.md) - new: why OpenAI, why Groq stays primary; [/decisions/adr-0003-llm-gateway.md](/decisions/adr-0003-llm-gateway.md) - amended pointer.
* [/build/dev-launcher.md](/build/dev-launcher.md) - OpenAI counts as an LLM key; DEV-06 extended.
* [/architecture/deployment.md](/architecture/deployment.md) - secret and `/healthz` shape; [/build/runbook-gcp.md](/build/runbook-gcp.md) - optional secrets.
* [/build/runbook-local.md](/build/runbook-local.md) - OpenAI-only setup, switching roles, Groq 429 advice.
* [/ui/app-shell.md](/ui/app-shell.md) - provider dots include OpenAI.
* [/architecture/tech-stack.md](/architecture/tech-stack.md), [/architecture/system-overview.md](/architecture/system-overview.md), [/architecture/index.md](/architecture/index.md), [/product/demo-script.md](/product/demo-script.md) - wording.

# Acceptance criteria

New, defined in [/architecture/llm-gateway.md](/architecture/llm-gateway.md): LG-08 (key from `.env`, `/healthz`, precedence), LG-09 (request shape and cost of an `openai:` role), LG-10 (OpenAI-only setup and the Groq-429 fallback), LG-11 (price entries and `GET /api/models`).
Widened, defined in [/build/dev-launcher.md](/build/dev-launcher.md): DEV-06 (the OpenAI key counts as an LLM key).

# Tasks

1. Spec edits (done in this CP).
2. Backend: `openai_api_key` setting, provider key lookup, `openai` provider and two models in `config/models.yaml`, fallback chains, `/healthz` — covers LG-08…LG-11.
3. Dev launcher: `OPENAI_API_KEY` in the key list and warning rules — covers DEV-06.
4. Web: nothing to build (the header renders whatever `/healthz` returns); verify the dot in the browser.
5. Docs and tooling: `apps/api/.env.example`, README key list and troubleshooting, `infra/deploy-cloudrun.sh`, runbooks.
6. Tests: new tests for LG-08…LG-11 with stubbed clients (no network); update the DEV-06 test; one manual live check with a real key (a text call of each of the four agents).

# Risks and rollout

* **Models and prices must be confirmed** against the OpenAI console and price list before the demo ([/architecture/tech-stack.md](/architecture/tech-stack.md) already requires this for every model ID). A wrong ID returns 404 from OpenAI, which is *not* a fallback trigger and would fail the call, so an agent override or role line pointing at an unavailable model fails loudly.
* **Reasoning-family models** (the o-series and gpt-5 family) reject `max_tokens` and non-default `temperature`, which the gateway sends. They are not supported by this change; only non-reasoning chat models may be added to `models.yaml` until a per-model parameter mapping is specified.
* **Cost**: `gpt-4.1-mini` costs roughly three times `gpt-oss-120b` per token. At demo volumes this is cents; the dashboard cost figures use the price table, so wrong prices show wrong costs.
* **Rate limits** on OpenAI depend on the account's usage tier; a brand-new key can have a low tier. A 429 (including `insufficient_quota`) falls through to the next ref like any other.
* **Latency**: with Groq primary and Groq limited, each turn pays one failed Groq attempt before OpenAI answers; switching roles to OpenAI avoids it.
* **Data handling**: prompts contain only synthetic data; no PHI may be sent to any provider ([/product/healthcare-compliance.md](/product/healthcare-compliance.md)).

# Out of scope

* Changing the default primary provider away from Groq.
* Reasoning-family OpenAI models and per-model parameter mappings.
* Azure OpenAI or any provider that is not OpenAI-compatible.
* Marking models whose provider has no key in the builder's model list.
