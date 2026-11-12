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
2. **Verification gate** — if `requires_verification` and the call is not verified → return `{"error":"identity_not_verified","say":"I need to verify your identity first. Can I have your member ID and date of birth?"}` without calling the API. On an agent with no attached `is_verification` tool the call can never become verified, so the `say` is instead "I can't access account details on this line. I can connect you with a specialist who can." ([/architecture/caller-verification.md](/architecture/caller-verification.md), CP-0030). Counts as a tool error? **No** — the gate does not increment `tool_error_streak`.
3. Render the URL: `{param}` placeholders are replaced with URL-encoded argument values and removed from the remaining args. `GET`: remaining args become query parameters. `POST`: remaining args become the JSON body.
4. Headers: `X-Tenant-Id` and `X-Call-Id` are always sent. Once the call is verified, `X-Member-Ref` carries the verified member reference, so member-specific APIs never trust a member ID chosen by the model (minimum-necessary access; see [/product/healthcare-compliance.md](/product/healthcare-compliance.md)).
5. Relative URLs (starting `/`) execute **in-process** against the platform's own ASGI app (no network hop). Absolute URLs use a shared `httpx.AsyncClient`.
6. Response: JSON body (or `{"text": <body>}` for non-JSON), serialized and truncated to 2,000 characters. The limit is for HTTP tool responses: the built-in `search_knowledge` result reaches the model whole (at most four chunks of 900 characters, [/architecture/knowledge.md](/architecture/knowledge.md), KN-08). HTTP ≥ 400 → `{"error": "http_<code>", "detail": <body excerpt>}`. Timeout → `{"error":"timeout"}`.
7. **Verification tools** (`is_verification: true`): if the JSON response has `verified: true`, the call state becomes verified and `member_ref` (if present) is stored on the call. On an identified call the request also carries `X-Identified-Ref` with the identified member reference, so the business API can check a date of birth alone (flow A). A `verified: false` result counts a failed attempt and reaches the model as `{"verified": false, "say": "I'm sorry, I couldn't verify those details."}`, without the API's reason ([/architecture/caller-verification.md](/architecture/caller-verification.md)).
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
- **TS-02** — Given a verification tool returning `{"verified": true, "member_ref": "NGH-410237"}`, when executed, then the call is verified and `calls.caller_ref` is `NGH-410237`.
- **TS-03** — Given url `/mock/healthcare/claims/{claim_id}` and args `{claim_id: "CL-70231", include: "lines"}` with `GET`, when executed, then the request path is `/mock/healthcare/claims/CL-70231?include=lines`.
- **TS-04** — Given an API returning HTTP 404, when executed, then the result is `{"error":"http_404",...}` and the tool-error streak increments.
- **TS-05** — Given a response body over 2,000 characters, when returned to the model, then it is truncated to 2,000 characters.
- **TS-06** — Given a tool named `search_knowledge`, `send_email`, `send_sms` or `place_call`, when created, then the API rejects it with 422.
- **TS-07** — Given a skill whose `required_tools` includes a tool not on the agent, when publishing, then publish fails with a message naming the missing tool.
- **TS-09** — Given an identified call, when the verification tool runs, then the request carries `X-Identified-Ref`; given a failed verification, the model receives the uniform `say` text and not the API's reason.
- **TS-11** — Given an agent with no `is_verification` tool and a tool with `requires_verification`, when the model calls that tool, then no HTTP request is made and the result is `identity_not_verified` with the say text "I can't access account details on this line. I can connect you with a specialist who can."; with a verification tool attached, the say text is unchanged (TS-01).
- **TS-08** — Given a verified call, when any agent tool executes, then the request carries `X-Member-Ref` with the verified member reference; given an unverified call, the header is absent.
- **TS-10** — Given a tenant tool named `transfer_to_agent`, when created, then the API rejects it with 422 like the other built-in names.
