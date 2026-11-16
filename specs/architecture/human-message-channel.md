---
type: Component Spec
title: Human message channel
description: How a text conversation continues between the customer and a specialist after the AI hands off - customer lines stored for the human, specialist replies from the console, a polling endpoint for the customer's app, and resolution ending the conversation.
status: draft
tags: [architecture, escalation, public-api, chat, console]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Purpose

[Escalation](/architecture/escalation.md) ends the AI's part of a call (CE-01). For voice and phone the human takes over outside the platform. For a **text conversation created through the [public API](/api/public-api.md)** the conversation itself stays open, so a customer's app can show the specialist's words. One channel serves the [external chat app](/architecture/external-chat-app.md) and, later, other text channels.

# Rules

* **Scope.** Conversations with `source: api` and `channel: text`. Studio and playground calls, voice and phone are unchanged.
* **After escalation** the conversation `status` is `escalated` and stays so until it ends. The escalated segment's call is ended (`handoff`); human exchange events are stored on that call.
* **Customer lines.** `POST /v1/.../messages` on an escalated conversation stores the line as a `user` event with `data.to_human: true`, runs no model and no safety screen, and returns the turn result with `messages: []`, `status: escalated` and `escalation`. Empty or over-long text is rejected as usual.
* **Specialist replies.** `POST /api/escalations/{id}/messages` with `{text}` (1 to 2000 characters after trimming) by a specialist, admin or reviewer. 404 for an unknown escalation or another unit; 409 `not_accepted` unless the escalation is `accepted`; 409 `wrong_channel` unless its conversation is an API text conversation; 409 `conversation_ended` after the conversation ended. It stores a `human` event (`data.author` is the signed-in name) and publishes `escalation.message` `{escalation_id, seq}` on topic `console`. The reply is stored and delivered as typed (it is outward text); reads by a specialist stay masked ([/architecture/agent-desk.md](/architecture/agent-desk.md)).
* **Resolving ends it.** `POST /api/escalations/{id}/resolve` also ends the conversation: `status: ended`, `outcome: escalated`, `end_reason: human_resolved`, `ended_at` set, and the `conversation.ended` webhook is sent. A later customer message is 409 `conversation_ended`.
* **Customer leaving.** `POST /v1/.../end` on an escalated conversation ends it with `end_reason: caller_left`; the escalation row is untouched and can still be accepted and resolved for the record.

# Reading the thread

`GET /v1/tenants/{tenant_id}/conversations/{id}/messages?cursor=<opaque>` returns

```json
{ "status": "escalated", "escalation": { "id": "…", "status": "accepted", "assignee": "Sam" },
  "items": [ { "speaker": "caller", "text": "…", "at": "…" },
             { "speaker": "front_desk | agent | human", "text": "…", "at": "…" } ],
  "cursor": "…" }
```

* Items are the conversation's visible lines in order across segments: caller (`user`), front desk and agent (`assistant`) and `human`; no tool calls, system events or analysis. `speaker: human` items also carry `author` (first name).
* `cursor` identifies the last item returned; sending it back returns only later items. No cursor returns everything. A cursor that is not valid is 422 `invalid_cursor`.
* `escalation` is `null` before an escalation; `assignee` is the first name of the specialist once accepted, else `null`. `status` is the conversation's.
* Authentication, tenant, scope and rate limits are the public API's ([/api/public-api.md](/api/public-api.md)); another key's conversation is 404.

# Acceptance

- **HMC-01** — Given an API text conversation that has escalated, when the customer sends "Hello? Is someone there?", then the response has `status: escalated`, `messages: []` and an `escalation`, no LLM request is made, and the line is stored as a `user` event marked `to_human`.
- **HMC-02** — Given an escalated conversation with an AI exchange, a customer line and two specialist replies, when the app polls without a cursor, then the items are in order with speakers `caller`, `front_desk`/`agent`, `human`, contain no tool call, and a poll with the returned cursor after one more reply returns exactly that reply.
- **HMC-03** — Given an escalation in `waiting`, when a specialist posts a reply, then 409 `not_accepted` and nothing is stored; after `accept`, the reply is 201, stored as a `human` event with the specialist's name, and an `escalation.message` event is published on topic `console`.
- **HMC-04** — Given an accepted escalation of a voice call or a Studio test call, when a reply is posted, then 409 `wrong_channel`.
- **HMC-05** — Given an accepted escalation, when the specialist resolves it, then the conversation is `ended` with `end_reason: human_resolved`, a `conversation.ended` webhook is queued, the poll shows `status: ended`, and a further customer message and a further reply are 409 `conversation_ended`.
- **HMC-06** — Given an escalated conversation, when the customer ends it, then it is `ended` with `end_reason: caller_left` and the escalation can still be accepted and resolved.
- **HMC-07** — Given a specialist reply containing a telephone number, then the customer's poll returns it unchanged while the specialist's own read of the call masks it.
- **HMC-08** — Given a key of another tenant or scope, or an unknown conversation, then the poll is 404; a malformed cursor is 422 `invalid_cursor`; escalated voice conversations and phone calls behave as before (CE-01, TEL-07).
