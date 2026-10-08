---
type: Component Spec
title: LLM gateway
description: "Maps LLM roles to provider models over a pluggable wire adapter, with streaming, tool calls, JSON outputs, fallback and cost accounting."
status: stable
tags: [architecture, llm, groq, openrouter, openai]
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
| `turn` | Semantic turn detection (LLM evaluator) | tiny JSON verdict in under a second | `groq:openai/gpt-oss-20b` |

# Configuration — `apps/api/config/models.yaml`

```yaml
providers:
  groq:       { wire: openai, base_url: "https://api.groq.com/openai/v1", api_key_env: GROQ_API_KEY,
                options: { stream_usage: false, usage_extra_key: x_groq } }
  openrouter: { wire: openai, base_url: "https://openrouter.ai/api/v1",   api_key_env: OPENROUTER_API_KEY,
                options: { stream_usage: true } }
  openai:     { wire: openai, base_url: "https://api.openai.com/v1",      api_key_env: OPENAI_API_KEY,
                options: { stream_usage: true } }
models:            # price per 1M tokens (USD) for cost accounting
  "groq:openai/gpt-oss-120b":       { input: 0.15, output: 0.60, json_schema: true, reasoning_effort: true }
  "groq:openai/gpt-oss-20b":        { input: 0.10, output: 0.50, json_schema: true, reasoning_effort: true }
  "openrouter:openai/gpt-oss-120b": { input: 0.15, output: 0.60, json_schema: false }
  "openai:gpt-4.1-mini":            { input: 0.40, output: 1.60, json_schema: true }   # confirm IDs and prices in the OpenAI console
  "openai:gpt-4.1-nano":            { input: 0.10, output: 0.40, json_schema: true }
roles:
  realtime:  { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: low, temperature: 0.3, max_tokens: 800 },
               fallback: ["openrouter:openai/gpt-oss-120b", "openai:gpt-4.1-mini"] }
  analysis:  { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: low, temperature: 0 }, fallback: ["openrouter:openai/gpt-oss-120b", "openai:gpt-4.1-mini"] }
  drafting:  { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: medium, temperature: 0.4 }, fallback: ["openrouter:openai/gpt-oss-120b", "openai:gpt-4.1-mini"] }
  simulator: { model: "groq:openai/gpt-oss-20b",  params: { reasoning_effort: low, temperature: 0.7 }, fallback: ["groq:openai/gpt-oss-120b", "openai:gpt-4.1-nano"] }
  judge:     { model: "groq:openai/gpt-oss-120b", params: { reasoning_effort: low, temperature: 0 }, fallback: ["openrouter:openai/gpt-oss-120b", "openai:gpt-4.1-mini"] }
  turn:      { model: "groq:openai/gpt-oss-20b", params: { reasoning_effort: low, temperature: 0, max_tokens: 200 }, fallback: ["openrouter:openai/gpt-oss-20b", "openai:gpt-4.1-nano"] }
```

* A **model ref** is `<provider>:<model id>`. Any OpenRouter model may be used by adding it under `models`, and any non-reasoning OpenAI chat model likewise.
* `wire` names the HTTP protocol the provider speaks and selects the adapter that speaks it. It defaults to `openai`, so an entry that omits it keeps working. `options` is passed to that adapter untouched and is where per-provider quirks are declared instead of being coded; the gateway never reads it. For the `openai` wire: `stream_usage` asks for usage on the final stream chunk, and `usage_extra_key` names a vendor extension carrying usage when the standard field is absent.
* Every role's fallback chain **ends with an `openai:` model**, so a deployment that has only `OPENAI_API_KEY` works with no `LLM_ROLE_*` line: providers without a key are skipped, Groq and OpenRouter first, and OpenAI answers. Each provider's key is read from the variable its own `api_key_env` names — from the process environment or, failing that, from a line in `apps/api/.env`. No provider or key name appears in Python.
* Agents may override `realtime` via `config.models.realtime` ([/data/agent-config.md](/data/agent-config.md)). `GET /api/models` lists selectable refs.
* Env `LLM_ROLE_<ROLE>` (e.g. `LLM_ROLE_REALTIME=openrouter:openai/gpt-oss-120b` or `LLM_ROLE_REALTIME=openai:gpt-4.1-mini`) overrides a role's primary model at deploy time. It is read from a real environment variable or, failing that, from a line in `apps/api/.env`. The role's fallbacks stay as configured; a provider with no API key is skipped.

# Adding a provider

* **A provider that speaks a wire we already have:** add a `providers:` entry naming that `wire`, add its models with prices under `models:`, and set the API key variable the entry names. Reference it from a role or a fallback chain. **No Python file changes** — not the gateway, not the settings, not the routes. `GET /healthz` picks the provider up by itself.
* **A provider with its own protocol:** add one module at `voiceai/adapters/llm/<wire>.py` exposing `build(cfg) -> ChatClient`, then configure the provider with `wire: <wire>`. The adapter owns client construction, request shaping and the mapping from its errors onto the port's `Retryable` (try the next ref) and `BadRequest` (do not). It owns nothing about roles, fallback order or prices.
* A `wire` with no adapter module, or one whose SDK is not installed, is skipped exactly like a provider with no API key: the next ref answers and start-up is unaffected. Adapter modules are imported lazily, so an unused provider's SDK is never loaded.

Model IDs still live only in `apps/api/config/models.yaml`, never in code ([/architecture/tech-stack.md](/architecture/tech-stack.md)).

# Interface (`voiceai.llm.gateway`)

| Function | Behavior |
|---|---|
| `stream_chat(role, messages, tools, override=None)` | Async iterator of events: `text` deltas, then a final `done` event carrying the assembled tool calls (id, name, JSON args), finish reason and usage. |
| `complete_json(role, messages, schema: type[BaseModel])` | Returns a validated Pydantic object. Uses `response_format={"type":"json_schema",...}` when the model supports it, else `json_object` plus the schema in the prompt. On validation failure retries once with the error appended. |
| `usage_cost(model_ref, usage)` | USD from the price table; unknown models cost 0 and log a warning. |

The `turn` role is optional in practice: if it fails or times out, semantic turn detection uses its local heuristic ([/architecture/turn-detection.md](/architecture/turn-detection.md)).

# Fallback and timeouts

* Order: role model, then each `fallback` ref. Fallback triggers on connection errors, timeouts, HTTP 429 and 5xx — never on 400-class validation errors.
* For streams, fallback is only attempted before the first token is yielded.
* Timeouts: `realtime` first-token 8 s; JSON roles 60 s total.
* Missing API key for a provider: that provider is skipped as if it failed.

# Provider quirks

* Groq gpt-oss models accept `reasoning_effort`; it is sent only when the model entry says `reasoning_effort: true`. Reasoning tokens count toward `max_tokens`, so the realtime cap is 800 even though spoken replies are short.
* Groq reports streaming usage in `x_groq.usage` on the last chunk, declared as `options.usage_extra_key: x_groq`; OpenRouter and OpenAI need `stream_options.include_usage`, declared as `options.stream_usage: true`. Both are configuration read by the wire adapter, not branches on a provider name. Missing usage is estimated by the gateway as characters ÷ 4.
* `json_schema` response format is tried first when the model entry allows it; a 400 from the provider falls back to `json_object` on the same model.
* Tool call arguments are parsed with `json.loads`; malformed JSON is returned to the model as a tool error (`{"error":"invalid_arguments"}`), never raised.
* OpenRouter requests include `HTTP-Referer` and `X-Title: Voice AI Platform` headers.
* OpenAI chat models of the gpt-4.1 family accept `max_tokens`, `temperature`, tools and `stream_options.include_usage` (`stream_usage: true`) like the other providers; they have no `reasoning_effort`, so their entries omit the flag and the gateway drops the parameter. `json_schema` response format is supported.
* **Not supported:** OpenAI reasoning-family models (o-series, gpt-5 family) reject `max_tokens` and non-default `temperature`; they must not be added to `models` until a per-model parameter mapping is specified.
* A 404 (unknown model) or 401 (bad key) is a 400-class error and does not fall back; a 429, including `insufficient_quota`, does.

# Testing

A scripted in-memory responder is selected with `LLM_FAKE=1` or installed by a test. It short-circuits at the **role** level, before any wire is chosen, so it exercises no adapter and needs no provider configuration; unit tests never hit the network.

# Acceptance

- **LG-01** — Given role `realtime` whose primary provider returns HTTP 503, when a stream starts, then the request is retried on the first fallback ref and the turn succeeds.
- **LG-02** — Given a 400 validation error from the primary, when called, then no fallback is attempted and the error propagates.
- **LG-03** — Given an agent override `openrouter:openai/gpt-oss-120b`, when the runtime calls `realtime`, then that model ref is used.
- **LG-04** — Given `complete_json` with a schema and a first response that fails validation, then exactly one retry is made and a valid object is returned or a `LLMJsonError` raised.
- **LG-05** — Given usage of 1,000,000 input and 1,000,000 output tokens on `groq:openai/gpt-oss-120b`, then `usage_cost` returns 0.75.
- **LG-06** — Given `LLM_ROLE_JUDGE=groq:openai/gpt-oss-20b` as an environment variable, when the gateway loads, then the judge role uses that model.
- **LG-07** — Given the same setting only as a line in `apps/api/.env` (not in the process environment), then the judge role uses that model; given both with different values, the environment variable wins.
- **LG-08** — Given `OPENAI_API_KEY` only as a line in `apps/api/.env` (not in the process environment), when `/healthz` is requested, then `providers.openai` is `true` and the gateway builds its `openai` client with that key and base URL `https://api.openai.com/v1`; given the variable in both places with different values, the environment variable wins; given neither, `providers.openai` is `false` and the provider is skipped.
- **LG-09** — Given `LLM_ROLE_REALTIME=openai:gpt-4.1-mini`, when a stream starts, then the request goes to model `gpt-4.1-mini` through the `openai` provider with `stream_options.include_usage` set and without `reasoning_effort`, and `usage_cost("openai:gpt-4.1-mini", 1,000,000 input and 1,000,000 output tokens)` returns 2.00.
- **LG-10** — Given the default configuration, when each role's reference list is built, then it ends with an `openai:` model; given a key for OpenAI only (Groq and OpenRouter skipped for lack of a key) every role (`realtime`, `analysis`, `drafting`, `simulator`, `judge`, `turn`) is served by OpenAI with no `LLM_ROLE_*` line; and given Groq answering 429 and no OpenRouter key, a `realtime` stream is served by `openai:gpt-4.1-mini`.
- **LG-11** — Given the default configuration, then every `openai:` ref used by a role or fallback has a price entry, and `GET /api/models` lists the OpenAI refs in `selectable`.
- **LG-12** — Given a `providers:` entry naming a `wire` that has an adapter, a `base_url`, an `api_key_env` whose variable is set, and a priced ref under `models:`, when a role names that ref, then the request reaches that adapter with that base URL, that key, the role's params and the entry's `options`, the result is priced from the table, and no Python file outside `apps/api/config/models.yaml` mentions the provider.
- **LG-13** — Given `models.yaml` declaring N providers, when `/healthz` is requested, then `providers` has exactly those N names plus `deepgram`, each `true` only when its key resolves.
- **LG-14** — Given a role whose primary ref names a `wire` with no adapter module, when a stream starts, then that ref is skipped like a missing key and the next ref answers; and a `wire` value that is not a plain lowercase identifier is rejected rather than imported.
- **LG-15** — Given a provider entry declaring `options.usage_extra_key`, when a stream's chunk carries usage only under that key, then the usage is read from it; given no such declaration the key is ignored, the standard usage field always wins, and usage the provider never reports is estimated as characters ÷ 4.
