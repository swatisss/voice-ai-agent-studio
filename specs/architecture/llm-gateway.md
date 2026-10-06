---
type: Component Spec
title: LLM gateway
description: Maps LLM roles to Groq or OpenRouter models through one OpenAI-compatible client, with streaming, tool calls, JSON outputs, fallback and cost accounting.
status: stable
tags: [architecture, llm, groq, openrouter]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Roles

| Role | Used by | Needs | Default |
|---|---|---|---|
| `realtime` | Agent runtime (all channels) | low latency, streaming, tool calls | `groq:openai/gpt-oss-120b`, reasoning effort `low` |
| `analysis` | Packet + call analysis | JSON output | `groq:openai/gpt-oss-120b` |
| `drafting` | Cluster naming, fix drafting | JSON output, writing quality | `groq:openai/gpt-oss-120b` |
| `simulator` | Simulated callers | cheap, fast | `groq:openai/gpt-oss-20b` |
| `judge` | Eval grading | JSON output | `groq:openai/gpt-oss-120b` |

# Configuration — `apps/api/config/models.yaml`

```yaml
providers:
  groq:       { base_url: "https://api.groq.com/openai/v1", api_key_env: GROQ_API_KEY }
  openrouter: { base_url: "https://openrouter.ai/api/v1",   api_key_env: OPENROUTER_API_KEY }
models:            # price per 1M tokens (USD) for cost accounting
  "groq:openai/gpt-oss-120b":       { input: 0.15, output: 0.60, json_schema: true, reasoning_effort: true }
  "groq:openai/gpt-oss-20b":        { input: 0.10, output: 0.50, json_schema: true, reasoning_effort: true }
  "openrouter:openai/gpt-oss-120b": { input: 0.15, output: 0.60, json_schema: false }
roles:
  realtime:  { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: low, temperature: 0.3, max_tokens: 800 },
               fallback: ["openrouter:openai/gpt-oss-120b"] }
  analysis:  { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: low, temperature: 0 }, fallback: ["openrouter:openai/gpt-oss-120b"] }
  drafting:  { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: medium, temperature: 0.4 }, fallback: ["openrouter:openai/gpt-oss-120b"] }
  simulator: { model: "groq:openai/gpt-oss-20b",  params: { reasoning_effort: low, temperature: 0.7 }, fallback: ["groq:openai/gpt-oss-120b"] }
  judge:     { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: low, temperature: 0 }, fallback: ["openrouter:openai/gpt-oss-120b"] }
```

* A **model ref** is `<provider>:<model id>`. Any OpenRouter model may be used by adding it under `models`.
* Agents may override `realtime` via `config.models.realtime` ([/data/agent-config.md](/data/agent-config.md)). `GET /api/models` lists selectable refs.
* Env `LLM_ROLE_<ROLE>` (e.g. `LLM_ROLE_REALTIME=openrouter:openai/gpt-oss-120b`) overrides a role at deploy time.

# Interface (`voiceai.llm.gateway`)

| Function | Behavior |
|---|---|
| `stream_chat(role, messages, tools, override=None)` | Async iterator of events: `text` deltas, then a final `done` event carrying the assembled tool calls (id, name, JSON args), finish reason and usage. |
| `complete_json(role, messages, schema: type[BaseModel])` | Returns a validated Pydantic object. Uses `response_format={"type":"json_schema",...}` when the model supports it, else `json_object` plus the schema in the prompt. On validation failure retries once with the error appended. |
| `usage_cost(model_ref, usage)` | USD from the price table; unknown models cost 0 and log a warning. |

# Fallback and timeouts

* Order: role model, then each `fallback` ref. Fallback triggers on connection errors, timeouts, HTTP 429 and 5xx — never on 400-class validation errors.
* For streams, fallback is only attempted before the first token is yielded.
* Timeouts: `realtime` first-token 8 s; JSON roles 60 s total.
* Missing API key for a provider: that provider is skipped as if it failed.

# Provider quirks

* Groq gpt-oss models accept `reasoning_effort`; it is sent only when the model entry says `reasoning_effort: true`. Reasoning tokens count toward `max_tokens`, so the realtime cap is 800 even though spoken replies are short.
* Groq reports streaming usage in `x_groq.usage` on the last chunk; OpenRouter needs `stream_options.include_usage` (`stream_usage: true` in the provider entry). Missing usage is estimated as characters ÷ 4.
* `json_schema` response format is tried first when the model entry allows it; a 400 from the provider falls back to `json_object` on the same model.
* Tool call arguments are parsed with `json.loads`; malformed JSON is returned to the model as a tool error (`{"error":"invalid_arguments"}`), never raised.
* OpenRouter requests include `HTTP-Referer` and `X-Title: Voice AI Platform` headers.

# Testing

A `fake` provider (in-memory, scripted responses) implements the same interface and is selected with `LLM_FAKE=1`; unit tests never hit the network.

# Acceptance

- **LG-01** — Given role `realtime` whose primary provider returns HTTP 503, when a stream starts, then the request is retried on the first fallback ref and the turn succeeds.
- **LG-02** — Given a 400 validation error from the primary, when called, then no fallback is attempted and the error propagates.
- **LG-03** — Given an agent override `openrouter:openai/gpt-oss-120b`, when the runtime calls `realtime`, then that model ref is used.
- **LG-04** — Given `complete_json` with a schema and a first response that fails validation, then exactly one retry is made and a valid object is returned or a `LLMJsonError` raised.
- **LG-05** — Given usage of 1,000,000 input and 1,000,000 output tokens on `groq:openai/gpt-oss-120b`, then `usage_cost` returns 0.75.
- **LG-06** — Given `LLM_ROLE_JUDGE=groq:openai/gpt-oss-20b`, when the gateway loads, then the judge role uses that model.
