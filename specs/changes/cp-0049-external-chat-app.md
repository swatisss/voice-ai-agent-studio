---
type: Change Proposal
title: CP-0049 External chat app and the human message channel
description: A separate customer chat web app on its own port that talks to the agents only through the public API, plus the smallest platform change that lets a specialist type to the customer after an escalation.
status: stable
cp_state: implemented
tags: [public-api, chat, escalation, console, channels]
generated: { by: "claude-code/claude-sonnet-5-5", at: "2026-11-16T00:00:00Z" }
---

# Why

The platform proves itself through the Studio, the playground and a phone number. A real customer would use none of them: they would meet the agent inside another system, such as an insurer's website. The owner wants to show exactly that: a separate chat app, deployed and run on its own, that integrates only through the public API, shows the virtual-assistant disclaimer, and, when the AI escalates, tells the customer they are now talking to a human who then really answers.

Today that last step is impossible. The hand-off ends the AI call (CE-01), the specialist's console only accepts and resolves, and the public API has no way to carry a specialist's words back to the caller. The research in `.scratch/human-voice-and-channels/research/01-human-voice-phone-chat-whatsapp.md` found the same gap for WhatsApp and voice, so this change builds the **human message channel once**, for text.

# What changes

* **A new app, `apps/chat/`** (Next.js with server routes, port **3100**, so it runs beside the web app on :3000 and the API on :8000). Its server holds a `member` API key; the browser never sees it. It uses only `/v1` endpoints. The page looks like a real insurer chat: header, a standing disclaimer, bubbles, a typing indicator, and system notices when a specialist is being connected and when they join.
* **Human message channel (text only).** After a text conversation escalates it stays open for people: the customer's further messages are stored for the specialist (no AI reply), a specialist who has accepted the escalation can type replies from the console, the customer's app polls `GET /v1/.../conversations/{id}/messages`, and resolving the escalation ends the conversation. Voice and phone behave as before.
* **Agent console** gains a conversation panel for escalated text conversations: thread, composer, live refresh.
* **Data**: `call_events.kind` gains `human`.
* **Launcher**: `python scripts/dev.py --chat` also starts the chat app on :3100 and creates its API key on first run.

# Affected specs

* [/architecture/human-message-channel.md](/architecture/human-message-channel.md) - new (HMC-01..HMC-08)
* [/architecture/external-chat-app.md](/architecture/external-chat-app.md) - new (CHAT-01..CHAT-06)
* [/ui/chat-app.md](/ui/chat-app.md) - new (UI-83..UI-85)
* [/api/public-api.md](/api/public-api.md) - messages after escalation, `GET .../messages` (PUB-11, PUB-12)
* [/architecture/escalation.md](/architecture/escalation.md) - what happens to a text conversation after hand-off
* [/architecture/agent-desk.md](/architecture/agent-desk.md) - one more allowed call for the specialist
* [/ui/agent-console.md](/ui/agent-console.md) - conversation panel (UI-86)
* [/api/rest-api.md](/api/rest-api.md) - `POST /api/escalations/{id}/messages` (API-17)
* [/data/data-model.md](/data/data-model.md) - `human` event kind (DM-17)
* [/build/dev-launcher.md](/build/dev-launcher.md) - `--chat` (DEV-18)
* [/process/conventions.md](/process/conventions.md) - prefixes `HMC`, `CHAT`

# Acceptance criteria

New: HMC-01 to HMC-08, CHAT-01 to CHAT-06, PUB-11, PUB-12, UI-83 to UI-86, API-17, DM-17, DEV-18. Changed: DESK-02 (the allowed list gains the reply call), CE-01 reading (text API conversations stay open for the human). No existing ID is reused.

# Tasks

1. Spec edits (done in this CP).
2. Backend: after-escalation caller messages, `GET .../messages`, `POST /api/escalations/{id}/messages`, resolve ends the conversation, `human` events and the `escalation.message` console event, allow-list entry - covers HMC-01..08, PUB-11, PUB-12, API-17, DM-17, DESK-02.
3. Web console: conversation panel - covers UI-86.
4. `apps/chat/`: server routes and page - covers CHAT-01..06, UI-83..85.
5. Launcher `--chat` and key creation - covers DEV-18; README and runbook lines.
6. Tests (fake LLM, temp SQLite, no network): API tests with `Covers:` lines; chat app route tests with a stubbed platform; type check and build of both web apps.

# Risks and rollout

* Polling uses the key's request budget (default 120 per minute): the app polls every 2 s (30 per minute), and slows to 5 s when idle.
* A specialist's reply is outward text; it is delivered as typed. Specialists' own reads stay masked (DESK-05).
* The chat app is deployed on its own later (a second Cloud Run service); this CP covers running it locally. The WhatsApp and phone changes reuse the channel and are separate CPs.
* Existing Studio and playground text calls are unchanged: the channel applies to conversations created through `/v1`.

# Out of scope

Voice or phone human legs, live captions, WhatsApp, supervisor monitoring of live chats, attachments, typing indicators from the specialist, learning from the human lines (resolution notes stay the evidence), webhooks for each message, and hosting the chat app in the cloud.
