---
type: Component Spec
title: Tools and skills
description: HTTP tool definitions and execution (in-process for relative URLs), the identity verification gate, result shaping, and the skill format rendered into the system prompt.
status: stable
tags: [architecture, tools, skills]
generated: { by: "claude-code/claude-opus-5-5", at: "2026-10-06T00:00:00Z" }
---

# Tool definition

Schema in [/data/agent-config.md](/data/agent-config.md). Key fields: `name` (snake_case, unique per tenant, not a built-in name), `description`, `method` (`GET`/`POST`), `url` (template), `parameters` (JSON Schema object), `requires_verification`, `is_verification`, `timeout_s` (default 8).

# Execution

1. Parse arguments (JSON). Invalid → `{"error":"invalid_arguments"}`.
2. **Verification gate** — if `requires_verification` and the call is not verified → return `{"error":"identity_not_verified","say":"I need to verify your identity first. Can I have your member ID and date of birth?"}` without calling the API. Counts as a tool error? **No** — the gate does not increment `tool_error_streak`.
3. Render the URL: `{param}` placeholders are replaced with URL-encoded argument values and removed from the remaining args. `GET`: remaining args become query parameters. `POST`: remaining args become the JSON body.
4. Headers: `X-Tenant-Id` and `X-Call-Id` are always sent. Once the call is verified, `X-Member-Ref` carries the verified member reference, so member-specific APIs never trust a member ID chosen by the model (minimum-necessary access; see [/product/healthcare-compliance.md](/product/healthcare-compliance.md)).
5. Execution goes through the `ToolCaller` port, so the runtime never holds the application object or chooses a transport ([/architecture/modular-structure.md](/architecture/modular-structure.md)). Its routing adapter sends relative URLs (starting `/`) **in-process** against the platform's own ASGI app (no network hop) and absolute URLs over HTTP. Pointing a relative prefix at another service later is an adapter configuration change, not a runtime change; a future MCP transport is another adapter behind the same port.
6. Response: JSON body (or `{"text": <body>}` for non-JSON), serialized and truncated to 2,000 characters. HTTP ≥ 400 → `{"error": "http_<code>", "detail": <body excerpt>}`. Timeout → `{"error":"timeout"}`.
7. **Verification tools** (`is_verification: true`): if the JSON response has `verified: true`, the call state becomes verified and `member_ref` (if present) is stored on the call.
8. Every execution appends `{name, ok, summary}` to `state.tools_used`, where `summary` is a ≤ 160-char human-readable digest (status code + key fields).

# Skill format

| Field | Meaning |
|---|---|
| `name` | Short label, e.g. "Claim status" |
| `description` | When this skill applies (one sentence) |
| `instructions` | Markdown steps the agent follows |
| `required_tools` | Tool names the skill uses (must exist in the agent's tool list to publish) |
| `escalate_when` | Conditions under which this skill must escalate |

Skills are rendered into the system prompt as:

```
## Skill: {name}
Use when: {description}
Tools: {required_tools joined}
Steps:
{instructions}
Escalate when: {escalate_when}
```

v1 includes all of an agent's skills in every prompt (no on-demand loading).

# Acceptance

- **TS-01** — Given a tool with `requires_verification` and an unverified call, when the model calls it, then no HTTP request is made and the result is `identity_not_verified`.
- **TS-02** — Given a verification tool returning `{"verified": true, "member_ref": "EVG-482913"}`, when executed, then the call is verified and `calls.caller_ref` is `EVG-482913`.
- **TS-03** — Given url `/mock/healthcare/claims/{claim_id}` and args `{claim_id: "C-20931", include: "lines"}` with `GET`, when executed, then the request path is `/mock/healthcare/claims/C-20931?include=lines`.
- **TS-04** — Given an API returning HTTP 404, when executed, then the result is `{"error":"http_404",...}` and the tool-error streak increments.
- **TS-05** — Given a response body over 2,000 characters, when returned to the model, then it is truncated to 2,000 characters.
- **TS-06** — Given a tool named `search_knowledge`, when created, then the API rejects it with 422.
- **TS-07** — Given a skill whose `required_tools` includes a tool not on the agent, when publishing, then publish fails with a message naming the missing tool.
- **TS-08** — Given a verified call, when any agent tool executes, then the request carries `X-Member-Ref` with the verified member reference; given an unverified call, the header is absent.
