---
type: Decision Record
title: ADR-0003 LLM gateway
description: A thin gateway over the OpenAI-compatible APIs of Groq and OpenRouter, with roles, fallbacks and prices in YAML - no LiteLLM, no provider SDKs.
status: stable
tags: [decision, llm]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Context

The LLM must be cheap and switchable. Groq gives very fast, low-cost inference of open-weight models (e.g. `openai/gpt-oss-120b` at about $0.15/$0.60 per million tokens); OpenRouter gives access to many models through one key. Both expose OpenAI-compatible chat completions with tool calling.

# Decision

* One `AsyncOpenAI` client per provider (different `base_url`/key), wrapped by `voiceai.llm.gateway` ([/architecture/llm-gateway.md](/architecture/llm-gateway.md)).
* Work is expressed as **roles**; each role maps to a model ref and fallbacks in `config/models.yaml`; agents may override the realtime model.
* The live-call path talks to Groq directly (no extra OpenRouter hop); OpenRouter is the fallback and the place to try other models.

# Consequences

* Switching models is a config change, visible in the builder.
* We own small amounts of glue (streaming tool-call assembly, JSON validation, fallback) instead of a heavy dependency.
* Provider-specific features (e.g. `reasoning_effort`) are gated per model entry.

Amended by [ADR-0007](adr-0007-openai-provider.md): OpenAI is a third provider, and the last fallback of every role.
