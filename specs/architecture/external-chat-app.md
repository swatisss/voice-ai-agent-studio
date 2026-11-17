---
type: Component Spec
title: External chat app
description: A separate Next.js customer chat app on port 3100 whose server holds a member API key and reaches the agents only through the public API - configuration, server routes, polling, resume and failure behavior.
status: stable
tags: [architecture, chat, public-api, integration]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Purpose

Show how an outside system uses the platform. `apps/chat/` is deliberately **not** part of the Studio: it has its own package, port and deployment, and can only do what an API key allows ([/api/public-api.md](/api/public-api.md)). Its look is in [/ui/chat-app.md](/ui/chat-app.md); the human part of a conversation is [/architecture/human-message-channel.md](/architecture/human-message-channel.md).

# Configuration (server environment)

| Variable | Default | Meaning |
|---|---|---|
| `VOICEAI_API_URL` | `http://localhost:8000` | Platform base URL |
| `VOICEAI_TENANT_ID` | `northgate-health` | Business unit of the key |
| `VOICEAI_API_KEY` | none | A `member` key (`vak_…`); required |
| `CHAT_BRAND_NAME` | `Northgate Health` | Name in the header and title |
| `PORT` | `3100` | Port of the app |

`apps/chat/.env.local` is git-ignored; `.env.example` lists the names only.

# Server routes (the only thing the browser calls)

| Route | Does |
|---|---|
| `POST /api/chat` | `{message?}` → creates a text conversation (`channel: text`, `external_id: web-<random>`, `metadata: {source: "chat-app"}`); returns `{conversation_id, items, cursor, status}` with the front desk's greeting and disclosure and, when a message was sent, the AI's reply |
| `POST /api/chat/{id}/messages` | `{text, cursor?}` (text 1 to 2000 characters, else 422 `invalid_message`) → sends the line, then returns what is new since `cursor`: `items`, `cursor`, `status`, `escalation` |
| `GET /api/chat/{id}/messages?cursor=` | proxies the platform poll; same shape |
| `POST /api/chat/{id}/end` | ends the conversation |

* The routes call only `/v1/tenants/{tenant}/…` with `Authorization: Bearer`. They never call `/api/*` and never forward the key, a platform URL or an upstream error body to the browser.
* The browser keeps `conversation_id` and `cursor` in `sessionStorage`; a reload resumes the thread.
* Polling: every 2 s while the conversation is `active` and a reply is awaited or `escalated`; every 5 s otherwise; stopped when `ended`. The poll pauses when the tab is hidden.

# Failure behavior

| Situation | The page |
|---|---|
| `VOICEAI_API_KEY` missing | routes answer 503 `chat_not_configured`; the page shows a setup panel (what to set, no secrets) instead of the chat |
| Platform unreachable or 5xx | a notice "We can't reach the assistant. Try again." with a **Retry** button; the typed text stays in the box |
| 429 `rate_limited` | the app waits `Retry-After` seconds and retries the poll silently; a send shows "One moment, please." |
| 404 for the conversation | the thread is cleared and a new chat is offered |
| 401 `invalid_key` | the same notice as unreachable; the log names a revoked key, the page never does |

# Acceptance

- **CHAT-01** — Given `VOICEAI_API_KEY` set, when the page is loaded and a chat is run, then the key does not appear in any response body, response header or the client bundle, and every upstream request carries `Authorization: Bearer` on a `/v1` path.
- **CHAT-02** — Given a chat started with "I want to check on a claim", then `POST /api/chat` creates one conversation through `POST /v1/tenants/{tenant}/conversations` with `channel: text`, and returns the greeting with the virtual-assistant disclosure and the agent's reply as items.
- **CHAT-03** — Given the key unset, then every `/api/chat*` route is 503 `chat_not_configured` and the page shows the setup panel and no input box.
- **CHAT-04** — Given a conversation that escalates and is then accepted and answered by a specialist, then successive polls return the `escalation` status `waiting`, then `accepted` with the assignee's first name, then the `human` items, then `ended` after resolve.
- **CHAT-05** — Given a thread in progress, when the page is reloaded, then the same conversation and thread are shown and polling continues from the stored cursor; given the platform answers 404, then a new chat is offered.
- **CHAT-06** — Given the platform answers 429 with `Retry-After: 3` to a poll, then the app polls again after 3 s with no visible error; given 503, then the retry notice shows and the typed text is kept.
