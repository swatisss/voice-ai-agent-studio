---
type: Decision Record
title: ADR-0007 OpenAI as a third LLM provider
description: Add OpenAI beside Groq and OpenRouter through the same OpenAI-compatible gateway; Groq stays the default primary, OpenAI is the last fallback of every role and a one-line switch.
status: stable
tags: [decision, llm]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-10-07T00:00:00Z" }
---

# Context

[ADR-0003](adr-0003-llm-gateway.md) chose Groq (cheap, fast, open-weight models) with OpenRouter as the fallback. In the first live test the Groq `on_demand` tier limit of 8,000 tokens per minute per model made tool-calling turns fail: one turn sends two to four requests of about 2.9K tokens each. OpenRouter needs a separate key and account. The team already has an OpenAI API key.

# Decision

* Add `openai` as a provider in `config/models.yaml` (base URL `https://api.openai.com/v1`, key `OPENAI_API_KEY`, streaming usage enabled). No new client: it is the same `AsyncOpenAI` wrapper.
* Register two non-reasoning chat models, `gpt-4.1-mini` and `gpt-4.1-nano`, and end every role's fallback chain with one of them.
* Keep Groq as the default primary: it is the cheapest and fastest option and works well on a paid tier. Teams on the free tier switch roles to OpenAI with `LLM_ROLE_<ROLE>` lines.
* Support only models that accept `max_tokens` and `temperature`; reasoning-family models need a per-model parameter mapping and are a later change.

# Consequences

* A deployment with only an OpenAI key works out of the box: Groq and OpenRouter are skipped for lack of a key and the OpenAI fallback answers.
* Cost per token is higher than `gpt-oss-120b`; prices come from the price table and must be kept current.
* Prompts leave for one more third party; the synthetic-data rule applies to every provider ([/product/healthcare-compliance.md](/product/healthcare-compliance.md)).
* A wrong or unavailable OpenAI model ID fails with a 404, which is deliberately not a fallback trigger.
